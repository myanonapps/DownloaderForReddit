"""
A simpler database viewer that lives alongside the legacy DatabaseDialog.

There are no focus modes and no show/hide checkboxes, just one rule that flows in one direction:

    list (Reddit objects OR Sessions)  ->  results (Content | Posts)  ->  details (Post | Comments)

* Browse by: either reddit objects or download sessions, chosen with the two buttons above the list.  The modes are
  mutually exclusive and the two lists do not affect each other.
* The list: shows the items that match its own filters (REDDIT_OBJECT filters in the reddit object list, DOWNLOAD_SESSION
  filters in the session list) and exactly one of them is selected.  The previous selection of the mode is selected
  again if it is still listed, otherwise the first entry is.
* Results: the content or posts of the selected reddit object or session.  Posts are narrowed by the POST filters.
  Content is narrowed by the CONTENT filters and also by the POST filters (it is the content of the posts that pass
  them), so each filter narrows its own items and everything below them, in one direction.
* Details: the post (and its comments) for the selected item.  Comments are only loaded while the Comments tab is open.
* Paging: every list loads one page at a time (the page size is the model's, from settings_manager).  Each list has a
  'Load more' button and an 'Auto-load' checkbox that loads the next page when you scroll near the end.  Auto-load
  starts from settings_manager.database_view_<list>_infinite_scroll and your changes are saved in QSettings.
* Filters: the filter panel is the one place filters live.  On first run it is seeded from
  settings_manager.database_view_default_filters['Database View']; after that from the filters saved in QSettings, which
  are updated every time the panel changes.

The layout is in database_viewer.ui (open it in Qt Designer).  Generate the python from it with:

    pyuic6 -o database_viewer_auto.py database_viewer.ui

Window geometry, splitter sizes, sort choices, the selected tabs, the post table columns and the thumbnail size are saved
in their own ini file (via QSettings) so this viewer does not depend on the settings manager.

To open it:
    from DownloaderForReddit.gui.database_views.database_viewer import DatabaseViewer
    self.database_viewer = DatabaseViewer()
    self.database_viewer.show()
"""
import datetime
import enum
import html
import json
import logging

from PyQt6.QtCore import QItemSelectionModel, QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QPalette
from PyQt6.QtWidgets import QApplication, QMenu, QWidget
from sqlalchemy import or_

from DownloaderForReddit.core.const import ERROR_COLOR_HTML
from DownloaderForReddit.database.model_enums import NsfwFilter
from DownloaderForReddit.guiresources.database_views.database_viewer_auto import Ui_DatabaseViewer
from DownloaderForReddit.database.models import DownloadSession, RedditObject, Post, Content, Comment
from DownloaderForReddit.database.filters import (DownloadSessionFilter, RedditObjectFilter, PostFilter, ContentFilter,
                                                  CommentFilter)
from DownloaderForReddit.utils import injector, system_util, general_utils
from DownloaderForReddit.viewmodels.database_view_models import (DownloadSessionModel, RedditObjectModel,
                                                                 PostTableModel, ContentListModel, CommentTreeModel)
from DownloaderForReddit.core.errors import Error

SAVEABLE_ENUMS = {cls.__name__: cls for cls in (Error,NsfwFilter)}  # enums that may appear in a saved filter
DEFAULT_ICON_SIZE = 150
MODES = ('REDDIT_OBJECT', 'DOWNLOAD_SESSION')  # what the list on the left browses by
MAX_PAGES_TO_FIND = 50  # how many pages are loaded to find the remembered selection of a list
NO_ITEMS_TEXT = {'REDDIT_OBJECT': 'No reddit objects match the filters', 'DOWNLOAD_SESSION': 'No sessions match the filters'}
MODE_NOUN = {'REDDIT_OBJECT': 'Reddit object', 'DOWNLOAD_SESSION': 'Session'}
DEFAULT_POST_COLUMNS = ('title', 'date_posted', 'score', 'author', 'subreddit')
# Columns of the comment tree model: author, id, subreddit, body, body_html, score, date_posted, reddit_id
HIDDEN_COMMENT_COLUMNS = (1, 2, 4, 7)

