import logging

from PyQt6.QtWidgets import QWidget, QLineEdit, QSpinBox, QComboBox, QDateTimeEdit, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal
from sqlalchemy import Integer, String, DateTime, Enum, Boolean

from DownloaderForReddit.guiresources.database_views.filter_input_widget_auto import Ui_FilterInputWidget
from DownloaderForReddit.database.filters import (DownloadSessionFilter, RedditObjectFilter, PostFilter, ContentFilter,
                                                  CommentFilter)
from DownloaderForReddit.utils import injector
from .filter_item import FilterItem


class FilterInputWidget(QWidget, Ui_FilterInputWidget):

    export_filter = pyqtSignal(list)

    def __init__(self, parent=None):
        QWidget.__init__(self, parent=parent)
        self.setupUi(self)
        self.settings_manager = injector.get_settings_manager()
        self.logger = logging.getLogger(f'DownloaderForReddit.{__name__}')
        self.launch_quick_filter = True
        self.filter_model_map = {
            'DOWNLOAD_SESSION': DownloadSessionFilter,
            'REDDIT_OBJECT': RedditObjectFilter,
            'POST': PostFilter,
            'CONTENT': ContentFilter,
            'COMMENT': CommentFilter
        }

        self.field_type_map = {
            Boolean: self.get_boolean_field,
            Integer: self.get_integer_field,
            String: self.get_string_field,
            DateTime: self.get_datetime_field
        }

        self.value_field = None
        self.value_field_type = None

        self.add_filter_button.clicked.connect(self.add_filter)
        self.model_combo.currentIndexChanged.connect(self.set_fields)

        self.model_list = ['DOWNLOAD_SESSION', 'REDDIT_OBJECT', 'POST', 'CONTENT', 'COMMENT']
        for model in self.model_list:
            self.model_combo.addItem(model.replace('_', ' ').title(), model)

        operators = [('Equal To', 'eq'), ('Not Equal', 'not'), ('<', 'lt'), ('<=', 'lte'), ('>', 'gt'), ('>=', 'gte'),
                     ('In', 'in'), ('Like', 'like'), ('Contains', 'contains')]
        for x in operators:
            self.operator_combo.addItem(x[0], x[1])

        self.set_fields()
        self.field_combo.currentIndexChanged.connect(self.set_value_field)
        self.set_value_field()

        self.quick_filter_combo.addItem('Quick Filters')
        self.quick_filter_combo.addItems(self.settings_manager.database_view_quick_filters.keys())
        self.quick_filter_combo.currentIndexChanged.connect(self.handle_quick_filter)

    @property
    def current_model(self):
        return self.model_combo.currentData(Qt.ItemDataRole.UserRole)

    @property
    def current_field(self):
        return self.field_combo.currentData(Qt.ItemDataRole.UserRole)

    @property
    def current_operator(self):
        return self.operator_combo.currentData(Qt.ItemDataRole.UserRole)

    def set_model_combo(self, model):
        try:
            self.model_combo.setCurrentIndex(self.model_list.index(model))
        except (ValueError,IndexError):
            pass

    def set_fields(self):
        self.field_combo.clear()
        f = self.filter_model_map[self.current_model]
        for field in f.get_filter_fields():
            self.field_combo.addItem(field.replace('_', ' ').title(), field)

    def set_value_field(self):
        """Replaces the value input so that it matches the type of the selected field."""
        current_field = self.current_field
        if current_field is None:
            return
        f = self.filter_model_map[self.current_model]()
        field_type = f.get_type(current_field)

        # Enum fields always get a new input because their choices depend on the field.  Other types keep the existing
        # input (and whatever the user typed into it) as long as the field type is the same.
        if field_type != Enum and field_type == self.value_field_type and self.value_field is not None:
            return

        if field_type == Enum:
            widget = self.get_choice_field(choices=f.get_choices(current_field))
        else:
            factory = self.field_type_map.get(field_type)
            if factory is None:
                self.logger.warning("No value input for field type '%s', using a text box", field_type)
                factory = self.get_string_field
            widget = factory()

        self.replace_value_field(widget)
        self.value_field_type = field_type

    def replace_value_field(self, widget):
        old = self.value_field
        if old is not None:
            self.value_layout.removeWidget(old)
            old.setParent(None)  # hides it right away; deleteLater alone leaves it visible until the event loop runs
            old.deleteLater()
        self.value_field = widget
        self.value_layout.addWidget(widget)

    def get_value(self):
        field = self.value_field
        if isinstance(field, QComboBox):
            return field.currentData(Qt.ItemDataRole.UserRole)
        if isinstance(field, QLineEdit):
            return field.text()
        if isinstance(field, QSpinBox):
            return field.value()
        if isinstance(field, QDateTimeEdit):
            return field.dateTime().toUTC().toString(Qt.DateFormat.ISODate)
        raise AttributeError(f'Unhandled value field type: {type(field).__name__}')

    def handle_quick_filter(self):
        if self.launch_quick_filter and self.quick_filter_combo.currentIndex() != 0:
            self.launch_quick_filter = False
            try:
                filters = [FilterItem(**filter_dict) for filter_dict in self.settings_manager.database_view_quick_filters[self.quick_filter_combo.currentText()]]
                self.add_filter(filters)
                self.quick_filter_combo.setCurrentIndex(0)
            finally:                
                self.launch_quick_filter = True

    def add_filter(self, filters=None):
        if not isinstance(filters, list):
            filters = [self.create_filter()]
        self.export_filter.emit(filters)

    def create_filter(self):
        return FilterItem(self.current_model, self.current_field, self.current_operator, self.get_value())

    def get_boolean_field(self):
        combo = QComboBox()
        combo.addItem('True', True)
        combo.addItem('False', False)
        return combo

    def get_integer_field(self):
        spin_box = QSpinBox()
        spin_box.setMaximum(1000000000)
        return spin_box

    def get_string_field(self):
        x = QLineEdit()
        x.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return x

    def get_choice_field(self, choices):
        combo = QComboBox()
        for x in choices:
            combo.addItem(x)
        return combo

    def get_datetime_field(self):
        return QDateTimeEdit()

    def keyPressEvent(self, event): # pylint: disable=invalid-name
        if event.key() == Qt.Key.Key_Enter or event.key() == Qt.Key.Key_Return:
            self.add_filter()
