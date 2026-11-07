"""
A simpler database viewer that lives alongside the legacy DatabaseDialog.

There are no focus modes and no show/hide checkboxes, just one rule that flows left to right:

    scope (session + selected reddit objects)  ->  results (Content | Posts)  ->  details (Post | Comments)

* Scope: the session dropdown and the reddit object list.  Nothing selected in the reddit object list means every
  reddit object.  The reddit object list is never narrowed by what is selected further to the right.
* Results: the items in the current scope, narrowed by the filters, shown in the Content or Posts tab.
* Details: the post (and its comments) for the selected item.  Comments are only loaded while the Comments tab is open.
* Filters: the viewer owns its filter state, a list of filter tuples per model name (REDDIT_OBJECT, POST, CONTENT,
  COMMENT).  On first run it is taken from settings_manager.database_view_default_filters.  Changes made in the filter
  panel are saved to QSettings and restored on the next run.

The layout is in database_viewer.ui (open it in Qt Designer).  Generate the python from it with:

    pyuic6 -o database_viewer_auto.py database_viewer.ui

Window geometry, splitter sizes, sort choices, the selected tabs, the post table columns and the thumbnail size are saved
in their own ini file (via QSettings) so this viewer does not depend on the settings manager.

To open it:
    from DownloaderForReddit.gui.database_views.database_viewer import DatabaseViewer
    self.database_viewer = DatabaseViewer()
    self.database_viewer.show()
"""
import html
import json
import logging

from PyQt6.QtCore import QItemSelectionModel, QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from DownloaderForReddit.guiresources.database_views.database_viewer_auto import Ui_DatabaseViewer
from DownloaderForReddit.database.models import DownloadSession, RedditObject, Post, Content, Comment
from DownloaderForReddit.database.filters import RedditObjectFilter, PostFilter, ContentFilter, CommentFilter
from DownloaderForReddit.utils import injector, system_util, general_utils
from DownloaderForReddit.viewmodels.database_view_models import (RedditObjectModel, PostTableModel, ContentListModel,
                                                                 CommentTreeModel)

SESSION_LIMIT = 200
DEFAULT_ICON_SIZE = 150
FILTER_MODELS = ('REDDIT_OBJECT', 'POST', 'CONTENT', 'COMMENT')
DEFAULT_POST_COLUMNS = ('title', 'date_posted', 'score', 'author', 'subreddit')
# Columns of the comment tree model: author, id, subreddit, body, body_html, score, date_posted, reddit_id
HIDDEN_COMMENT_COLUMNS = (1, 2, 4, 7)


# ---------------------------------------------------------------------------------------------------------------------
# Queries.  The whole scope rule lives here: a session narrows by download_session_id, selected reddit objects narrow by
# the post's significant reddit object.  These use the same constructs as the legacy dialog.
# ---------------------------------------------------------------------------------------------------------------------

def session_query(db_session):
    """The most recent download sessions, newest first."""
    return db_session.query(DownloadSession).order_by(DownloadSession.id.desc()).limit(SESSION_LIMIT)


def reddit_object_query(db_session, session_id):
    """Reddit objects, limited to the ones that have posts or content in the session if a session is selected."""
    query = db_session.query(RedditObject)
    if session_id is not None:
        subquery = db_session.query(Post.significant_reddit_object_id).join(Content) \
            .filter(Content.download_session_id == session_id) \
            .union(db_session.query(Post.significant_reddit_object_id).filter(Post.download_session_id == session_id))
        query = query.filter(RedditObject.id.in_(subquery))
    return query


def post_query(db_session, session_id, reddit_object_ids):
    query = db_session.query(Post)
    if session_id is not None:
        query = query.filter(Post.download_session_id == session_id)
    if reddit_object_ids:
        query = query.filter(Post.significant_reddit_object_id.in_(reddit_object_ids))
    return query