def error_text(error):
    """'FORBIDDEN' (an Error member or its name) as 'Forbidden'."""
    return str(getattr(error, 'name', error)).replace('_', ' ').title()

# ---------------------------------------------------------------------------------------------------------------------
# Queries.  The results are the posts or content of the selected reddit object or the selected session.  A reddit object
# matches by being the post's significant reddit object, its author or its subreddit, so a reddit object that was only
# created because something was downloaded still has results.  With nothing selected (nothing is listed) nothing matches.
# ---------------------------------------------------------------------------------------------------------------------

def post_query(db_session, mode, scope_id):
    query = db_session.query(Post)
    if scope_id is None:
        return query.filter(Post.id.in_([]))
    if mode == 'DOWNLOAD_SESSION':
        return query.filter(Post.download_session_id == scope_id)
    return query.filter(or_(Post.significant_reddit_object_id == scope_id, Post.author_id == scope_id,
                            Post.subreddit_id == scope_id))


def content_query(db_session, mode, scope_id, post_ids=None):
    """post_ids is an optional query for the ids of the posts that the content must belong to (the POST filters)."""
    query = db_session.query(Content)
    if scope_id is None:
        return query.filter(Content.id.in_([]))
    if mode == 'DOWNLOAD_SESSION':
        query = query.filter(Content.download_session_id == scope_id)
    else:
        posts = db_session.query(Post.id).filter(Post.significant_reddit_object_id == scope_id)
        query = query.filter(or_(Content.post_id.in_(posts), Content.user_id == scope_id,
                                 Content.subreddit_id == scope_id))
    if post_ids is not None:
        query = query.filter(Content.post_id.in_(post_ids))
    return query


def comment_query(db_session, post_ids):
    return db_session.query(Comment).filter(Comment.post_id.in_(post_ids))


# ---------------------------------------------------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------------------------------------------------

def encode_filters(filter_items):
    """
    JSON text for FilterItems (their widget dicts, the form FilterWidget.set_default_filters takes).  Dates are kept
    as tagged ISO strings.  Raises TypeError if a value cannot be saved.
    """
    def encode_value(value):
        if isinstance(value, datetime.datetime):
            return {'__type__': 'datetime', 'value': value.isoformat()}
        if isinstance(value, datetime.date):
            return {'__type__': 'date', 'value': value.isoformat()}
        if isinstance(value, enum.Enum) and type(value).__name__ in SAVEABLE_ENUMS:
            return {'__type__': 'enum', 'enum': type(value).__name__, 'name': value.name}
        raise TypeError(f'Cannot save a filter value of type {type(value).__name__}')

    return json.dumps([item.widget_dict for item in filter_items], default=encode_value)


