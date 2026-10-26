from PyQt6.QtCore import QModelIndex
from PyQt6.QtGui import QTextDocument, QPalette
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle

class HyperlinkDelegate(QStyledItemDelegate):
    """
    Provides a delegate for rendering hyperlinks in item views.

    This class inherits from QStyledItemDelegate and is used to display and interact with
    content containing hyperlinks within item views. It renders HTML content and handles
    mouse events to support hyperlink navigation while preserving the item's intended
    color, while fully supporting item selection states.
    """
    def paint(self, painter, option, index):
        """
        Overrides the paint method to render selection highlights, hyperlinks, and colored text.

        :param painter: QPainter object used for rendering.
        :param option: QStyleOptionViewItem containing options for rendering the item.
        :param index: QModelIndex providing access to model data.
        :return: None
        """
        # 1. Initialize option structure and draw standard selection/hover backgrounds
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)

        painter.save()

        # Draw the standard background widget (handles selection, focus, alternate rows)
        style = style_option.widget.style() if style_option.widget else QStyle.alignedRect()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, style_option, painter, style_option.widget)

        # 2. Get the document with the correct context-aware text color
        doc = self.get_document(style_option, index)

        # 3. Render the text content inside the designated rect boundary
        painter.translate(style_option.rect.topLeft())
        doc.drawContents(painter)

        painter.restore()

    def sizeHint(self, option, index):
        """
        Overrides the sizeHint method to return the size of the document element after
        the formatting is applied to render the HTML correctly.

        :param option: Contains style option controls for rendering items
        :param index: Refers to the model index of the item
        :return: Calculated size of the item as a QSize object
        """
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)

        doc = self.get_document(style_option, index)
        return doc.size().toSize()

    def get_document(self, option: QStyleOptionViewItem, index: QModelIndex) -> QTextDocument:
        """
        Generates a QTextDocument object with formatted HTML content and foreground
        color based on provided index data and selection state.

        :param option: The style option which provides selection state and bounding rectangles.
        :param index: The model index containing data for the document.
        :return: A configured QTextDocument instance.
        """
        doc = QTextDocument()

        # Constrain document layout to the cell width boundaries
        doc.setTextWidth(option.rect.width())

        # Extract base HTML content from the model
        html_content = index.data() or ""
        doc.setHtml(html_content)

        # Determine appropriate text color: standard palette vs selection palette
        if option.state & QStyle.StateFlag.State_Selected:
            text_color = option.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText)
        else:
            # Fallback to model's explicit ForegroundRole color if specified, else default text color
            foreground = index.data(QPalette.ColorRole.Foreground)
            if foreground:
                text_color = foreground.color()
            else:
                text_color = option.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Text)

        # Apply default text color to document configuration
        doc.setDefaultTextColor(text_color)

        return doc
