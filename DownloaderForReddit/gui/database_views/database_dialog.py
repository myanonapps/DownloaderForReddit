import functools
import logging
from PyQt6.QtWidgets import (QMenu, QWidget, QInputDialog, QAbstractItemView, QWidgetAction, QCheckBox,
                             QApplication, QSplitter)
from PyQt6.QtCore import QByteArray, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QActionGroup, QClipboard
from sqlalchemy import or_

from DownloaderForReddit.core.const import SUBREDDIT_OBJECT, USER_OBJECT
from DownloaderForReddit.guiresources.database_views.database_dialog_auto import Ui_DatabaseDialog
from DownloaderForReddit.database.models import DownloadSession, RedditObject, Post, Content, Comment
from DownloaderForReddit.database.filters import (DownloadSessionFilter, RedditObjectFilter, PostFilter, CommentFilter,
                                                  ContentFilter)
from DownloaderForReddit.database.model_manager import ModelManger
from DownloaderForReddit.viewmodels.database_view_models import (DownloadSessionModel, RedditObjectModel,
                                                                 PostTableModel, ContentListModel, CommentTreeModel)
from DownloaderForReddit.gui.blank_dialog import BlankDialog
from DownloaderForReddit.gui.export_wizard import ExportWizard
from DownloaderForReddit.utils import injector, system_util, general_utils


def hold_setup(method):
    """
    Decorator method that sets a hold flag before the method is called and releases it after.  This is used to avoid
    infinite looping calls when a monitored attribute must be changed.

    The previous value of the flag is restored (rather than blindly cleared) so holds can nest, and the flag is always
    released, even if the wrapped method raises.  Otherwise a single exception would leave the hold set for the rest of
    the session and every @check_hold method would silently do nothing.
    """
    @functools.wraps(method)
    def set_hold(instance, *args, **kwargs):
        previous = instance.hold_setup
        instance.hold_setup = True
        try:
            return method(instance, *args, **kwargs)
        finally:
            instance.hold_setup = previous
    return set_hold


def check_hold(method):
    """
    Checks a hold flag before calling the supplied method.  This is used so that monitored attributes can be changed
    without causing an infinite loop.  Passing override_hold=True runs the method even while the hold is set.
    The override_hold keyword is always consumed here, so the wrapped method never receives it.
    """
    @functools.wraps(method)
    def check(instance, *args, **kwargs):
        override = kwargs.pop('override_hold', False)
        if not instance.hold_setup or override:
            return method(instance, *args, **kwargs)
        return None
    return check


