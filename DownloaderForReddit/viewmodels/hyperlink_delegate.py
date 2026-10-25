import webbrowser
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle
from PyQt6.QtGui import QTextDocument, QTextCursor, QTextCharFormat
from PyQt6.QtCore import QEvent, Qt, QModelIndex, QPointF

class HyperlinkDelegate(QStyledItemDelegate):
    """
    Provides a delegate for rendering hyperlinks in item views.

    This class inherits from QStyledItemDelegate and is used to display and interact with
    content containing hyperlinks within item views. It renders HTML content and handles
    mouse events to support hyperlink navigation while preserving the item's intended
    color.
    """
    def paint(self, painter, option, index):
        """
        Overrides the paint method to render hyperlinks and colored text in the item view.

        :param painter: QPainter object used for rendering the text.
        :param option: QStyleOptionViewItem containing options for rendering the item.
        :param index: QModelIndex providing access to model data.
        :return: None
        """
        # Handle selection state properly by using Qt's built-in painting for selected items
        # This ensures that selection highlighting works correctly while maintaining hyperlink functionality
        if option.state & QStyle.StateFlag.State_Selected:
            # Use the default selection background for selected items
            painter.fillRect(option.rect, option.palette.highlight())

            # For selected items, we need to preserve the original text colors from document
            # but ensure proper visibility - we'll use the highlight text color for better contrast
            text_color = option.palette.highlightedText().color()
        else:
            # Use normal background
            painter.fillRect(option.rect, option.palette.base())
            text_color = option.palette.text().color()

        doc = self.get_document(option, index)

        # Adjust painter for text positioning
        painter.save()
        painter.translate(option.rect.topLeft())

        # Apply the appropriate text color - but we need to be more careful about preserving
        # original colors from model data that were already applied in get_document()
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        fmt.setForeground(text_color)
        cursor.mergeCharFormat(fmt)

        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index): # pylint: disable=invalid-name
        """
        Overrides the sizeHint method to return the size of the document element after
        the formatting is applied to render the HTML correctly.

        :param option: Contains style option controls for rendering items
        :param index: Refers to the model index of the item
        :return: Calculated size of the item as a QSize object
        """
        doc = self.get_document(option, index)
        return doc.size().toSize()

    def get_document(self, option: QStyleOptionViewItem, index: QModelIndex) -> QTextDocument:
        """
        Generates a QTextDocument object with formatted HTML content and foreground
        color based on provided index data.

        :param option: The style option which provides information such as the rectangle
                       dimensions to adjust the document's text width.
        :param index: The model index containing data for the document, such as HTML content
                      and optional foreground color.
        :return: A QTextDocument object set with the formatted HTML content and modified
                 foreground color (if applicable).
        """
        doc = QTextDocument()
        html = index.data(Qt.ItemDataRole.DisplayRole)
        doc.setHtml(html)
        color = index.data(Qt.ItemDataRole.ForegroundRole)

        if color:
            cursor = QTextCursor(doc)
            cursor.select(QTextCursor.SelectionType.Document)
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor.mergeCharFormat(fmt)

        doc.setTextWidth(option.rect.width())
        return doc

    def editorEvent(self, event, model, option, index):  # pylint: disable=invalid-name,unused-argument
        """
        Overrides the editorEvent method to handle mouse events for hyperlink navigation.
        """
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            doc = QTextDocument()
            html = index.data(Qt.ItemDataRole.DisplayRole)
            doc.setHtml(html)
            pos = event.pos() - option.rect.topLeft()
            anchor = doc.documentLayout().anchorAt(QPointF(pos))
            if anchor:
                webbrowser.open(anchor)
                return True
        return False