def content_query(db_session, session_id, reddit_object_ids):
    query = db_session.query(Content)
    if session_id is not None:
        query = query.filter(Content.download_session_id == session_id)
    if reddit_object_ids:
        posts = db_session.query(Post.id).filter(Post.significant_reddit_object_id.in_(reddit_object_ids))
        query = query.filter(Content.post_id.in_(posts))
    return query


def comment_query(db_session, post_ids):
    return db_session.query(Comment).filter(Comment.post_id.in_(post_ids))


# ---------------------------------------------------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------------------------------------------------

class SortBinding:
    """
    Ties together the sort field combo and the ascending/descending toggle button that are defined in the .ui file.
    Fills the combo, keeps the button's arrow in step, and loads and saves the choice.
    """

    def __init__(self, combo, button, fields):
        self.combo = combo
        self.button = button
        for field in fields:
            combo.addItem(field.replace('_', ' ').title(), field)
        self.update_button()
        button.toggled.connect(lambda _checked: self.update_button())

    @property
    def field(self):
        return self.combo.currentData()

    @property
    def desc(self):
        return self.button.isChecked()

    def connect(self, callback):
        """Calls callback (with no arguments) when the user changes the sort field or direction."""
        self.combo.currentIndexChanged.connect(lambda _index: callback())
        self.button.toggled.connect(lambda _checked: callback())

    def update_button(self):
        if self.button.isChecked():
            self.button.setText('\u2193')
            self.button.setToolTip('Descending')
        else:
            self.button.setText('\u2191')
            self.button.setToolTip('Ascending')

    def load(self, settings, name, default_field=None):
        """Loads the saved sort without notifying.  Falls back to default_field, then to the first field."""
        self.combo.blockSignals(True)
        self.button.blockSignals(True)
        index = self.combo.findData(settings.value(f'sort/{name}/field', default_field))
        if index < 0:
            index = self.combo.findData(default_field)
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self.button.setChecked(settings.value(f'sort/{name}/desc', False, type=bool))
        self.update_button()
        self.combo.blockSignals(False)
        self.button.blockSignals(False)

    def save(self, settings, name):
        settings.setValue(f'sort/{name}/field', self.field)
        settings.setValue(f'sort/{name}/desc', self.desc)