class DatabaseDialog(QWidget, Ui_DatabaseDialog):

    download_signal = pyqtSignal(list)
    update_post_score_signal = pyqtSignal(list)
    update_post_comments_signal = pyqtSignal(list)

    def __init__(self, save_settings=True, **setup_kwargs):
        """
        save_settings: True if the dialog settings should be saved on close.  Pass False for a specialty view (such
            as failed downloads) whose layout must not overwrite the user's saved database view.
        setup_kwargs fields:
            visible_models: The models that will be visible on start
            <model_name>_sort: The sort attribute that will be used on start for the model name
            <model_name>_desc: Dictates whether the model_name sort should be in desc. order
            focus_model: The model that will have focus on start
            filters: A list of filter tuples that will be used to filter models on start
                filter tuple order: (model, attribute_field, operator, value)
        """
        QWidget.__init__(self)
        self.setupUi(self)
        self.logger = logging.getLogger(f'DownloaderForReddit.{__name__}')
        self.settings_manager = injector.get_settings_manager()
        self.db = injector.get_database_handler()
        self.session = self.db.get_session()
        self.hold_setup = False
        self.save_settings = save_settings
        self.setup_kwargs = setup_kwargs

        self.setup_call_list = []

        geom = self.settings_manager.database_view_geom
        self.resize(geom['width'], geom['height'])
        if geom['x'] != 0 and geom['y'] != 0 and self.position_is_on_screen(geom['x'], geom['y']):
            self.move(geom['x'], geom['y'])
        self.download_session_widget.resize(self.settings_manager.database_view_download_session_widget_width, 0)
        self.reddit_object_widget.resize(self.settings_manager.database_view_reddit_object_widget_width, 0)
        self.post_widget.resize(self.settings_manager.database_view_post_widget_width, 0)
        self.content_widget.resize(self.settings_manager.database_view_content_widget_width, 0)
        self.comment_widget.resize(self.settings_manager.database_view_comment_widget_width, 0)

        self.filter_widget.set_default_filters(*self.setup_kwargs.get('filters', []))
        self.filter_widget.setVisible(False)
        self.filter_button.clicked.connect(self.toggle_filter)

        self.data_setup_filter_map = {
            'DOWNLOAD_SESSION': self.setup_download_sessions,
            'REDDIT_OBJECT': self.setup_reddit_objects,
            'POST': self.setup_posts,
            'CONTENT': self.setup_content,
            'COMMENT': self.setup_comments
        }
        self.filter_widget.filter_changed.connect(self.update_filtering)

        self.model_visibility_map = {
            'DOWNLOAD_SESSION': self.show_download_sessions_checkbox,
            'REDDIT_OBJECT': self.show_reddit_objects_checkbox,
            'POST': self.show_posts_checkbox,
            'CONTENT': self.show_content_checkbox,
            'COMMENT': self.show_comments_checkbox
        }
        try:
            visible_models = self.setup_kwargs['visible_models']
            for model in visible_models:
                self.model_visibility_map[model].setChecked(True)
        except KeyError:
            self.show_download_sessions_checkbox.setChecked(self.settings_manager.database_view_show_download_sessions)
            self.show_reddit_objects_checkbox.setChecked(self.settings_manager.database_view_show_reddit_objects)
            self.show_posts_checkbox.setChecked(self.settings_manager.database_view_show_posts)
            self.show_content_checkbox.setChecked(self.settings_manager.database_view_show_content)
            self.show_comments_checkbox.setChecked(self.settings_manager.database_view_show_comments)

        for x in DownloadSessionFilter.get_order_fields():
            self.download_session_sort_combo.addItem(x.replace('_', ' ').title(), x)
        for x in RedditObjectFilter.get_order_fields():
            self.reddit_object_sort_combo.addItem(x.replace('_', ' ').title(), x)
        for x in PostFilter.get_order_fields():
            self.post_sort_combo.addItem(x.replace('_', ' ').title(), x)
        for x in ContentFilter.get_order_fields():
            self.content_sort_combo.addItem(x.replace('_', ' ').title(), x)
        for x in CommentFilter.get_order_fields():
            self.comment_sort_combo.addItem(x.replace('_', ' ').title(), x)

        # The setup_kwargs value wins, then the saved setting, then the first entry in the combo.  Falling back to the
        # first entry keeps a stale saved field (renamed/removed) from leaving the combo blank and sorting by None.
        sort_widgets = (
            (self.download_session_sort_combo, 'download_session_sort',
             self.settings_manager.database_view_download_session_order),
            (self.reddit_object_sort_combo, 'reddit_object_sort',
             self.settings_manager.database_view_reddit_object_order),
            (self.post_sort_combo, 'post_sort', self.settings_manager.database_view_post_order),
            (self.content_sort_combo, 'content_sort', self.settings_manager.database_view_content_order),
            (self.comment_sort_combo, 'comment_sort', self.settings_manager.database_view_comment_order)
        )
        for combo, kwarg_key, saved_value in sort_widgets:
            self.select_combo_data(combo, self.setup_kwargs.get(kwarg_key), saved_value)

        desc_widgets = (
            (self.download_session_desc_sort_checkbox, 'download_session_desc',
             self.settings_manager.database_view_download_session_desc_order),
            (self.reddit_object_desc_sort_checkbox, 'reddit_object_desc',
             self.settings_manager.database_view_reddit_object_desc_order),
            (self.post_desc_sort_checkbox, 'post_desc', self.settings_manager.database_view_post_desc_order),
            (self.content_desc_sort_checkbox, 'content_desc', self.settings_manager.database_view_content_desc_order),
            (self.comment_desc_sort_checkbox, 'comment_desc', self.settings_manager.database_view_comment_desc_order)
        )
        for checkbox, kwarg_key, saved_value in desc_widgets:
            checkbox.setChecked(bool(self.setup_kwargs.get(kwarg_key, saved_value)))

        self.download_session_sort_combo.currentIndexChanged.connect(self.change_download_session_sort)
        self.reddit_object_sort_combo.currentIndexChanged.connect(self.change_reddit_object_sort)
        self.post_sort_combo.currentIndexChanged.connect(self.change_post_sort)
        self.content_sort_combo.currentIndexChanged.connect(self.change_content_sort)
        self.comment_sort_combo.currentIndexChanged.connect(self.change_comment_sort)

        self.download_session_desc_sort_checkbox.toggled.connect(self.change_download_session_sort)
        self.reddit_object_desc_sort_checkbox.toggled.connect(self.change_reddit_object_sort)
        self.post_desc_sort_checkbox.toggled.connect(self.change_post_sort)
        self.content_desc_sort_checkbox.toggled.connect(self.change_content_sort)
        self.comment_desc_sort_checkbox.toggled.connect(self.change_comment_sort)

        self.icon_size = self.settings_manager.database_view_icon_size

        self.current_download_session = []
        self.current_reddit_object = []
        self.current_post = []
        self.current_content = []
        self.current_comment = []

        self.download_session_model = DownloadSessionModel()
        self.download_session_list_view.setModel(self.download_session_model)
        self.download_session_model.update_count.connect(lambda x: self.update_count_label(x, 'DOWNLOAD_SESSION'))

        self.reddit_object_model = RedditObjectModel()
        self.reddit_object_list_view.setModel(self.reddit_object_model)
        self.reddit_object_model.update_count.connect(lambda x: self.update_count_label(x, 'REDDIT_OBJECT'))

        self.post_model = PostTableModel()
        self.post_table_view.setModel(self.post_model)
        self.post_model.update_count.connect(lambda x: self.update_count_label(x, 'POST'))
        self.post_text_browser.setVisible(False)
        self.post_text_browser.attach_signal.connect(self.attach_post_text_browser)
        self.post_text_browser.detach_signal.connect(self.detach_post_text_browser)
        post_headers = self.post_table_view.horizontalHeader()
        post_headers.setStretchLastSection(True)
        post_headers.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        post_headers.customContextMenuRequested.connect(self.post_headers_context_menu)
        post_headers.setSectionsMovable(True)
        # State (column order/widths) is restored first; the visibility settings are applied after so they stay the
        # authority on which columns are hidden.
        self.restore_header_state(post_headers, 'database_view_post_table_header_state')
        self.apply_header_visibility(post_headers, self.post_model.headers,
                                     self.settings_manager.database_view_post_table_headers)

        self.set_content_icon_size()
        self.content_model = ContentListModel()
        self.content_list_view.setModel(self.content_model)
        self.content_model.update_count.connect(lambda x: self.update_count_label(x, 'CONTENT'))
        self.content_list_view.setBatchSize(1)
        self.content_list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.content_list_view.verticalScrollBar().setSingleStep(20)

        self.comment_tree_model = CommentTreeModel()
        self.comment_tree_view.setModel(self.comment_tree_model)
        self.comment_tree_model.update_count.connect(lambda x: self.update_count_label(x, 'COMMENT'))
        self.comment_tree_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        self.download_session_widget.setVisible(self.show_download_sessions)
        self.reddit_object_widget.setVisible(self.show_reddit_objects)
        self.post_widget.setVisible(self.show_posts)
        self.content_widget.setVisible(self.show_content)
        self.comment_widget.setVisible(self.show_comments)

        self.comment_text_browser.setVisible(False)
        self.comment_text_browser.attach_signal.connect(self.attach_comment_text_browser)
        self.comment_text_browser.detach_signal.connect(self.detach_comment_text_browser)

        self.show_download_sessions_checkbox.stateChanged.connect(self.toggle_download_session_view)
        self.show_reddit_objects_checkbox.stateChanged.connect(self.toggle_reddit_object_view)
        self.show_posts_checkbox.stateChanged.connect(self.toggle_post_view)
        self.show_content_checkbox.stateChanged.connect(self.toggle_content_view)
        self.show_comments_checkbox.stateChanged.connect(self.toggle_comment_view)

        self.model_button_link_map = {
            self.download_session_model: self.load_more_download_sessions_button,
            self.reddit_object_model: self.load_more_reddit_objects_button,
            self.post_model: self.load_more_posts_button,
            self.content_model: self.load_more_content_button,
            self.comment_tree_model: self.load_more_comments_button
        }

        self.infinite_scroll_map = {
            self.download_session_model: self.settings_manager.database_view_download_session_infinite_scroll,
            self.reddit_object_model: self.settings_manager.database_view_reddit_object_infinite_scroll,
            self.post_model: self.settings_manager.database_view_post_infinite_scroll,
            self.content_model: self.settings_manager.database_view_content_infinite_scroll,
            self.comment_tree_model: self.settings_manager.database_view_comment_infinite_scroll
        }

        self.download_session_list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.reddit_object_list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.post_table_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.content_list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.comment_tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        self.download_session_list_view.selectionModel().selectionChanged.connect(self.set_current_download_session)
        self.reddit_object_list_view.selectionModel().selectionChanged.connect(self.set_current_reddit_object)
        self.post_table_view.selectionModel().selectionChanged.connect(self.set_current_post)
        self.content_list_view.selectionModel().selectionChanged.connect(self.set_current_content)
        self.comment_tree_view.selectionModel().selectionChanged.connect(self.set_current_comment)

        self.content_list_view.doubleClicked.connect(self.open_selected_content)

        self.download_session_list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.download_session_list_view.customContextMenuRequested.connect(self.download_session_view_context_menu)

        self.reddit_object_list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.reddit_object_list_view.customContextMenuRequested.connect(self.reddit_object_context_menu)

        self.post_table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.post_table_view.customContextMenuRequested.connect(self.post_view_context_menu)

        self.content_list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.content_list_view.customContextMenuRequested.connect(self.content_view_context_menu)

        self.comment_tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.comment_tree_view.customContextMenuRequested.connect(self.comment_view_context_menu)

        comment_headers = self.comment_tree_view.header()
        comment_headers.setSectionsMovable(True)
        comment_headers.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        comment_headers.customContextMenuRequested.connect(self.comment_header_context_menu)
        self.restore_header_state(comment_headers, 'database_view_comment_tree_header_state')
        self.apply_header_visibility(comment_headers, self.comment_tree_model.headers,
                                     self.settings_manager.database_view_comment_tree_headers)

        self.download_session_focus_radio.toggled.connect(lambda x: self.focus_on('DOWNLOAD_SESSION') if x else None)
        self.reddit_object_focus_radio.toggled.connect(lambda x: self.focus_on('REDDIT_OBJECT') if x else None)
        self.post_focus_radio.toggled.connect(lambda x: self.focus_on('POST') if x else None)
        self.content_focus_radio.toggled.connect(lambda x: self.focus_on('CONTENT') if x else None)
        self.comment_focus_radio.toggled.connect(lambda x: self.focus_on('COMMENT') if x else None)
        self.focus_map = {
            'DOWNLOAD_SESSION': self.download_session_focus_radio,
            'REDDIT_OBJECT': self.reddit_object_focus_radio,
            'POST': self.post_focus_radio,
            'CONTENT': self.content_focus_radio,
            'COMMENT': self.comment_focus_radio
        }
        self.focus_map[self.setup_kwargs.get('focus_model', self.settings_manager.database_view_focus_model)]\
            .setChecked(True)
        selected_model_id = self.setup_kwargs.get('selected_model_id', None)
        if selected_model_id is not None:
            self.set_current_item(selected_model_id)

        self.download_session_list_view.verticalScrollBar().valueChanged.connect(lambda: self.monitor_scrollbar(
            self.download_session_list_view.verticalScrollBar(), self.download_session_model,
            self.set_download_session_data
        ))
        self.reddit_object_list_view.verticalScrollBar().valueChanged.connect(lambda: self.monitor_scrollbar(
            self.reddit_object_list_view.verticalScrollBar(), self.reddit_object_model, self.set_reddit_object_data
        ))
        self.post_table_view.verticalScrollBar().valueChanged.connect(lambda: self.monitor_scrollbar(
            self.post_table_view.verticalScrollBar(), self.post_model, self.set_post_data
        ))
        self.content_list_view.verticalScrollBar().valueChanged.connect(lambda: self.monitor_scrollbar(
            self.content_list_view.verticalScrollBar(), self.content_model, self.set_content_data, 80
        ))
        self.comment_tree_view.verticalScrollBar().valueChanged.connect(lambda: self.monitor_scrollbar(
            self.comment_tree_view.verticalScrollBar(), self.comment_tree_model, self.set_comment_data
        ))

        self.load_more_download_sessions_button.clicked.connect(lambda: self.load_next_page(
            self.download_session_model, self.set_download_session_data))
        self.load_more_reddit_objects_button.clicked.connect(lambda: self.load_next_page(
            self.reddit_object_model, self.set_reddit_object_data))
        self.load_more_posts_button.clicked.connect(lambda: self.load_next_page(
            self.post_model, self.set_post_data))
        self.load_more_content_button.clicked.connect(lambda: self.load_next_page(
            self.content_model, self.set_content_data))
        self.load_more_comments_button.clicked.connect(lambda: self.load_next_page(
            self.comment_tree_model, self.set_comment_data))

        for model, button in self.model_button_link_map.items():
            button.setVisible(model.has_next_page)

        self.restore_pane_widths()

    def toggle_filter(self):
        self.filter_widget.setVisible(not self.filter_widget.isVisible())

    def update_filtering(self, model_names):
        for name in model_names:
            data_setup_method = self.data_setup_filter_map[name]
            data_setup_method()

    def check_call_list(self, call):
        contains = call in self.setup_call_list
        if not contains:
            self.setup_call_list.append(call)
        return contains

    @property
    def cascade(self):
        return len(self.setup_call_list) == 0

    @property
    def download_session_focus(self):
        return self.download_session_focus_radio.isChecked()

    @property
    def reddit_object_focus(self):
        return self.reddit_object_focus_radio.isChecked()

    @property
    def post_focus(self):
        return self.post_focus_radio.isChecked()

    @property
    def content_focus(self):
        return self.content_focus_radio.isChecked()

    @property
    def comment_focus(self):
        return self.comment_focus_radio.isChecked()

    @property
    def current_focus_model(self):
        if self.download_session_focus:
            return self.download_session_model
        elif self.reddit_object_focus:
            return self.reddit_object_model
        elif self.post_focus:
            return self.post_model
        elif self.content_focus:
            return self.content_model
        else:
            return self.comment_tree_model

    @property
    def current_focus_view(self):
        if self.download_session_focus:
            return self.download_session_list_view
        elif self.reddit_object_focus:
            return self.reddit_object_list_view
        elif self.post_focus:
            return self.post_table_view
        elif self.content_focus:
            return self.content_list_view
        else:
            return self.comment_tree_view

    @property
    def show_download_sessions(self):
        return self.show_download_sessions_checkbox.isChecked()

    @property
    def show_reddit_objects(self):
        return self.show_reddit_objects_checkbox.isChecked()

    @property
    def show_posts(self):
        return self.show_posts_checkbox.isChecked()

    @property
    def show_content(self):
        return self.show_content_checkbox.isChecked()

    @property
    def show_comments(self):
        return self.show_comments_checkbox.isChecked()

    def check_visibility(self, model_name):
        if model_name == 'DOWNLOAD_SESSION':
            return self.show_download_sessions
        elif model_name == 'REDDIT_OBJECT':
            return self.show_reddit_objects
        elif model_name == 'POST':
            return self.show_posts
        elif model_name == 'CONTENT':
            return self.show_content
        elif model_name == 'COMMENT':
            return self.show_comments

    @property
    def download_session_order(self):
        return self.download_session_sort_combo.currentData(Qt.ItemDataRole.UserRole)

    @property
    def download_session_desc(self):
        return self.download_session_desc_sort_checkbox.isChecked()

    @property
    def reddit_object_order(self):
        return self.reddit_object_sort_combo.currentData(Qt.ItemDataRole.UserRole)

    @property
    def reddit_object_desc(self):
        return self.reddit_object_desc_sort_checkbox.isChecked()

    @property
    def post_order(self):
        return self.post_sort_combo.currentData(Qt.ItemDataRole.UserRole)

    @property
    def post_desc(self):
        return self.post_desc_sort_checkbox.isChecked()

    @property
    def comment_order(self):
        return self.comment_sort_combo.currentData(Qt.ItemDataRole.UserRole)

    @property
    def comment_desc(self):
        return self.comment_desc_sort_checkbox.isChecked()

    @property
    def content_order(self):
        return self.content_sort_combo.currentData(Qt.ItemDataRole.UserRole)

    @property
    def content_desc(self):
        return self.content_desc_sort_checkbox.isChecked()

    def current_download_session_attr(self, attr):
        try:
            return [getattr(x, attr) for x in self.current_download_session]
        except AttributeError:
            return None

    def current_reddit_object_attr(self, attr):
        try:
            return [getattr(x, attr) for x in self.current_reddit_object]
        except AttributeError:
            return None

    def current_post_attr(self, attr):
        try:
            return [getattr(x, attr) for x in self.current_post]
        except AttributeError:
            return None

    def current_content_attr(self, attr):
        try:
            return [getattr(x, attr) for x in self.current_content]
        except AttributeError:
            return None

    def current_comment_attr(self, attr):
        try:
            return [getattr(x, attr) for x in self.current_comment]
        except AttributeError:
            return None

    @property
    def current_download_session_id(self):
        return self.current_download_session_attr('id')

    @property
    def current_reddit_object_id(self):
        return self.current_reddit_object_attr('id')

    @property
    def current_user_id(self):
        return [x.id for x in self.current_reddit_object if x.object_type == USER_OBJECT]

    @property
    def current_subreddit_id(self):
        return [x.id for x in self.current_reddit_object if x.object_type == SUBREDDIT_OBJECT]

    @property
    def current_reddit_object_significant(self):
        return self.current_reddit_object_attr('significant_reddit_object_id')

    @property
    def current_reddit_object_type(self):
        try:
            types = self.current_reddit_object_attr('object_type')
            first = types[0]
            if all(x == first for x in types):
                return first
            else:
                return 'MIXED'
        except (IndexError, TypeError):
            return None

    @property
    def current_post_id(self):
        return self.current_post_attr('id')

    @property
    def current_content_id(self):
        return self.current_content_attr('id')

    @property
    def current_comment_id(self):
        return self.current_comment_attr('id')

    def download_session_view_context_menu(self):
        menu = QMenu()
        try:
            dl_session = \
                self.download_session_model.get_item(self.download_session_list_view.selectedIndexes()[0].row())
        except Exception:
            dl_session = None
        except BaseException:
            self.logger.exception("Somebody is throwing something of BaseException")
            dl_session = None
        rename = menu.addAction('Rename Session', lambda: self.rename_download_session(dl_session))
        rename.setDisabled(dl_session is None)
        menu.addSeparator()
        menu.addAction('Select All', self.download_session_list_view.selectAll)
        menu.exec(QCursor.pos())

    def reddit_object_context_menu(self):
        menu = QMenu()
        try:
            ro = self.reddit_object_model.get_item(self.reddit_object_list_view.selectedIndexes()[0].row())
        except Exception:
            ro = None
        except BaseException:
            self.logger.exception("Somebody is throwing something of BaseException")
            ro = None
        oepn_dl_folder = menu.addAction('Open Download Folder', self.open_download_folder)
        menu.addSeparator()
        export_all = menu.addAction('Export All', self.export_all_reddit_objects) # pylint: disable=unused-variable
        export_selected = menu.addAction('Export Selected', self.export_selected_reddit_objects) # pylint: disable=unused-variable
        menu.addSeparator()
        download = menu.addAction('Download', self.download_reddit_object)
        menu.addSeparator()
        export_ro = menu.addAction('Export', self.export_reddit_object) # pylint: disable=unused-variable
        menu.addSeparator()
        delete_menu = menu.addMenu('Delete Selected')
        delete_menu.addAction('Reddit Objects', lambda: self.delete_selected_reddit_objects(delete_files=False))
        delete_menu.addAction('Reddit Objects and Content Files',
                              lambda: self.delete_selected_reddit_objects(delete_files=True))
        menu.addSeparator()
        menu.addAction('Select All', self.reddit_object_list_view.selectAll)

        if ro is None:
            oepn_dl_folder.setDisabled(True)
            download.setDisabled(True)
        menu.exec(QCursor.pos())

    def open_download_folder(self):
        reddit_object = self.reddit_object_model.get_item(self.reddit_object_list_view.selectedIndexes()[0].row())
        general_utils.open_reddit_object_download_folder(reddit_object, self)

    def export_all_reddit_objects(self):
        self.export_reddit_objects(self.get_reddit_object_data())

    def export_selected_reddit_objects(self):
        selected = self.reddit_object_list_view.selectedIndexes()
        self.export_reddit_objects(self.reddit_object_model.get_items(selected))

    def export_reddit_objects(self, ro_list):
        wizard = ExportWizard(ro_list, RedditObject)
        wizard.exec()

    def download_reddit_object(self):
        reddit_objects = self.reddit_object_model.get_item(self.reddit_object_list_view.selectedIndexes())
        self.download_signal.emit([x.id for x in reddit_objects])

    def export_reddit_object(self):
        wizard = ExportWizard(self.current_reddit_object, RedditObject)
        wizard.exec()

    def delete_selected_reddit_objects(self, delete_files=False):
        reddit_objects = self.reddit_object_model.get_items(self.reddit_object_list_view.selectedIndexes())
        for ro in reddit_objects:
            ModelManger.delete_reddit_object(ro, session=self.session, delete_files=delete_files)
        self.reddit_object_model.remove_items(reddit_objects)
        self.setup_reddit_objects()

    def post_view_context_menu(self):
        menu = QMenu()
        try:
            post = self.post_model.get_item(self.post_table_view.selectedIndexes()[0].row())
        except Exception:
            post = None
        except BaseException:
            self.logger.exception("Somebody is throwing something of BaseException")
            post = None

        open_post = menu.addAction('Visit Post', lambda: general_utils.open_post_in_browser(post))

        copy_menu = menu.addMenu('Copy To Clipboard')
        copy_menu.addAction('Title', lambda: self.copy_to_clipboard(post.title))
        copy_menu.addAction('Url', lambda: self.copy_to_clipboard(post.url))
        copy_menu.addAction('Domain', lambda: self.copy_to_clipboard(post.domain))
        copy_menu.addAction('Author', lambda: self.copy_to_clipboard(post.author.name))
        copy_menu.addAction('Subreddit', lambda: self.copy_to_clipboard(post.subreddit.name))

        menu.addSeparator()
        update_score = menu.addAction('Update Score', self.update_post_scores)
        update_comments = menu.addAction('Fetch New Comments', self.update_post_comments)
        menu.addSeparator()
        export_all = menu.addAction('Export All Posts', self.export_all_posts) # pylint: disable=unused-variable
        export_selected = menu.addAction('Export Selected Posts', self.export_selected_posts) # pylint: disable=unused-variable
        menu.addSeparator()
        delete_menu = menu.addMenu('Delete Selected')
        delete_menu.addAction('Posts', lambda: self.delete_selected_posts(delete_files=False))
        delete_menu.addAction('Posts and Files', lambda: self.delete_selected_posts(delete_files=True))
        menu.addSeparator()
        menu.addAction('Select All', self.post_table_view.selectAll)

        open_post.setDisabled(post is None)
        update_score.setDisabled(post is None)
        update_comments.setDisabled(post is None)
        menu.exec(QCursor.pos())

    def copy_to_clipboard(self, text):
        cb = QApplication.clipboard()
        cb.clear(mode=QClipboard.Mode.Clipboard)
        cb.setText(text)

    def update_post_scores(self):
        self.update_post_score_signal.emit(self.current_post_id)

    def update_post_comments(self):
        self.update_post_comments_signal.emit(self.current_post_id)

    def export_all_posts(self):
        self.export_posts(self.get_post_data().all())

    def export_selected_posts(self):
        selected_indices = self.post_table_view.selectedIndexes()
        self.export_posts(self.post_model.get_items(selected_indices))

    def delete_selected_posts(self, delete_files):
        selected_posts = self.post_model.get_items(self.post_table_view.selectedIndexes())
        for post in selected_posts:
            ModelManger.delete_post(post, session=self.session, delete_files=delete_files)
        self.post_model.remove_items(selected_posts)
        self.setup_posts()

    def export_posts(self, post_list):
        wizard = ExportWizard(post_list, Post)
        wizard.exec()

    def post_headers_context_menu(self):
        """
        Displays a context menu for the post table header which allows the user to select which headers will be visible.
        """
        menu = QMenu()
        for value in self.post_model.headers:
            name = value.replace('_', ' ').replace(' display', '')
            checkbox = QCheckBox(menu)
            checkbox.setText(name)
            checkbox.setChecked(self.settings_manager.database_view_post_table_headers.get(value, True))
            checkbox.toggled.connect(lambda x, header=value: self.toggle_post_table_header(header))
            action = QWidgetAction(menu)
            action.setDefaultWidget(checkbox)
            menu.addAction(action)
        menu.exec(QCursor.pos())

    def attach_post_text_browser(self):
        """Closes the post text browser dialog and adds it back to the main dialog window."""
        self.post_text_splitter.addWidget(self.post_text_browser)
        self.post_text_browser.stand_alone = False

    def detach_post_text_browser(self):
        """Detaches the post text browser from the main dialog window and displays it as a separate dialog."""
        dialog = BlankDialog(parent=self)
        dialog.setWindowTitle(self.current_post[0].title)
        dialog.add_widgets(self.post_text_browser)
        dialog.closing.connect(self.post_text_browser.handle_dialog_movement)
        dialog.setWhatsThis('Displays the text from the selected post.  Close dialog to re-attach text box.')
        dialog.show()
        self.post_text_browser.stand_alone = True

    def attach_comment_text_browser(self):
        self.comment_text_splitter.addWidget(self.comment_text_browser)
        self.comment_text_browser.stand_alone = False

    def detach_comment_text_browser(self):
        dialog = BlankDialog(parent=self)
        dialog.add_widgets(self.comment_text_browser)
        dialog.closing.connect(self.comment_text_browser.handle_dialog_movement)
        dialog.setWhatsThis('Displays the text from the selected comment.  Close dialog to re-attach text box.')
        dialog.show()
        self.comment_text_browser.stand_alone = True

    def toggle_post_table_header(self, header):
        """
        Hides or shows the supplied post table header based on its currently visibility. (hidden headers will be shown,
        visible headers will be hidden)
        :param header: The header that is to be toggled.
        """
        index = self.post_model.headers.index(header)
        headers = dict(self.settings_manager.database_view_post_table_headers)
        visible = headers.get(header, True)
        headers[header] = not visible
        self.assign_setting('database_view_post_table_headers', headers)
        # sets the table header visibility to the opposite of what visible originally was
        self.post_table_view.horizontalHeader().setSectionHidden(index, visible)

    def content_view_context_menu(self):
        menu = QMenu()
        try:
            content = self.content_model.get_item(self.content_list_view.selectedIndexes()[0].row())
        except Exception:
            content = None
        except BaseException:
            self.logger.exception("Somebody is throwing something of BaseException")
            content = None

        open_directory = menu.addAction('Open Directory', lambda: system_util.open_in_system(content.directory_path))
        open_directory.setDisabled(content is None)
        menu.addSeparator()
        export_all = menu.addAction('Export All', self.export_all_content) # pylint: disable=unused-variable
        export_selected = menu.addAction('Export Selected', self.export_selected_content) # pylint: disable=unused-variable
        menu.addSeparator()
        delete_menu = menu.addMenu('Delete Selected')
        delete_menu.addAction('Content Only',
                              lambda: self.delete_selected_content(delete_post=False, delete_file=False))
        delete_menu.addAction('Content with Post',
                              lambda: self.delete_selected_content(delete_post=True, delete_file=False))
        delete_menu.addAction('Content with File',
                              lambda: self.delete_selected_content(delete_post=False, delete_file=True))
        delete_menu.addAction('Content with Post and File',
                              lambda: self.delete_selected_content(delete_post=True, delete_file=True))
        menu.addSeparator()

        icon_menu = QMenu('Icon Size')
        action_group = QActionGroup(self)
        extra_small_item = self.add_icon_menu_item(icon_menu, action_group, 'Extra Small', 72) # pylint: disable=unused-variable
        small_item = self.add_icon_menu_item(icon_menu, action_group, 'Small', 110) # pylint: disable=unused-variable
        medium_item = self.add_icon_menu_item(icon_menu, action_group, 'Medium', 176) # pylint: disable=unused-variable
        large_item = self.add_icon_menu_item(icon_menu, action_group, 'Large', 256) # pylint: disable=unused-variable
        extra_large_item = self.add_icon_menu_item(icon_menu, action_group, 'Extra Large', 420) # pylint: disable=unused-variable
        custom_item = self.add_icon_menu_item(icon_menu, action_group, 'Custom', None, connect=False)
        custom_item.triggered.connect(self.set_custom_content_icon_size)
        if not any(x.isChecked() for x in icon_menu.actions()):
            custom_item.setChecked(True)
            custom_item.setText(custom_item.text() + f' ({self.icon_size})')
        menu.addMenu(icon_menu)

        menu.exec(QCursor.pos())

    def add_icon_menu_item(self, icon_menu, action_group, text, icon_size, connect=True):
        if connect:
            item = icon_menu.addAction(text, lambda: self.set_content_icon_size(icon_size))
        else:
            item = icon_menu.addAction(text)
        item.setCheckable(True)
        item.setChecked(icon_size == self.icon_size)
        action_group.addAction(item)
        return item

    def export_all_content(self):
        self.export_content(self.get_content_data())

    def export_selected_content(self):
        selected = self.content_list_view.selectedIndexes()
        self.export_content(self.content_model.get_items(selected))

    def export_content(self, content_list):
        wizard = ExportWizard(content_list, Content)
        wizard.exec()

    def delete_selected_content(self, delete_post, delete_file):
        content_list = self.content_model.get_items(self.content_list_view.selectedIndexes())
        for content in content_list:
            ModelManger.delete_content(content, session=self.session, delete_post=delete_post,
                                       delete_file=delete_file)
        self.content_model.remove_items(content_list)
        self.setup_posts()

    def comment_view_context_menu(self):
        menu = QMenu()
        delete_menu = menu.addMenu('Delete Selected')
        delete_menu.addAction('Comments Only',
                              lambda: self.delete_selected_comments(delete_posts=False, delete_files=False))
        delete_menu.addAction('Comments with Posts',
                              lambda: self.delete_selected_comments(delete_posts=True, delete_files=False))
        delete_menu.addAction('Comments with Files',
                              lambda: self.delete_selected_comments(delete_posts=False, delete_files=True))
        delete_menu.addAction('Comments with Posts and Files',
                              lambda: self.delete_selected_comments(delete_posts=True, delete_files=True))
        menu.addSeparator()
        menu.addAction('Select All', self.comment_tree_view.selectAll)
        menu.addSeparator()

        menu.exec(QCursor.pos())

    def export_all_comments(self):
        self.export_comments(self.get_comment_data())

    def export_selected_comments(self):
        selected = self.comment_tree_view.selectedIndexes()
        self.export_comments(self.comment_tree_model.get_items(selected))

    def export_comments(self, comment_list):
        wizard = ExportWizard(comment_list, Comment)
        wizard.exec()

    def delete_selected_comments(self, delete_posts, delete_files):
        comments = self.comment_tree_model.get_items(self.comment_tree_view.selectedIndexes())
        for comment in comments:
            ModelManger.delete_comment(comment, session=self.session, delete_post=delete_posts,
                                       delete_files=delete_files)
        self.comment_tree_model.remove_items(comments)
        self.setup_posts()

    def comment_header_context_menu(self):
        """
        Displays a context menu for the comment table header which allows the user to select which headers will be
        visible.
        """
        menu = QMenu()
        for value in self.comment_tree_model.headers:
            item = menu.addAction(value.replace('_', ' ').title())
            item.triggered.connect(lambda x, header=value: self.toggle_comment_tree_headers(header))
            item.setCheckable(True)
            item.setChecked(self.settings_manager.database_view_comment_tree_headers.get(value, True))
        menu.exec(QCursor.pos())

    def toggle_comment_tree_headers(self, header):
        """Toggles the visibility of the supplied comment table header."""
        index = self.comment_tree_model.headers.index(header)
        headers = dict(self.settings_manager.database_view_comment_tree_headers)
        visible = headers.get(header, True)
        headers[header] = not visible
        self.assign_setting('database_view_comment_tree_headers', headers)
        # sets the header visibility to the opposite of what it originally was
        self.comment_tree_view.header().setSectionHidden(index, visible)

    def toggle_download_session_view(self):
        self.download_session_widget.setVisible(self.show_download_sessions)
        if self.show_download_sessions:
            self.setup_download_sessions()
        else:
            self.current_download_session = []
            self.adjust_focus('DOWNLOAD_SESSION')
            if self.show_reddit_objects:
                self.setup_reddit_objects()
            elif self.show_posts:
                self.setup_posts()
            elif self.show_content:
                self.setup_content()
            elif self.show_comments:
                self.setup_comments()

    def toggle_reddit_object_view(self):
        self.reddit_object_widget.setVisible(self.show_reddit_objects)
        if self.show_reddit_objects:
            self.setup_reddit_objects()
        else:
            self.current_reddit_object = []
            self.adjust_focus('REDDIT_OBJECT')
            if self.show_posts:
                self.setup_posts()
            elif self.show_content:
                self.setup_content()
            elif self.show_comments:
                self.setup_comments()

    def toggle_post_view(self):
        self.post_widget.setVisible(self.show_posts)
        if self.show_posts:
            self.setup_posts()
        else:
            self.current_post = []
            self.adjust_focus('POST')
            if self.show_content:
                self.setup_content()
            elif self.show_comments:
                self.setup_comments()

    def toggle_content_view(self):
        self.content_widget.setVisible(self.show_content_checkbox.isChecked())
        if self.show_content:
            self.setup_content()
        else:
            self.current_content = []
            self.adjust_focus('CONTENT')
            if self.show_comments:
                self.setup_comments()

    def toggle_comment_view(self):
        self.comment_widget.setVisible(self.show_comments_checkbox.isChecked())
        if self.show_comments:
            self.setup_comments()
        else:
            self.current_comment = []
            self.adjust_focus('COMMENT')

    def adjust_focus(self, calling_model):
        """
        Adjusts the focus if a model widget is hidden while having the focus, since the focus cannot belong to a model
        that is not visible.

        Starts with the models in the order that they appear, then tries to adjust the focus to the models before the
        supplied calling model.  If none before it are visible, it moves to the models after the supplied.
        :param calling_model: The model that is being hidden and may need focus adjusted.
        """
        if self.focus_map[calling_model].isChecked():
            model_order = ['DOWNLOAD_SESSION', 'REDDIT_OBJECT', 'POST', 'CONTENT', 'COMMENT']
            index = model_order.index(calling_model)
            sub = model_order[:index][::-1]
            sub.extend(model_order[index + 1:])
            for model in sub:
                if self.check_visibility(model):
                    self.focus_map[model].toggle()
                    break

    def sort_targets(self, model_name):
        """
        Returns (data_method, model, view, current_attribute_name, set_first_index_method) for the supplied model name.
        """
        return {
            'DOWNLOAD_SESSION': (self.set_download_session_data, self.download_session_model,
                                 self.download_session_list_view, 'current_download_session',
                                 self.set_first_download_session_index),
            'REDDIT_OBJECT': (self.set_reddit_object_data, self.reddit_object_model, self.reddit_object_list_view,
                              'current_reddit_object', self.set_first_reddit_object_index),
            'POST': (self.set_post_data, self.post_model, self.post_table_view, 'current_post',
                     self.set_first_post_index),
            'CONTENT': (self.set_content_data, self.content_model, self.content_list_view, 'current_content',
                        self.set_first_content_index),
            'COMMENT': (self.set_comment_data, self.comment_tree_model, self.comment_tree_view, 'current_comment',
                        self.set_first_comment_index)
        }[model_name]

    @hold_setup
    def reload_sorted_data(self, model_name):
        """
        Reloads the first page of the supplied model with the current sort settings and re-selects the item that was
        selected before the reload.  Runs with the hold set so the model reset and the re-selection do not trigger
        loads or cascades.
        :return: True if there was a selection that is no longer in the loaded data (nothing could be re-selected).
        """
        set_data, model, view, current_attr, _ = self.sort_targets(model_name)
        set_data(override_hold=True)
        current = getattr(self, current_attr)
        if not current:
            return False
        if model.contains(current):
            view.setCurrentIndex(model.get_item_index(current))
            return False
        return True

    def apply_sort_change(self, model_name):
        """
        Applies a change to the sort field or sort direction of the supplied model.  If the previous selection is no
        longer in the reloaded page, the first item is selected with the hold released so the downstream views are
        refreshed for the new selection.
        """
        selection_lost = self.reload_sorted_data(model_name)
        if selection_lost:
            self.sort_targets(model_name)[4]()
        self.save_sort_settings(model_name)

    def change_download_session_sort(self, *_args):
        self.apply_sort_change('DOWNLOAD_SESSION')

    def change_reddit_object_sort(self, *_args):
        self.apply_sort_change('REDDIT_OBJECT')

    def change_post_sort(self, *_args):
        self.apply_sort_change('POST')

    def change_content_sort(self, *_args):
        self.apply_sort_change('CONTENT')

    def change_comment_sort(self, *_args):
        self.apply_sort_change('COMMENT')

    def set_content_icon_size(self, size=None):
        """Sets the content icon size to the supplied size which is supplied by the user."""
        if size is None:
            size = self.icon_size
        else:
            self.icon_size = size
        self.content_list_view.setIconSize(QSize(size, size))
        self.content_list_view.setGridSize(QSize(size + 2, size + 45))

    def set_custom_content_icon_size(self):
        """Prompts the user to enter a custom size for the icon display, then calls the method to set the size."""
        size, ok = QInputDialog.getInt(self, 'Custom Icon Size', 'Enter custom icon size:')
        if ok:
            self.set_content_icon_size(size)

    def open_selected_content(self):
        """Opens the selected content with the operating systems default application."""
        content = self.content_model.get_item(self.content_list_view.selectedIndexes()[0].row())
        system_util.open_in_system(content.get_full_file_path())

    def rename_download_session(self, dl_session):
        if dl_session is not None:
            new_name, ok = QInputDialog.getText(self, 'New Session Name', 'Enter new session name:')
            if ok:
                dl_session.name = new_name
                self.session.commit()
                self.download_session_model.refresh()

    def focus_on(self, model_name):
        """
        Checks that the supplied model view is visible.  If it is not, it is selected to become visible, then the
        appropriate setup method is called to reflect the focused model.
        :param model_name: The name of the model that is being focused in on.
        """
        if model_name == 'DOWNLOAD_SESSION':
            self.show_download_sessions_checkbox.setChecked(True)
            self.setup_download_sessions()
        elif model_name == 'REDDIT_OBJECT':
            self.show_reddit_objects_checkbox.setChecked(True)
            self.setup_reddit_objects()
        elif model_name == 'POST':
            self.show_posts_checkbox.setChecked(True)
            self.setup_posts()
        elif model_name == 'CONTENT':
            self.show_content_checkbox.setChecked(True)
            self.setup_content()
        else:
            self.show_comments_checkbox.setChecked(True)
            self.setup_comments()
        self.filter_widget.filter_input_widget.set_model_combo(model_name)

    def setup_download_sessions(self):
        self.set_download_session_data()
        self.set_first_download_session_index()

    def setup_reddit_objects(self):
        self.set_reddit_object_data()
        self.set_first_reddit_object_index()

    def setup_posts(self):
        self.set_post_data()
        self.set_first_post_index()

    def setup_content(self):
        self.set_content_data()
        self.set_first_content_index()

    def setup_comments(self):
        self.set_comment_data()
        self.set_first_comment_index()

    def cascade_setup(self):
        """
        Cascades the view setup down the line of models.  The order of these calls is important to ensure that each
        view is setup correctly based on the view before it.  The call list contains the names of models who's views
        have already been set up.  Not checking the call list will result in an infinite loop and a stack overflow
        error.
        """
        if not self.download_session_focus and not self.check_call_list('DOWNLOAD_SESSION'):
            self.setup_download_sessions()
        if not self.reddit_object_focus and not self.check_call_list('REDDIT_OBJECT'):
            self.setup_reddit_objects()
        if not self.post_focus and not self.check_call_list('POST'):
            self.setup_posts()
        if not self.content_focus and not self.check_call_list('CONTENT'):
            self.setup_content()
        if not self.comment_focus and not self.check_call_list('COMMENT'):
            self.setup_comments()

    def set_current_download_session(self):
        """
        Sets the current download session, then cascades the view setup down the line so that the rest of the views show
        the correct models based on this download session.
        """
        if self.show_download_sessions:
            try:
                self.current_download_session = \
                    self.download_session_model.get_items(self.download_session_list_view.selectedIndexes())
            except IndexError:
                self.current_download_session = []
            if self.cascade:
                self.setup_call_list.append('DOWNLOAD_SESSION')
                self.cascade_setup()
                self.setup_call_list.clear()

    def set_current_reddit_object(self):
        """See set current download session."""
        if self.show_reddit_objects:
            try:
                self.current_reddit_object = \
                    self.reddit_object_model.get_items(self.reddit_object_list_view.selectedIndexes())
            except IndexError:
                self.current_reddit_object = []
            if self.cascade:
                self.setup_call_list.append('REDDIT_OBJECT')
                if not self.reddit_object_focus:
                    self.setup_call_list.append('DOWNLOAD_SESSION')
                self.cascade_setup()
                self.setup_call_list.clear()

    def set_current_post(self):
        """See set current download session."""
        if self.show_posts:
            try:
                self.current_post = self.post_model.get_items(self.post_table_view.selectedIndexes())
                self.handle_post_text_browser()
            except IndexError:
                self.current_post = []
                self.post_text_browser.setVisible(False)
            if self.cascade:
                self.setup_call_list.append('POST')
                if not self.post_focus:
                    self.setup_call_list.extend(['DOWNLOAD_SESSION', 'REDDIT_OBJECT'])
                self.cascade_setup()
                self.setup_call_list.clear()

    def handle_post_text_browser(self):
        post_size = len(self.current_post)
        if post_size >= 1:
            if post_size > 1:
                parts = [f'<b>{post.title}</b>\n{post.text_html}' for post in self.current_post if
                         post.text_html is not None]
                if len(parts) > 0:
                    text = '\n\n'.join(parts)
                else:
                    text = None
            else:
                text = self.current_post[0].text_html
            if text is not None:
                self.post_text_browser.set_title(self.current_post[0].title)
                self.post_text_browser.setHtml(text)
                self.post_text_browser.setVisible(True)
            else:
                self.setWindowTitle('Post Text Browser')
                self.post_text_browser.clear()
                self.post_text_browser.setVisible(False)
        else:
            if not self.post_text_browser.stand_alone and self.post_text_browser.isVisible():
                self.post_text_browser.setVisible(False)
            self.post_text_browser.clear()

    def set_current_content(self):
        """See set current download session."""
        if self.show_content:
            try:
                self.current_content = self.content_model.get_items(self.content_list_view.selectedIndexes())
            except IndexError:
                self.current_content = []
            if self.cascade:
                self.setup_call_list.append('CONTENT')
                if not self.content_focus:
                    self.setup_call_list.extend(['DOWNLOAD_SESSION', 'REDDIT_OBJECT', 'POST'])
                self.cascade_setup()
                self.setup_call_list.clear()

    def set_current_comment(self):
        """See set current download session."""
        if self.show_comments:
            try:
                self.current_comment = self.comment_tree_model.get_items(self.comment_tree_view.selectedIndexes())
                self.handle_comment_text_browser()
            except (IndexError, AttributeError):
                self.current_comment = []
                self.comment_text_browser.setVisible(False)
                self.comment_text_browser.clear()
            if self.cascade:
                self.setup_call_list.append('COMMENT')
                if not self.comment_focus:
                    self.setup_call_list.extend(['DOWNLOAD_SESSION', 'REDDIT_OBJECT', 'POST', 'COMMENT'])
                self.cascade_setup()
                self.setup_call_list.clear()

    def handle_comment_text_browser(self):
        comment_size = len(self.current_comment)
        if comment_size >= 1:
            if comment_size > 1:
                parts = [f'<b>{comment.author}<b>\n{comment.body_html}' for comment in self.current_comment if
                         comment.body_html is not None]
                if len(parts) > 0:
                    text = '\n\n'.join(parts)
                else:
                    text = None
            else:
                text = self.current_comment[0].body_html
            if text is not None:
                self.comment_text_browser.set_title(f'{self.current_comment[0].author} - comment')
                self.comment_text_browser.setHtml(text)
                self.comment_text_browser.setVisible(True)
            else:
                if not self.comment_text_browser.stand_alone and self.comment_text_browser.isVisible():
                    self.comment_text_browser.setVisible(False)
                self.comment_text_browser.clear()

    @check_hold
    def set_download_session_data(self, extend=False):
        """
        Sets the data displayed in the download session view based on the focus settings, visible models, and filters
        that are used in the database dialog.
        :param extend: False if this is the first page of data, false if it is another page.  This indicates whether
                       the shown data should be extended (if True) or overwritten (if False).
        """
        f = DownloadSessionFilter()
        filter_tups = self.filter_widget.filter('DOWNLOAD_SESSION')
        query = self.session.query(DownloadSession)
        if self.reddit_object_focus:
            if self.current_reddit_object_significant:
                dl_ids = self.session.query(Post.download_session_id)\
                    .filter(Post.significant_reddit_object_id.in_(self.current_reddit_object_id))
            else:
                current_reddit_object_type = self.current_reddit_object_type
                if current_reddit_object_type == USER_OBJECT:
                    dl_ids = self.session.query(Post.download_session_id)\
                        .filter(Post.author_id.in_(self.current_user_id))
                elif current_reddit_object_type == SUBREDDIT_OBJECT:
                    dl_ids = self.session.query(Post.download_session_id)\
                        .filter(Post.subreddit_id.in_(self.current_subreddit_id))
                else:
                    dl_ids = self.session.query(Post.download_session_id)\
                        .filter(or_(Post.author_id.in_(self.current_user_id),
                                    Post.subreddit_id.in_(self.current_subreddit_id)))
            query = query.filter(DownloadSession.id.in_(dl_ids))
        elif self.post_focus:
            query = query.filter(DownloadSession.id.in_(self.current_post_attr('download_session_id')))
        elif self.content_focus:
            query = query.filter(DownloadSession.id.in_(self.current_content_attr('download_session_id')))
        elif self.comment_focus:
            query = query.filter(DownloadSession.id.in_(self.current_comment_attr('download_session_id')))
        final_query = f.filter(self.session, *filter_tups, query=query, order_by=self.download_session_order,
                               desc=self.download_session_desc)
        if not extend:
            self.download_session_model.set_data(final_query)
        else:
            self.download_session_model.load_next_page(final_query)
        self.check_load_more_button(self.download_session_model)

    def get_reddit_object_data(self):
        f = RedditObjectFilter()
        filter_tups = self.filter_widget.filter('REDDIT_OBJECT')
        query = self.session.query(RedditObject)
        if self.download_session_focus:
            subquery = self.session.query(Post.significant_reddit_object_id).join(Content) \
                .filter(Content.download_session_id.in_(self.current_download_session_id)) \
                .union(
                self.session.query(Post.significant_reddit_object_id)
                    .filter(Post.download_session_id.in_(self.current_download_session_id))
            )
            query = query.filter(RedditObject.id.in_(subquery))
        elif self.post_focus:
            query = query.filter(RedditObject.id.in_(self.current_post_attr('significant_reddit_object_id')))
        elif self.content_focus:
            query = query.filter(RedditObject.id.in_(
                self.get_significant_reddit_object_ids_from_post_in_list(self.current_content)
            ))
        elif self.comment_focus:
            query = query.filter(RedditObject.id.in_(
                self.get_significant_reddit_object_ids_from_post_in_list(self.current_comment)
            ))
        final_query = f.filter(self.session, *filter_tups, query=query, order_by=self.reddit_object_order,
                               desc=self.reddit_object_desc)
        return final_query

    def get_significant_reddit_object_ids_from_post_in_list(self, item_list):
        """
        Helper method to return a list of significant reddit object ids associated with the posts of a list of items.
        :param item_list: A list of items from which significant reddit object ids are to be taken.  A list of content
            or comments.
        :return: A list of significant reddit object ids from posts associated with each item in the supplied item list.
        """
        id_list = []
        for item in item_list:
            try:
                id_list.append(item.post.significant_reddit_object_id)
            except AttributeError:
                pass
        return id_list

    @check_hold
    def set_reddit_object_data(self, extend=False):
        """See set download session data."""
        final_query = self.get_reddit_object_data()
        if not extend:
            self.reddit_object_model.set_data(final_query)
        else:
            self.reddit_object_model.load_next_page(final_query)
        self.check_load_more_button(self.reddit_object_model)

    @check_hold
    def set_post_data(self, extend=False):
        """See set download session data."""
        final_query = self.get_post_data()
        if not extend:
            self.post_model.set_data(final_query)
        else:
            self.post_model.load_next_page(final_query)
        self.check_load_more_button(self.post_model)

    def get_post_data(self):
        f = PostFilter()
        filter_tups = self.filter_widget.filter('POST')
        query = self.session.query(Post)
        if self.download_session_focus or self.reddit_object_focus:
            if self.show_download_sessions:
                query = query.filter(Post.download_session_id.in_(self.current_download_session_id))
            if self.show_reddit_objects:
                if self.current_reddit_object_significant:
                    query = query.filter(Post.significant_reddit_object_id.in_(self.current_reddit_object_id))
                else:
                    current_type = self.current_reddit_object_type
                    if current_type == USER_OBJECT:
                        query = query.filter(Post.author_id.in_(self.current_user_id))
                    elif current_type == SUBREDDIT_OBJECT:
                        query = query.filter(Post.subreddit_id.in_(self.current_subreddit_id))
                    else:
                        query = query.filter(or_(Post.author_id.in_(self.current_user_id),
                                                 Post.subreddit_id.in_(self.current_subreddit_id)))
        elif self.content_focus:
            query = query.filter(Post.id.in_(self.current_content_attr('post_id')))
        elif self.comment_focus:
            query = query.filter(Post.id.in_(self.current_comment_attr('post_id')))
        final_query = f.filter(self.session, *filter_tups, query=query, order_by=self.post_order,
                               desc=self.post_desc)
        return final_query

    def get_content_data(self):
        f = ContentFilter()
        filter_tups = self.filter_widget.filter('CONTENT')
        query = self.session.query(Content)
        if self.download_session_focus:
            query = query.filter(Content.download_session_id.in_(self.current_download_session_id))
            if self.show_posts:
                query = query.filter(Content.post_id.in_(self.current_post_id))
            elif self.show_reddit_objects:
                if self.current_reddit_object_significant:
                    posts = self.session.query(Post.id) \
                        .filter(Post.significant_reddit_object_id.in_(self.current_reddit_object_id))
                    query = query.filter(Content.post_id.in_(posts))
                else:
                    current_type = self.current_reddit_object_type
                    if current_type == USER_OBJECT:
                        query = query.filter(Content.user_id.in_(self.current_user_id))
                    elif current_type == SUBREDDIT_OBJECT:
                        query = query.filter(Content.subreddit_id.in_(self.current_subreddit_id))
                    else:
                        query = query.filter(or_(Content.user_id.in_(self.current_user_id),
                                                 Content.subreddit_id.in_(self.current_subreddit_id)))
        elif self.reddit_object_focus:
            if self.current_reddit_object_significant:
                posts = self.session.query(Post.id) \
                    .filter(Post.significant_reddit_object_id.in_(self.current_reddit_object_id))
                query = query.filter(Content.post_id.in_(posts))
            else:
                current_type = self.current_reddit_object_type
                if current_type == USER_OBJECT:
                    query = query.filter(Content.user_id.in_(self.current_user_id))
                elif current_type == SUBREDDIT_OBJECT:
                    query = query.filter(Content.subreddit_id.in_(self.current_subreddit_id))
                else:
                    query = query.filter(or_(Content.user_id.in_(self.current_user_id),
                                             Content.subreddit_id.in_(self.current_subreddit_id)))
            if self.show_posts:
                query = query.filter(Content.post_id.in_(self.current_post_id))
            elif self.show_download_sessions:
                query = query.filter(Content.download_session_id.in_(self.current_download_session_id))
        elif self.post_focus:
            query = query.filter(Content.post_id.in_(self.current_post_id))
        elif self.comment_focus:
            query = query.filter(Content.comment_id.in_(self.current_comment_id))
        final_query = f.filter(self.session, *filter_tups, query=query, order_by=self.content_order,
                               desc=self.content_desc)
        return final_query

    @check_hold
    def set_content_data(self, extend=False):
        """See set download session data."""
        final_query = self.get_content_data()
        if not extend:
            self.content_model.set_data(final_query)
        else:
            self.content_model.load_next_page(final_query)
        self.check_load_more_button(self.content_model)

    def get_comment_data(self):
        f = CommentFilter()
        filter_tups = self.filter_widget.filter('COMMENT')
        query = self.session.query(Comment)
        if self.download_session_focus or self.reddit_object_focus:
            if self.show_posts:
                query = query.filter(Comment.post_id.in_(self.current_post_id))
            elif self.show_reddit_objects:
                posts = self.session.query(Post.id) \
                    .filter(Post.significant_reddit_object_id.in_(self.current_reddit_object_id))
                query = query.filter(Comment.post_id.in_(posts))
            else:
                query = query.filter(Comment.download_session_id.in_(self.current_download_session_id))
        elif self.post_focus:
            query = query.filter(Comment.post_id.in_(self.current_post_id))
        elif self.content_focus:
            query = query.filter(Comment.post_id.in_(self.current_content_attr('comment_id')))
        final_query = f.filter(self.session, *filter_tups, query=query, order_by=self.comment_order,
                               desc=self.comment_desc)
        return final_query

    @check_hold
    def set_comment_data(self, extend=False):
        """See set download session data."""
        final_query = self.get_comment_data()
        if not extend:
            self.comment_tree_model.set_data(final_query)
        else:
            self.comment_tree_model.load_next_page(final_query)
        self.check_load_more_button(self.comment_tree_model)

    def set_first_download_session_index(self):
        """
        Sets the index of the download session view once it has been reloaded.  This will be the first view if the
        download session that was selected before the data was changed is no long in the viewable data.  If the previous
        download session is still in the viewable data, it will be re-selected.
        """
        if not self.download_session_model.contains(self.current_download_session):
            first_index = self.download_session_model.createIndex(0, 0)
            if self.download_session_list_view.currentIndex() != first_index:
                self.download_session_list_view.setCurrentIndex(first_index)
            else:
                self.set_current_download_session()
        else:
            current_index = self.download_session_model.get_item_index(self.current_download_session)
            if self.download_session_list_view.currentIndex() != current_index:
                self.download_session_list_view.setCurrentIndex(current_index)

    def set_first_reddit_object_index(self):
        """See set_first_download_session_index."""
        if not self.reddit_object_model.contains(self.current_reddit_object):
            first_index = self.reddit_object_model.createIndex(0, 0)
            if self.reddit_object_list_view.currentIndex() != first_index:
                self.reddit_object_list_view.setCurrentIndex(first_index)
            else:
                self.set_current_reddit_object()
        else:
            current_index = self.reddit_object_model.get_item_index(self.current_reddit_object)
            if self.reddit_object_list_view.currentIndex() != current_index:
                self.reddit_object_list_view.setCurrentIndex(current_index)

    def set_first_post_index(self):
        """See set_first_download_session_index."""
        if not self.post_model.contains(self.current_post):
            first_index = self.post_model.createIndex(0, 0)
            if self.post_table_view.currentIndex() != first_index:
                self.post_table_view.setCurrentIndex(first_index)
            else:
                self.set_current_post()
        else:
            current_index = self.post_model.get_item_index(self.current_post)
            if self.post_table_view.currentIndex() != current_index:
                self.post_table_view.setCurrentIndex(current_index)

    def set_first_content_index(self):
        """See set_first_download_session_index."""
        if not self.content_model.contains(self.current_content):
            first_index = self.content_model.createIndex(0, 0)
            if self.content_list_view.currentIndex() != first_index:
                self.content_list_view.setCurrentIndex(first_index)
            else:
                self.set_current_content()
        else:
            current_index = self.content_model.get_item_index(self.current_content)
            if self.content_list_view.currentIndex() != current_index:
                self.content_list_view.setCurrentIndex(current_index)

    def set_first_comment_index(self):
        """See set_first_download_session_index."""
        if not self.comment_tree_model.contains(self.current_comment):
            first_index = self.comment_tree_model.get_first_index()
            if self.comment_tree_view.currentIndex() != first_index:
                self.comment_tree_view.setCurrentIndex(first_index)
            else:
                self.set_current_comment()
        else:
            current_index = self.comment_tree_model.get_item_index(self.current_comment)
            if self.comment_tree_view.currentIndex() != current_index:
                self.comment_tree_view.setCurrentIndex(current_index)

    def set_current_item(self, item_id):
        if self.current_focus_model is not None:
            index = self.current_focus_model.get_item_index_by_id(item_id)
            self.current_focus_view.setCurrentIndex(index)

    def monitor_scrollbar(self, bar_scroll, model, load_method, load_percentage=90):
        """
        Monitors the supplied scrollbar for when it reaches the load_percentage position.  This is used to determine
        when the infinite scroll should load the next page if it is enabled.  The load_percentage is adjustable and
        should be determined based on the loading performance of the model that the view deals with.
        :param bar: The scrollbar that is monitored.
        :param model: The model who's view the scrollbar belongs to.
        :param load_method: The method that should be called in order to load the next page.
        :param load_percentage: The percentage at which the scrollbar will call the load method.
        """
        try:
            if self.infinite_scroll_map[model]:
                value = bar_scroll.value()
                p = (value / bar_scroll.maximum()) * 100
                if p >= load_percentage and model.has_next_page and not model.loading:
                    load_method(extend=True)
        except ZeroDivisionError:
            pass

    def load_next_page(self, model, load_method):
        load_method(extend=True)
        self.check_load_more_button(model)

    def check_load_more_button(self, model):
        """
        Checks the supplied view model, and sets the 'load more' button visibility based on if there is another page
        available.
        """
        self.model_button_link_map[model].setVisible(model.has_next_page)

    def update_count_label(self, count_pair, model):
        visible, total = count_pair
        if model == 'DOWNLOAD_SESSION':
            visible_label = self.download_session_visible_count_label
            count_label = self.download_session_count_label
        elif model == 'REDDIT_OBJECT':
            visible_label = self.reddit_object_visible_count_label
            count_label = self.reddit_object_count_label
        elif model == 'POST':
            visible_label = self.post_visible_count_label
            count_label = self.post_count_label
        elif model == 'CONTENT':
            visible_label = self.content_visible_count_label
            count_label = self.content_count_label
        else:
            visible_label = self.comment_visible_count_label
            count_label = self.comment_count_label
        visible_label.setText(str(visible))
        count_label.setText(str(total))

    @staticmethod
    def select_combo_data(combo, *candidates):
        """
        Selects the first candidate value that exists in the combo's item data.  If none exist the first entry is
        selected so the combo is never left blank (a blank combo reports None as its sort field).
        """
        for candidate in candidates:
            if candidate is None:
                continue
            index = combo.findData(candidate)
            if index >= 0:
                combo.setCurrentIndex(index)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    @staticmethod
    def apply_header_visibility(header, model_headers, visibility):
        """
        Hides or shows header sections from a {header_name: visible} dict.  Names that are no longer headers of the
        model are ignored, and headers missing from the dict are left visible.
        """
        for key, visible in visibility.items():
            if key in model_headers:
                header.setSectionHidden(model_headers.index(key), not visible)

    def restore_header_state(self, header, setting_name):
        """Restores a header's saved state (column order, widths).  The state is stored as a hex string."""
        state = getattr(self.settings_manager, setting_name, None)
        if not state:
            return
        try:
            header.restoreState(QByteArray.fromHex(state.encode()))
        except (AttributeError, TypeError, ValueError):
            self.logger.warning(f'Unable to restore header state for {setting_name}', exc_info=True)

    def save_header_state(self, header, setting_name):
        setattr(self.settings_manager, setting_name, header.saveState().toHex().data().decode())

    @staticmethod
    def position_is_on_screen(x, y):
        """True if the supplied window position is on one of the currently connected screens."""
        return QApplication.screenAt(QPoint(x + 20, y + 20)) is not None

    def assign_setting(self, name, value):
        """
        Assigns a dict setting through the settings manager rather than editing the dict that the manager returns in
        place.  If the manager hands back a copy, in place edits are silently lost.
        """
        try:
            setattr(self.settings_manager, name, value)
        except AttributeError:
            getattr(self.settings_manager, name).update(value)

    def flush_settings(self):
        """
        Asks the settings manager to write its settings to disk so the window settings survive even if the application
        is not closed cleanly.  Does nothing if the manager has no such method.
        """
        for method_name in ('save_all', 'save_settings'):
            save = getattr(self.settings_manager, method_name, None)
            if callable(save):
                try:
                    save()
                except Exception: # pylint: disable=broad-except
                    self.logger.warning('Unable to write the settings to disk', exc_info=True)
                return

    def save_geometry_settings(self):
        """Saves the window size and position.  A minimized or maximized window saves its normal geometry."""
        if self.isMinimized() or self.isMaximized():
            rect = self.normalGeometry()
            x, y, width, height = rect.x(), rect.y(), rect.width(), rect.height()
        else:
            x, y, width, height = self.x(), self.y(), self.width(), self.height()
        geom = dict(self.settings_manager.database_view_geom)
        geom.update({'width': width, 'height': height, 'x': x, 'y': y})
        self.assign_setting('database_view_geom', geom)

    def pane_width_settings(self):
        """Returns (pane widget, settings name) pairs for the width of each pane in the split view."""
        return (
            (self.download_session_widget, 'database_view_download_session_widget_width'),
            (self.reddit_object_widget, 'database_view_reddit_object_widget_width'),
            (self.post_widget, 'database_view_post_widget_width'),
            (self.content_widget, 'database_view_content_widget_width'),
            (self.comment_widget, 'database_view_comment_widget_width')
        )

    def find_pane_splitter(self):
        """Returns the QSplitter that holds the panes, or None if the panes are not in a splitter."""
        widget = self.download_session_widget.parentWidget()
        while widget is not None and not isinstance(widget, QSplitter):
            widget = widget.parentWidget()
        return widget

    @staticmethod
    def splitter_child(splitter, widget):
        """Returns the direct child of the splitter that is, or contains, the supplied widget."""
        while widget is not None and widget.parentWidget() is not splitter:
            widget = widget.parentWidget()
        return widget

    def restore_pane_widths(self):
        """
        Applies the saved pane widths to the splitter.  A splitter overrides the size of its children when it is first
        shown, so resizing the panes themselves does not stick; the sizes have to be given to the splitter.
        """
        splitter = self.find_pane_splitter()
        if splitter is None:
            return
        saved = {}
        for pane, setting_name in self.pane_width_settings():
            child = self.splitter_child(splitter, pane)
            width = getattr(self.settings_manager, setting_name, None)
            if child is not None and width and width > 0:
                saved[child] = width
        if not saved:
            return
        sizes = []
        for index in range(splitter.count()):
            child = splitter.widget(index)
            sizes.append(saved.get(child) or max(child.sizeHint().width(), 1))
        splitter.setSizes(sizes)

    def save_pane_widths(self):
        """Saves the width of each visible pane.  Hidden panes keep their previously saved width."""
        for pane, setting_name in self.pane_width_settings():
            if pane.isVisibleTo(self) and pane.width() > 0:
                setattr(self.settings_manager, setting_name, pane.width())

    def save_sort_settings(self, model_name):
        """
        Saves the sort field and sort direction of the supplied model together so they can never be out of step.  Does
        nothing unless the dialog was set up to save its settings (specialty dialogs must not overwrite them).
        """
        if not self.save_settings:
            return
        name = model_name.lower()
        order = getattr(self, f'{name}_order')
        if order is not None:
            setattr(self.settings_manager, f'database_view_{name}_order', order)
        setattr(self.settings_manager, f'database_view_{name}_desc_order', getattr(self, f'{name}_desc'))

    def save_header_states(self):
        """
        Saves the column order/widths of the post table and comment tree.  A state is only saved if the settings manager
        defines the attribute for it, so nothing new is written to the settings unless it was added there.  Failures
        are logged and never interfere with saving the rest of the window settings.
        """
        headers = (
            (self.post_table_view.horizontalHeader(), 'database_view_post_table_header_state'),
            (self.comment_tree_view.header(), 'database_view_comment_tree_header_state')
        )
        for header, setting_name in headers:
            if not hasattr(self.settings_manager, setting_name):
                continue
            try:
                self.save_header_state(header, setting_name)
            except Exception: # pylint: disable=broad-except
                self.logger.warning(f'Unable to save header state for {setting_name}', exc_info=True)

    def closeEvent(self, event): # pylint: disable=invalid-name
        """
        Overrides the default close event in order to save the window settings.  The settings will only be saved if the
        classes 'save_settings' flag is set.  When this dialog is setup to display specialty information (such as failed
        downloads) the settings should not be saved so that the database view dialog displays correctly the next time
        the user opens the dialog.
        """
        self.save_geometry_settings()
        self.settings_manager.database_view_icon_size = self.icon_size
        if self.save_settings:
            self.save_pane_widths()

            for key, value in self.focus_map.items():
                if value.isChecked():
                    self.settings_manager.database_view_focus_model = key
                    break
            self.settings_manager.database_view_show_download_sessions = self.show_download_sessions
            self.settings_manager.database_view_show_reddit_objects = self.show_reddit_objects
            self.settings_manager.database_view_show_posts = self.show_posts
            self.settings_manager.database_view_show_content = self.show_content
            self.settings_manager.database_view_show_comments = self.show_comments
            for model_name in ('DOWNLOAD_SESSION', 'REDDIT_OBJECT', 'POST', 'CONTENT', 'COMMENT'):
                self.save_sort_settings(model_name)
            self.save_header_states()
        self.flush_settings()
        super().closeEvent(event)