def decode_filters(text):
    """
    The list of filter dicts held in text that encode_filters made.  Raises ValueError if the text is not that.
    """
    def decode_value(obj):
        kind = obj.get('__type__')
        if kind == 'datetime':
            return datetime.datetime.fromisoformat(obj['value'])
        if kind == 'date':
            return datetime.date.fromisoformat(obj['value'])
        if kind == 'enum':
            try:
                return SAVEABLE_ENUMS[obj['enum']][obj['name']]
            except KeyError as e:
                raise ValueError('Unknown saved enum value') from e
        return obj

    loaded = json.loads(text, object_hook=decode_value)
    if not isinstance(loaded, list):
        raise ValueError('Saved filters are not a list')
    try:
        return [{'model': f['model'], 'field': f['field'], 'operator': f['operator'], 'value': f['value']}
                for f in loaded]
    except (KeyError, TypeError) as e:
        raise ValueError('Saved filter is missing a field') from e


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

    def load(self, settings, name, default_field=None, default_desc=False):
        """Loads the saved sort without notifying.  Falls back to the defaults, then to the first field."""
        self.combo.blockSignals(True)
        self.button.blockSignals(True)
        index = self.combo.findData(settings.value(f'sort/{name}/field', default_field))
        if index < 0:
            index = self.combo.findData(default_field)
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self.button.setChecked(settings.value(f'sort/{name}/desc', default_desc, type=bool))
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

        self.current_content = []
        self.current_posts = []
        self.comment_key = None  # the post ids the comment tree currently shows, so it is not reloaded needlessly
        self.dirty_tabs = set()  # result tabs whose data is out of date and is reloaded when the tab is shown
        self.loading_scope = False  # True while the list selection is being set by the code, not the user
        self.icon_size = DEFAULT_ICON_SIZE
        self.mode = 'REDDIT_OBJECT'
        self.selected_ids = {mode: None for mode in MODES}  # the selection each mode remembers
        self.dirty_lists = set()  # lists whose data is out of date and is reloaded when their mode is shown

        self.reddit_object_model = RedditObjectModel()
        self.download_session_model = DownloadSessionModel()
        self.content_model = ContentListModel()
        self.post_model = PostTableModel()
        self.comment_model = CommentTreeModel()
        self.models = {
            'REDDIT_OBJECT': self.reddit_object_model,
            'DOWNLOAD_SESSION': self.download_session_model,
            'CONTENT': self.content_model,
            'POST': self.post_model,
            'COMMENT': self.comment_model
        }
        self.views = {
            'REDDIT_OBJECT': self.reddit_object_view,
            'DOWNLOAD_SESSION': self.session_view
        }
        self.count_labels = {
            'REDDIT_OBJECT': self.reddit_object_count_label,
            'DOWNLOAD_SESSION': self.session_count_label,
            'CONTENT': self.content_count_label,
            'POST': self.post_count_label,
            'COMMENT': self.comment_count_label
        }
        self.more_buttons = {
            'REDDIT_OBJECT': self.reddit_object_more_button,
            'DOWNLOAD_SESSION': self.session_more_button,
            'CONTENT': self.content_more_button,
            'POST': self.post_more_button,
            'COMMENT': self.comment_more_button
        }
        self.auto_checks = {
            'REDDIT_OBJECT': self.reddit_object_auto_check,
            'DOWNLOAD_SESSION': self.session_auto_check,
            'CONTENT': self.content_auto_check,
            'POST': self.post_auto_check,
            'COMMENT': self.comment_auto_check
        }
        self.auto_load = {name: True for name in self.auto_checks}  # loaded from the settings by load_settings

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
        self.dirty_lists = set(MODES) - {self.mode}
        self.reload_list(self.mode)

    # -----------------------------------------------------------------------------------------------------------------
    # View setup (the layout itself is in database_viewer.ui)
    # -----------------------------------------------------------------------------------------------------------------

    def configure_views(self):
        """Attaches the models to the views and applies the settings that Designer cannot express."""
        self.filter_widget.setVisible(False)
        for button in self.more_buttons.values():
            button.setVisible(False)

        self.reddit_object_view.setModel(self.reddit_object_model)
        self.session_view.setModel(self.download_session_model)
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
        self.session_sort = SortBinding(self.session_sort_combo, self.session_desc_button,
                                        DownloadSessionFilter.get_order_fields())
        self.content_sort = SortBinding(self.content_sort_combo, self.content_desc_button,
                                        ContentFilter.get_order_fields())
        self.post_sort = SortBinding(self.post_sort_combo, self.post_desc_button, PostFilter.get_order_fields())
        self.comment_sort = SortBinding(self.comment_sort_combo, self.comment_desc_button,
                                        CommentFilter.get_order_fields())

    def connect_signals(self):
        self.reddit_object_mode_button.toggled.connect(lambda checked: self.mode_toggled('REDDIT_OBJECT', checked))
        self.session_mode_button.toggled.connect(lambda checked: self.mode_toggled('DOWNLOAD_SESSION', checked))
        self.refresh_button.clicked.connect(self.refresh)
        self.filter_button.toggled.connect(self.filter_widget.setVisible)
        self.filter_widget.filter_changed.connect(self.filter_changed)

        self.reddit_object_sort.connect(lambda: self.reload_list('REDDIT_OBJECT'))
        self.session_sort.connect(lambda: self.reload_list('DOWNLOAD_SESSION'))
        self.content_sort.connect(lambda: self.reload_tab('CONTENT'))
        self.post_sort.connect(lambda: self.reload_tab('POST'))
        self.comment_sort.connect(self.reload_comments)

        self.reddit_object_view.selectionModel().selectionChanged.connect(self.scope_selection_changed)
        self.session_view.selectionModel().selectionChanged.connect(self.scope_selection_changed)
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
        self.more_buttons['DOWNLOAD_SESSION'].clicked.connect(lambda: self.load_download_sessions(extend=True))
        self.more_buttons['CONTENT'].clicked.connect(lambda: self.load_content(extend=True))
        self.more_buttons['POST'].clicked.connect(lambda: self.load_posts(extend=True))
        self.more_buttons['COMMENT'].clicked.connect(lambda: self.load_comments(extend=True))
        self.watch_scrollbar(self.reddit_object_view, 'REDDIT_OBJECT', self.load_reddit_objects)
        self.watch_scrollbar(self.session_view, 'DOWNLOAD_SESSION', self.load_download_sessions)
        self.watch_scrollbar(self.content_view, 'CONTENT', self.load_content, 80)
        self.watch_scrollbar(self.post_view, 'POST', self.load_posts)
        self.watch_scrollbar(self.comment_view, 'COMMENT', self.load_comments)
        for name, check in self.auto_checks.items():
            check.toggled.connect(lambda checked, n=name: self.auto_load_toggled(n, checked))

        QApplication.instance().aboutToQuit.connect(self.save_settings)

    def watch_scrollbar(self, view, name, loader, percent=90):
        """Loads the next page when the view is scrolled to percent of the way down."""
        scroll_bar = view.verticalScrollBar()
        model = self.models[name]

        def check(_value):
            maximum = scroll_bar.maximum()
            if (self.auto_load[name] and maximum > 0 and scroll_bar.value() / maximum * 100 >= percent
                    and model.has_next_page and not model.loading):
                loader(extend=True)

        scroll_bar.valueChanged.connect(check)

    def auto_load_toggled(self, name, checked):
        self.auto_load[name] = checked

    # -----------------------------------------------------------------------------------------------------------------
    # State
    # -----------------------------------------------------------------------------------------------------------------

    @property
    def current_tab_name(self):
        return 'CONTENT' if self.results_tabs.currentIndex() == 0 else 'POST'

    @property
    def scope_id(self):
        """The id of the selected reddit object or session (depending on the mode), None if nothing is listed."""
        items = self.models[self.mode].get_items(self.views[self.mode].selectedIndexes()) or []
        return items[0].id if items else None

    def default_sort(self, attribute):
        """The sort the legacy dialog last saved, used the first time this viewer runs."""
        return getattr(self.settings_manager, attribute, None)

    def default_desc(self, attribute, fallback=False):
        value = getattr(self.settings_manager, attribute, None)
        return fallback if value is None else bool(value)

    # -----------------------------------------------------------------------------------------------------------------
    # Loading data
    # -----------------------------------------------------------------------------------------------------------------

    def refresh(self):
        """Reloads everything from the database."""
        self.db_session.expire_all()
        self.dirty_lists = set(MODES) - {self.mode}
        self.reload_list(self.mode)

    def filter_changed(self, model_names):
        self.save_filters()
        list_reloaded = False
        for mode in MODES:
            if mode in model_names:
                self.reload_list(mode)
                list_reloaded = list_reloaded or mode == self.mode
        if not list_reloaded and ('POST' in model_names or 'CONTENT' in model_names):
            if 'POST' in model_names:
                self.dirty_tabs.update(('POST', 'CONTENT'))  # POST filters narrow the content as well
            if 'CONTENT' in model_names:
                self.dirty_tabs.add('CONTENT')
            self.load_dirty_tab()
        if 'COMMENT' in model_names:
            self.reload_comments()

    def mode_toggled(self, mode, checked):
        if checked:
            self.set_mode(mode)

    def set_mode(self, mode):
        """Switches the list on the left.  Its list is reloaded first if its filters changed while it was hidden."""
        self.mode = mode
        self.browse_stack.setCurrentIndex(MODES.index(mode))
        if mode in self.dirty_lists:
            self.reload_list(mode)
        else:
            self.update_scope_label()
            self.reload_results()

    def reload_list(self, mode):
        """
        Reloads the first page of the mode's list (the items that pass its filters) and selects the remembered item,
        or the first one, then reloads the results.  A list that is not showing is only marked out of date.
        """
        if mode != self.mode:
            self.dirty_lists.add(mode)
            return
        self.dirty_lists.discard(mode)
        self.loading_scope = True
        try:
            self.load_list(mode)
            self.select_remembered(mode)
        finally:
            self.loading_scope = False
        self.update_scope_label()
        self.reload_results()

    def load_list(self, mode, extend=False):
        if mode == 'REDDIT_OBJECT':
            self.load_reddit_objects(extend)
        else:
            self.load_download_sessions(extend)

    @staticmethod
    def row_of(model, item_id):
        if item_id is not None:
            for row, item in enumerate(model.items):
                if item.id == item_id:
                    return row
        return None

    def select_remembered(self, mode):
        """
        Selects the item the mode remembers.  It may be on a page that is not loaded yet, so pages are loaded until it
        turns up.  If it is no longer listed (the filters changed) the first item is selected instead.
        """
        model, view = self.models[mode], self.views[mode]
        wanted = self.selected_ids[mode]
        row = self.row_of(model, wanted)
        pages = 0
        while row is None and wanted is not None and model.has_next_page and pages < MAX_PAGES_TO_FIND:
            self.load_list(mode, extend=True)
            pages += 1
            row = self.row_of(model, wanted)
        if row is None and model.items:
            row = 0
        if row is None:
            self.selected_ids[mode] = None
            view.clearSelection()
            return
        index = model.index(row, 0)
        view.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        view.scrollTo(index)
        self.selected_ids[mode] = model.items[row].id

    def scope_selection_changed(self, *_args):
        """The user selected something in the list on the left."""
        if self.loading_scope:
            return
        if self.scope_id is None and self.models[self.mode].items:
            # clicking cannot leave the list without a selection
            self.loading_scope = True
            try:
                self.select_remembered(self.mode)
            finally:
                self.loading_scope = False
            return
        self.selected_ids[self.mode] = self.scope_id
        self.update_scope_label()
        self.result_timer.start()

    def update_scope_label(self):
        """Says what the results show."""
        items = self.models[self.mode].get_items(self.views[self.mode].selectedIndexes()) or []
        if items:
            name = getattr(items[0], 'name', None) or f'{MODE_NOUN[self.mode]} {items[0].id}'
            self.scope_label.setText(f'{MODE_NOUN[self.mode]}: {name}')
        else:
            self.scope_label.setText(NO_ITEMS_TEXT[self.mode])

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
        query = self.db_session.query(RedditObject)
        query = RedditObjectFilter().filter(self.db_session, *self.filter_widget.filter('REDDIT_OBJECT'), query=query,
                                            order_by=self.reddit_object_sort.field, desc=self.reddit_object_sort.desc)
        self.apply_query('REDDIT_OBJECT', query, extend)

    def load_download_sessions(self, extend=False):
        query = self.db_session.query(DownloadSession)
        query = DownloadSessionFilter().filter(self.db_session, *self.filter_widget.filter('DOWNLOAD_SESSION'),
                                               query=query, order_by=self.session_sort.field,
                                               desc=self.session_sort.desc)
        self.apply_query('DOWNLOAD_SESSION', query, extend)

    def filtered_post_ids(self):
        """A query for the ids of the posts that pass the POST filters, or None if there are no POST filters."""
        filters = self.filter_widget.filter('POST')
        if not filters:
            return None
        query = PostFilter().filter(self.db_session, *filters, query=self.db_session.query(Post),
                                    order_by=self.post_sort.field, desc=self.post_sort.desc)
        return query.with_entities(Post.id).order_by(None)

    def load_content(self, extend=False):
        query = content_query(self.db_session, self.mode, self.scope_id, self.filtered_post_ids())
        query = ContentFilter().filter(self.db_session, *self.filter_widget.filter('CONTENT'), query=query,
                                       order_by=self.content_sort.field, desc=self.content_sort.desc)
        self.apply_query('CONTENT', query, extend)
        if not extend:
            self.content_selection_changed()

    def load_posts(self, extend=False):
        query = post_query(self.db_session, self.mode, self.scope_id)
        query = PostFilter().filter(self.db_session, *self.filter_widget.filter('POST'), query=query,
                                    order_by=self.post_sort.field, desc=self.post_sort.desc)
        self.apply_query('POST', query, extend)
        if not extend:
            self.post_selection_changed()

    def load_comments(self, extend=False):
        query = comment_query(self.db_session, list(self.comment_key or ()))
        query = CommentFilter().filter(self.db_session, *self.filter_widget.filter('COMMENT'), query=query,
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

    def detail_colors(self):
        """Text colors taken from the browser's palette so the panel follows light and dark themes."""
        palette = self.post_browser.palette()
        base = palette.color(QPalette.ColorRole.Base)
        text = palette.color(QPalette.ColorRole.Text)
        red = QColor(ERROR_COLOR_HTML)

        def blend(one, other, ratio):
            return QColor(*(int(a * (1 - ratio) + b * ratio) for a, b in zip(one.getRgb()[:3], other.getRgb()[:3])))

        return {'text': text.name(), 'muted': blend(text, base, 0.45).name(), 'tint': blend(base, red, 0.15).name(),
                'badge': blend(base, text, 0.15).name()}

    @staticmethod
    def label_html(text, colors):
        return f'<p style="color:{colors["muted"]}; font-size:8pt; margin-bottom:2px"><b>{html.escape(text)}</b></p>'

    @staticmethod
    def error_banner_html(title, message, details, colors):
        """A red-barred block: bold title, the message, and a muted details line."""
        lines = f'<b style="color:{ERROR_COLOR_HTML}">! {html.escape(title)}</b>'
        if message:
            lines += f'<br>{html.escape(str(message))}'
        if details:
            lines += f'<br><span style="color:{colors["muted"]}">{html.escape(details)}</span>'
        return (f'<table width="100%" cellspacing="0" cellpadding="6"><tr><td width="4" bgcolor="{ERROR_COLOR_HTML}"></td>'
                f'<td bgcolor="{colors["tint"]}">{lines}</td></tr></table>')

    def post_error_html(self, post, colors):
        details = [f'Retries: {post.retry_attempts or 0}']
        if post.extraction_date_display:
            details.append(f'Last attempt: {post.extraction_date_display}')
        return self.error_banner_html(f'EXTRACTION FAILED \u00b7 {error_text(post.extraction_error)}',
                                      post.error_message, '  \u00b7  '.join(details), colors)

    @staticmethod
    def post_header_html(post, colors):
        esc = html.escape
        parts = [f'<h2 style="margin-top:8px; margin-bottom:2px">{esc(str(post.title))}</h2>']
        badges = [name for name, flag in (('NSFW', post.nsfw), ('Self post', post.is_self)) if flag]
        if badges:
            parts.append('<p style="margin-top:0; margin-bottom:2px">' + ' '.join(
                f'<span style="background-color:{colors["badge"]}">&nbsp;{esc(b)}&nbsp;</span>' for b in badges)
                         + '</p>')
        author = esc(str(getattr(post.author, 'name', '')))
        subreddit = esc(str(getattr(post.subreddit, 'name', '')))
        parts.append(f'<p style="margin-top:0; color:{colors["muted"]}">u/{author} in r/{subreddit}</p>')
        return ''.join(parts)

    @staticmethod
    def post_meta_html(post, colors):
        esc = html.escape
        if post.extraction_error is not None:
            status = f'<span style="color:{ERROR_COLOR_HTML}">Failed</span>'
        else:
            status = 'Extracted' if post.extracted else 'Not extracted'
        score = f'{post.score:,}' if post.score is not None else ''
        muted = f'style="color:{colors["muted"]}"'
        url = esc(str(post.url))
        return (f'<table width="100%" cellspacing="0" cellpadding="3">'
                f'<tr><td {muted}>Posted</td><td>{esc(str(post.date_posted_display))}</td>'
                f'<td {muted}>Score</td><td>{score}</td></tr>'
                f'<tr><td {muted}>Domain</td><td>{esc(str(post.domain))}</td>'
                f'<td {muted}>Status</td><td>{status}</td></tr>'
                f'<tr><td {muted}>Link</td><td colspan="3"><a href="{url}">{url}</a></td></tr></table>')

    def file_card_html(self, content, colors):
        esc = html.escape
        failed = [item for item in content if item.download_error is not None]
        if len(content) > 1:
            text = f'{len(content)} files selected'
            if failed:
                text += f' <span style="color:{ERROR_COLOR_HTML}">({len(failed)} failed)</span>'
            return self.label_html('FILE', colors) + f'<p style="margin-top:0">{text}</p>'
        item = content[0]
        parts = [self.label_html('FILE', colors), f'<p style="margin-top:0"><b>{esc(str(item.title))}</b><br>'
                 f'<span style="color:{colors["muted"]}">{esc(str(item.get_full_file_path()))}</span></p>']
        if item.download_error is not None:
            parts.append(self.error_banner_html(f'DOWNLOAD FAILED \u00b7 {error_text(item.download_error)}',
                                                item.error_message, f'Retries: {item.retry_attempts or 0}', colors))
        return ''.join(parts)

    def multiple_posts_html(self, posts, colors):
        failed = sum(1 for post in posts if post.extraction_error is not None)
        header = f'<h3 style="margin-bottom:2px">{len(posts)} posts selected</h3>'
        if failed:
            header += f'<p style="margin-top:0; color:{ERROR_COLOR_HTML}">{failed} with errors</p>'
        items = []
        for post in posts[:25]:
            mark = f'<span style="color:{ERROR_COLOR_HTML}">! </span>' if post.extraction_error is not None else ''
            items.append(f'<li>{mark}{html.escape(str(post.title))}</li>')
        more = (f'<p style="color:{colors["muted"]}">and {len(posts) - 25} more</p>' if len(posts) > 25 else '')
        return f'{header}<ul>{"".join(items)}</ul>{more}'

    def details_html(self, posts, content):
        """The HTML for the Post section of the details panel."""
        colors = self.detail_colors()
        if not posts and not content:
            return f'<p align="center" style="color:{colors["muted"]}"><br>Select an item to see its details.</p>'
        if len(posts) > 1:
            return self.multiple_posts_html(posts, colors)
        post = posts[0] if posts else None
        sections = []
        if post is not None and post.extraction_error is not None:
            sections.append(self.post_error_html(post, colors))
        if post is not None:
            sections.append(self.post_header_html(post, colors))
            sections.append(self.post_meta_html(post, colors))
        if content:
            sections.append(self.file_card_html(content, colors))
        if post is not None:
            if post.text_html:
                sections.append(post.text_html)
            else:
                sections.append(f'<p style="color:{colors["muted"]}"><i>This post has no text</i></p>')
        return '<hr>'.join(sections)
    # -----------------------------------------------------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------------------------------------------------

    def set_icon_size(self, size):
        self.icon_size = size
        self.content_view.setIconSize(QSize(size, size))
        self.content_view.setGridSize(QSize(size + 24, size + 36))

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
        """The filter dicts in settings_manager.database_view_default_filters['Database View']."""
        defaults = getattr(self.settings_manager, 'database_view_default_filters', None)
        if isinstance(defaults, dict):
            return [dict(item) for item in defaults.get('Database View') or []]
        return []

    def load_filters(self):
        """
        Seeds the filter panel with the filters saved by this viewer, or with the settings_manager defaults if none have
        been saved yet.  The panel's signals are blocked while it is seeded: nothing is loaded until setup is complete.
        """
        filters = None
        saved = self.qsettings.value('filters')
        if isinstance(saved, (list, tuple)):  # an ini file may hand back text that contains commas as a list
            saved = ','.join(saved)
        if saved:
            try:
                filters = decode_filters(saved)
            except ValueError:
                self.logger.warning('Unable to read the saved database viewer filters, using the defaults',
                                    exc_info=True)
        if filters is None:
            filters = self.default_filters()
        self.filter_widget.blockSignals(True)
        try:
            self.filter_widget.set_default_filters(*filters)
        except Exception: # pylint: disable=broad-except
            self.logger.warning('Unable to set the filters on the filter widget', exc_info=True)
        finally:
            self.filter_widget.blockSignals(False)

    def save_filters(self):
        """Saves the filters that are currently in the filter panel."""
        try:
            self.qsettings.setValue('filters', encode_filters(self.filter_widget.filters.values()))
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

        sorts = (('reddit_object', self.reddit_object_sort), ('download_session', self.session_sort),
                 ('content', self.content_sort), ('post', self.post_sort), ('comment', self.comment_sort))
        for name, sort in sorts:
            # the legacy dialog's saved sort is the default; sessions are newest first if the legacy has no setting
            sort.load(qs, name, self.default_sort(f'database_view_{name}_order'),
                      self.default_desc(f'database_view_{name}_desc_order', fallback=name == 'download_session'))

        mode = qs.value('mode')
        self.mode = mode if mode in MODES else 'REDDIT_OBJECT'
        for mode_name in MODES:
            try:
                self.selected_ids[mode_name] = int(qs.value(f'selected/{mode_name}'))
            except (TypeError, ValueError):
                self.selected_ids[mode_name] = None
        for button, mode_name in ((self.reddit_object_mode_button, 'REDDIT_OBJECT'),
                                  (self.session_mode_button, 'DOWNLOAD_SESSION')):
            button.blockSignals(True)
            button.setChecked(self.mode == mode_name)
            button.blockSignals(False)
        self.browse_stack.setCurrentIndex(MODES.index(self.mode))

        for name, check in self.auto_checks.items():
            default = getattr(self.settings_manager, f'database_view_{name.lower()}_infinite_scroll', True)
            self.auto_load[name] = qs.value(f'auto_load/{name}', bool(default), type=bool)
            check.blockSignals(True)
            check.setChecked(self.auto_load[name])
            check.blockSignals(False)

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
        self.session_sort.save(qs, 'download_session')
        qs.setValue('mode', self.mode)
        for name, enabled in self.auto_load.items():
            qs.setValue(f'auto_load/{name}', enabled)
        for mode_name in MODES:
            if self.selected_ids[mode_name] is not None:
                qs.setValue(f'selected/{mode_name}', self.selected_ids[mode_name])
            else:
                qs.remove(f'selected/{mode_name}')
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