class DatabaseViewer(QWidget, Ui_DatabaseViewer):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.logger = logging.getLogger(f'DownloaderForReddit.{__name__}')
        self.settings_manager = injector.get_settings_manager()
        self.db = injector.get_database_handler()
        self.db_session = self.db.get_session()
        self.qsettings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, 'DownloaderForReddit',
                                   'DatabaseViewer')
        print(self.qsettings.fileName())

        self.current_content = []
        self.current_posts = []
        self.comment_key = None  # the post ids the comment tree currently shows, so it is not reloaded needlessly
        self.dirty_tabs = set()  # result tabs whose data is out of date and is reloaded when the tab is shown
        self.loading_scope = False
        self.icon_size = DEFAULT_ICON_SIZE
        self.filters = {name: [] for name in FILTER_MODELS}

        self.reddit_object_model = RedditObjectModel()
        self.content_model = ContentListModel()
        self.post_model = PostTableModel()
        self.comment_model = CommentTreeModel()
        self.models = {
            'REDDIT_OBJECT': self.reddit_object_model,
            'CONTENT': self.content_model,
            'POST': self.post_model,
            'COMMENT': self.comment_model
        }
        self.count_labels = {
            'REDDIT_OBJECT': self.reddit_object_count_label,
            'CONTENT': self.content_count_label,
            'POST': self.post_count_label,
            'COMMENT': self.comment_count_label
        }
        self.more_buttons = {
            'REDDIT_OBJECT': self.reddit_object_more_button,
            'CONTENT': self.content_more_button,
            'POST': self.post_more_button,
            'COMMENT': self.comment_more_button
        }

        self.result_timer = QTimer(self)
        self.result_timer.setSingleShot(True)
        self.result_timer.setInterval(100)
        self.result_timer.timeout.connect(self.reload_results)
        self.details_timer = QTimer(self)
        self.details_timer.setSingleShot(True)
        self.details_timer.setInterval(80)
        self.details_timer.timeout.connect(self.refresh_details)

        self.configure_views()
        self.connect_signals()
        self.load_settings()
        self.load_sessions()
        self.reload_scope()

    # -----------------------------------------------------------------------------------------------------------------
    # View setup (the layout itself is in database_viewer.ui)
    # -----------------------------------------------------------------------------------------------------------------

    def configure_views(self):
        """Attaches the models to the views and applies the settings that Designer cannot express."""
        self.filter_widget.setVisible(False)
        for button in self.more_buttons.values():
            button.setVisible(False)

        self.reddit_object_view.setModel(self.reddit_object_model)
        self.content_view.setModel(self.content_model)
        self.content_view.verticalScrollBar().setSingleStep(20)

        self.post_view.setModel(self.post_model)
        header = self.post_view.horizontalHeader()
        header.setSectionsMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        for index, name in enumerate(self.post_model.headers):
            header.setSectionHidden(index, name not in DEFAULT_POST_COLUMNS)

        self.comment_view.setModel(self.comment_model)
        for column in HIDDEN_COMMENT_COLUMNS:
            self.comment_view.setColumnHidden(column, True)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 4)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([220, 640, 340])

        self.reddit_object_sort = SortBinding(self.reddit_object_sort_combo, self.reddit_object_desc_button,
                                              RedditObjectFilter.get_order_fields())
        self.content_sort = SortBinding(self.content_sort_combo, self.content_desc_button,
                                        ContentFilter.get_order_fields())
        self.post_sort = SortBinding(self.post_sort_combo, self.post_desc_button, PostFilter.get_order_fields())
        self.comment_sort = SortBinding(self.comment_sort_combo, self.comment_desc_button,
                                        CommentFilter.get_order_fields())

    def connect_signals(self):
        self.session_combo.currentIndexChanged.connect(self.session_changed)
        self.refresh_button.clicked.connect(self.refresh)
        self.filter_button.toggled.connect(self.filter_widget.setVisible)
        self.filter_widget.filter_changed.connect(self.filter_changed)
        self.show_all_button.clicked.connect(self.reddit_object_view.clearSelection)

        self.reddit_object_sort.connect(lambda: self.reload_scope(keep_selection=True))
        self.content_sort.connect(lambda: self.reload_tab('CONTENT'))
        self.post_sort.connect(lambda: self.reload_tab('POST'))
        self.comment_sort.connect(self.reload_comments)

        self.reddit_object_view.selectionModel().selectionChanged.connect(self.reddit_object_selection_changed)
        self.content_view.selectionModel().selectionChanged.connect(self.content_selection_changed)
        self.post_view.selectionModel().selectionChanged.connect(self.post_selection_changed)
        self.comment_view.selectionModel().selectionChanged.connect(self.comment_selection_changed)
        self.results_tabs.currentChanged.connect(self.results_tab_changed)
        self.details_tabs.currentChanged.connect(self.details_tab_changed)

        self.icon_slider.valueChanged.connect(self.set_icon_size)
        self.content_view.doubleClicked.connect(self.open_selected_content)
        self.content_view.customContextMenuRequested.connect(self.content_context_menu)
        self.post_view.customContextMenuRequested.connect(self.post_context_menu)
        self.post_view.horizontalHeader().customContextMenuRequested.connect(self.post_header_context_menu)

        self.more_buttons['REDDIT_OBJECT'].clicked.connect(lambda: self.load_reddit_objects(extend=True))
        self.more_buttons['CONTENT'].clicked.connect(lambda: self.load_content(extend=True))
        self.more_buttons['POST'].clicked.connect(lambda: self.load_posts(extend=True))
        self.more_buttons['COMMENT'].clicked.connect(lambda: self.load_comments(extend=True))
        self.watch_scrollbar(self.reddit_object_view, 'REDDIT_OBJECT', self.load_reddit_objects)
        self.watch_scrollbar(self.content_view, 'CONTENT', self.load_content, 80)
        self.watch_scrollbar(self.post_view, 'POST', self.load_posts)
        self.watch_scrollbar(self.comment_view, 'COMMENT', self.load_comments)

        QApplication.instance().aboutToQuit.connect(self.save_settings)

    def watch_scrollbar(self, view, name, loader, percent=90):
        """Loads the next page when the view is scrolled to percent of the way down."""
        bar = view.verticalScrollBar()
        model = self.models[name]

        def check(_value):
            maximum = bar.maximum()
            if maximum > 0 and bar.value() / maximum * 100 >= percent and model.has_next_page and not model.loading:
                loader(extend=True)

        bar.valueChanged.connect(check)

    # -----------------------------------------------------------------------------------------------------------------
    # State
    # -----------------------------------------------------------------------------------------------------------------

    @property
    def current_tab_name(self):
        return 'CONTENT' if self.results_tabs.currentIndex() == 0 else 'POST'

    @property
    def session_id(self):
        return self.session_combo.currentData()

    def selected_reddit_objects(self):
        return self.reddit_object_model.get_items(self.reddit_object_view.selectedIndexes())

    def selected_reddit_object_ids(self):
        return [x.id for x in self.selected_reddit_objects()]

    def default_sort(self, attribute):
        """The sort the legacy dialog last saved, used the first time this viewer runs."""
        return getattr(self.settings_manager, attribute, None)

    # -----------------------------------------------------------------------------------------------------------------
    # Loading data
    # -----------------------------------------------------------------------------------------------------------------

    def load_sessions(self):
        """Fills the session dropdown, keeping the current session selected if it is still there."""
        current = self.session_id
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItem('All sessions', None)
        for dl_session in session_query(self.db_session).all():
            self.session_combo.addItem(dl_session.name or f'Session {dl_session.id}', dl_session.id)
        index = self.session_combo.findData(current)
        self.session_combo.setCurrentIndex(index if index >= 0 else 0)
        self.session_combo.blockSignals(False)

    def refresh(self):
        """Reloads everything from the database."""
        self.db_session.expire_all()
        self.load_sessions()
        self.reload_scope(keep_selection=True)

    def session_changed(self, _index):
        self.reload_scope()

    def filter_changed(self, model_names):
        for name in model_names:
            if name in self.filters:
                self.filters[name] = [tuple(item) for item in self.filter_widget.filter(name)]
        self.save_filters()
        if 'REDDIT_OBJECT' in model_names:
            self.reload_scope(keep_selection=True)
            return
        if 'POST' in model_names or 'CONTENT' in model_names:
            self.dirty_tabs.update(name for name in model_names if name in ('POST', 'CONTENT'))
            self.load_dirty_tab()
        if 'COMMENT' in model_names:
            self.reload_comments()

    def reload_scope(self, keep_selection=False):
        """
        Reloads the reddit object list, then the results for the new scope.  Reloading clears the list's selection, so
        keep_selection re-selects the reddit objects that were selected (the ones still in the loaded page).
        """
        selected_ids = self.selected_reddit_object_ids() if keep_selection else []
        self.loading_scope = True
        try:
            self.load_reddit_objects()
            self.select_reddit_objects(selected_ids)
        finally:
            self.loading_scope = False
        self.reload_results()

    def select_reddit_objects(self, ids):
        if not ids:
            return
        selection = self.reddit_object_view.selectionModel()
        for row, item in enumerate(self.reddit_object_model.items):
            if item.id in ids:
                selection.select(self.reddit_object_model.index(row, 0), QItemSelectionModel.SelectionFlag.Select)

    def reload_results(self):
        """Marks both result tabs as out of date and loads the visible one."""
        self.dirty_tabs = {'CONTENT', 'POST'}
        self.load_dirty_tab()

    def reload_tab(self, name):
        self.dirty_tabs.add(name)
        if name == self.current_tab_name:
            self.load_dirty_tab()

    def load_dirty_tab(self):
        name = self.current_tab_name
        if name in self.dirty_tabs:
            self.dirty_tabs.discard(name)
            if name == 'CONTENT':
                self.load_content()
            else:
                self.load_posts()

    def apply_query(self, name, query, extend):
        model = self.models[name]
        if extend:
            model.load_next_page(query)
            model.loading = False  # the comment model never resets this itself
        else:
            model.set_data(query)
        self.count_labels[name].setText(f'Showing {len(model.items)} of {model.total_items}')
        self.more_buttons[name].setVisible(model.has_next_page)

    def load_reddit_objects(self, extend=False):
        query = reddit_object_query(self.db_session, self.session_id)
        query = RedditObjectFilter().filter(self.db_session, *self.filters['REDDIT_OBJECT'], query=query,
                                            order_by=self.reddit_object_sort.field, desc=self.reddit_object_sort.desc)
        self.apply_query('REDDIT_OBJECT', query, extend)

    def load_content(self, extend=False):
        query = content_query(self.db_session, self.session_id, self.selected_reddit_object_ids())
        query = ContentFilter().filter(self.db_session, *self.filters['CONTENT'], query=query,
                                       order_by=self.content_sort.field, desc=self.content_sort.desc)
        self.apply_query('CONTENT', query, extend)
        if not extend:
            self.content_selection_changed()

    def load_posts(self, extend=False):
        query = post_query(self.db_session, self.session_id, self.selected_reddit_object_ids())
        query = PostFilter().filter(self.db_session, *self.filters['POST'], query=query,
                                    order_by=self.post_sort.field, desc=self.post_sort.desc)
        self.apply_query('POST', query, extend)
        if not extend:
            self.post_selection_changed()

    def load_comments(self, extend=False):
        query = comment_query(self.db_session, list(self.comment_key or ()))
        query = CommentFilter().filter(self.db_session, *self.filters['COMMENT'], query=query,
                                       order_by=self.comment_sort.field, desc=self.comment_sort.desc)
        self.apply_query('COMMENT', query, extend)
        if not extend:
            total = self.comment_model.total_items
            self.details_tabs.setTabText(1, f'Comments ({total})' if total else 'Comments')
            self.comment_browser.clear()

    def reload_comments(self):
        self.comment_key = None
        self.refresh_comments()

    # -----------------------------------------------------------------------------------------------------------------
    # Selection and details
    # -----------------------------------------------------------------------------------------------------------------

    def reddit_object_selection_changed(self, *_args):
        if not self.loading_scope:
            self.result_timer.start()

    def results_tab_changed(self, _index):
        try:
            self.filter_widget.filter_input_widget.set_model_combo(self.current_tab_name)
        except AttributeError:
            pass
        self.load_dirty_tab()
        self.schedule_details()

    def details_tab_changed(self, index):
        if index == 1:
            self.refresh_comments()

    def content_selection_changed(self, *_args):
        self.current_content = self.content_model.get_items(self.content_view.selectedIndexes())
        self.schedule_details()

    def post_selection_changed(self, *_args):
        self.current_posts = self.post_model.get_items(self.post_view.selectedIndexes())
        self.schedule_details()

    def schedule_details(self):
        self.details_timer.start()

    def details_posts(self):
        """The posts that the details panel shows: the posts of the selected content, or the selected posts."""
        if self.current_tab_name == 'POST':
            return list(self.current_posts)
        posts = []
        for content in self.current_content:
            post = content.post
            if post is not None and post not in posts:
                posts.append(post)
        return posts

    def refresh_details(self):
        posts = self.details_posts()
        content = self.current_content if self.current_tab_name == 'CONTENT' else []
        self.post_browser.setHtml(self.details_html(posts, content))
        if self.details_tabs.currentIndex() == 1:
            self.refresh_comments(posts)

    def refresh_comments(self, posts=None):
        """Loads the comments of the details posts, unless the tree already shows them."""
        if posts is None:
            posts = self.details_posts()
        key = tuple(sorted(post.id for post in posts))
        if key != self.comment_key:
            self.comment_key = key
            self.load_comments()

    def comment_selection_changed(self, *_args):
        comments = self.comment_model.get_items(self.comment_view.selectedIndexes()) or []
        if not comments:
            self.comment_browser.clear()
            return
        parts = []
        for comment in comments:
            author = html.escape(str(getattr(comment.author, 'name', comment.author)))
            body = comment.body_html if comment.body_html is not None else html.escape(comment.body or '')
            parts.append(f'<p><b>{author}</b></p>{body}')
        self.comment_browser.setHtml('<hr>'.join(parts))

    @staticmethod
    def details_html(posts, content):
        """The HTML for the Post section of the details panel."""
        if not posts and not content:
            return '<p>Select an item to see its details.</p>'
        parts = []
        if len(posts) > 1:
            parts.append(f'<p><b>{len(posts)} posts selected</b></p><ul>')
            parts.extend(f'<li>{html.escape(str(post.title))}</li>' for post in posts[:25])
            parts.append('</ul>')
            return ''.join(parts)
        if len(content) > 1:
            parts.append(f'<p>{len(content)} files selected</p>')
        elif content:
            item = content[0]
            parts.append(f'<p><b>{html.escape(str(item.title))}</b><br>{html.escape(str(item.get_full_file_path()))}')
            if item.error_message is not None:
                parts.append(f'<br>Error: {html.escape(str(item.error_message))}')
            parts.append('</p><hr>')
        if posts:
            post = posts[0]
            parts.append(f'<h3>{html.escape(str(post.title))}</h3>')
            author = html.escape(str(getattr(post.author, 'name', '')))
            subreddit = html.escape(str(getattr(post.subreddit, 'name', '')))
            parts.append(f'<p>{author} in r/{subreddit}<br>'
                         f'{html.escape(str(post.date_posted_display))} &middot; score {html.escape(str(post.score_display))}'
                         f'<br><a href="{html.escape(str(post.url))}">{html.escape(str(post.url))}</a></p>')
            if post.text_html:
                parts.append(post.text_html)
        return ''.join(parts)

    # -----------------------------------------------------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------------------------------------------------

    def set_icon_size(self, size):
        self.icon_size = size
        self.content_view.setIconSize(QSize(size, size))
        self.content_view.setGridSize(QSize(size + 2, size + 45))

    def open_selected_content(self, *_args):
        if self.current_content:
            system_util.open_in_system(self.current_content[0].get_full_file_path())

    def content_context_menu(self, _position):
        menu = QMenu(self)
        content = self.current_content[0] if self.current_content else None
        open_file = menu.addAction('Open', self.open_selected_content)
        open_file.setDisabled(content is None)
        open_folder = menu.addAction('Open folder',
                                     lambda: system_util.open_in_system(self.current_content[0].directory_path))
        open_folder.setDisabled(content is None)
        menu.exec(QCursor.pos())

    def post_context_menu(self, _position):
        menu = QMenu(self)
        post = self.current_posts[0] if self.current_posts else None
        visit = menu.addAction('Visit post', lambda: general_utils.open_post_in_browser(post))
        visit.setDisabled(post is None)
        copy_title = menu.addAction('Copy title', lambda: QApplication.clipboard().setText(post.title))
        copy_title.setDisabled(post is None)
        copy_url = menu.addAction('Copy URL', lambda: QApplication.clipboard().setText(post.url))
        copy_url.setDisabled(post is None)
        menu.exec(QCursor.pos())

    def post_header_context_menu(self, _position):
        """Lets the user choose which columns of the post table are shown."""
        header = self.post_view.horizontalHeader()
        menu = QMenu(self)
        for index, name in enumerate(self.post_model.headers):
            action = menu.addAction(name.replace('_', ' ').title())
            action.setCheckable(True)
            action.setChecked(not header.isSectionHidden(index))
            action.toggled.connect(lambda checked, i=index: header.setSectionHidden(i, not checked))
        menu.exec(QCursor.pos())

    # -----------------------------------------------------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------------------------------------------------

    def default_filters(self):
        """The filters from settings_manager.database_view_default_filters, as a fresh {model name: [tuples]} dict."""
        defaults = getattr(self.settings_manager, 'database_view_default_filters', None)
        if isinstance(defaults, dict) and 'Database View' in defaults:
            self.filter_widget.set_default_filters(*defaults['Database View'])

    def load_filters(self):
        """Loads the filters saved by this viewer, or the settings_manager defaults if none have been saved."""
        self.default_filters()
        saved = self.qsettings.value('filters')
        if saved:
            try:
                loaded = json.loads(saved)
                self.filter_widget.set_default_filters(loaded)
            except (TypeError, ValueError, AttributeError):
                self.logger.warning('Unable to read the saved database viewer filters, using the defaults',
                                    exc_info=True)

    def save_filters(self):
        try:
            filters = self.filter_widget.filters
            self.qsettings.setValue('filters', json.dumps(filters))
        except TypeError:
            self.logger.warning('The database viewer filters contain values that cannot be saved', exc_info=True)

    def load_settings(self):
        """Restores the saved window and view state.  Runs before any data is loaded."""
        qs = self.qsettings
        self.load_filters()
        geometry = qs.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        splitter_state = qs.value('splitter')
        if splitter_state:
            self.splitter.restoreState(splitter_state)
        comment_splitter_state = qs.value('comment_splitter')
        if comment_splitter_state:
            self.comment_splitter.restoreState(comment_splitter_state)
        header_state = qs.value('post_header')
        if header_state:
            self.post_view.horizontalHeader().restoreState(header_state)

        self.reddit_object_sort.load(qs, 'reddit_object', self.default_sort('database_view_reddit_object_order'))
        self.content_sort.load(qs, 'content', self.default_sort('database_view_content_order'))
        self.post_sort.load(qs, 'post', self.default_sort('database_view_post_order'))
        self.comment_sort.load(qs, 'comment', self.default_sort('database_view_comment_order'))

        self.icon_slider.blockSignals(True)
        size = qs.value('icon_size', self.default_sort('database_view_icon_size') or DEFAULT_ICON_SIZE, type=int)
        self.icon_slider.setValue(size)
        self.icon_slider.blockSignals(False)
        self.set_icon_size(self.icon_slider.value())

        self.results_tabs.blockSignals(True)
        self.results_tabs.setCurrentIndex(qs.value('results_tab', 0, type=int))
        self.results_tabs.blockSignals(False)
        self.details_tabs.blockSignals(True)
        self.details_tabs.setCurrentIndex(qs.value('details_tab', 0, type=int))
        self.details_tabs.blockSignals(False)
        try:
            self.filter_widget.filter_input_widget.set_model_combo(self.current_tab_name)
        except AttributeError:
            pass

    def save_settings(self):
        """Saves the window and view state.  Only does anything while the viewer is open."""
        if not self.isVisible():
            return
        qs = self.qsettings
        qs.setValue('geometry', self.saveGeometry())
        qs.setValue('splitter', self.splitter.saveState())
        qs.setValue('comment_splitter', self.comment_splitter.saveState())
        qs.setValue('post_header', self.post_view.horizontalHeader().saveState())
        self.reddit_object_sort.save(qs, 'reddit_object')
        self.content_sort.save(qs, 'content')
        self.post_sort.save(qs, 'post')
        self.comment_sort.save(qs, 'comment')
        qs.setValue('icon_size', self.icon_size)
        qs.setValue('results_tab', self.results_tabs.currentIndex())
        qs.setValue('details_tab', self.details_tabs.currentIndex())
        self.save_filters()
        qs.sync()

    def closeEvent(self, event): # pylint: disable=invalid-name
        self.save_settings()
        try:
            QApplication.instance().aboutToQuit.disconnect(self.save_settings)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)