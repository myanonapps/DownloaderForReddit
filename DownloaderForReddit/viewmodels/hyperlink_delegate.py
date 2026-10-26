import webbrowser
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle
from PyQt6.QtGui import QTextDocument, QTextCursor, QTextCharFormat, QPalette
from PyQt6.QtCore import QEvent, Qt, QModelIndex, QPointF


class HyperlinkDelegate(QStyledItemDelegate):
    """
    Delegate for rendering HTML/hyperlinks in item views.

    The style draws the item background (selection, hover, focus, alternating rows).
    Text uses the model's ForegroundRole color when not selected, and the palette's
    highlighted-text color when selected. Links stay clickable in both states.
    """

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        group = self._color_group(opt)

        if selected:
            painter.fillRect(opt.rect, opt.palette.brush(group, QPalette.ColorRole.Highlight))

        text_color = opt.palette.brush(group, QPalette.ColorRole.HighlightedText) if selected else None
        doc = self.get_document(option, index, opt.rect.width(), text_color)

        painter.save()
        painter.translate(opt.rect.topLeft())
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index):
        doc = self.get_document(option, index, option.rect.width())
        return doc.size().toSize()

    @staticmethod
    def _selected_brush(opt: QStyleOptionViewItem):
        """Returns the highlighted-text brush if the item is selected, else None."""
        if not (opt.state & QStyle.StateFlag.State_Selected):
            return None
        if not (opt.state & QStyle.StateFlag.State_Enabled):
            group = QPalette.ColorGroup.Disabled
        elif opt.state & QStyle.StateFlag.State_Active:
            group = QPalette.ColorGroup.Active
        else:
            group = QPalette.ColorGroup.Inactive
        return opt.palette.brush(group, QPalette.ColorRole.HighlightedText)

    def get_document(self, option: QStyleOptionViewItem, index: QModelIndex,
                     width: int = 0, color_override=None) -> QTextDocument:
        """
        Builds the QTextDocument for an item.

        :param width: Text width to lay out at (<= 0 leaves the width unconstrained).
        :param color_override: Brush that takes precedence over the model's ForegroundRole
                               (used for selected text).
        """
        doc = QTextDocument()
        doc.setHtml(index.data(Qt.ItemDataRole.DisplayRole) or "")

        color = color_override if color_override is not None else index.data(Qt.ItemDataRole.ForegroundRole)
        if color:
            cursor = QTextCursor(doc)
            cursor.select(QTextCursor.SelectionType.Document)
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor.mergeCharFormat(fmt)  # also recolors anchors, underline is kept

        if width > 0:
            doc.setTextWidth(width)
        return doc

    @staticmethod
    def _color_group(opt: QStyleOptionViewItem) -> QPalette.ColorGroup:
        if not (opt.state & QStyle.StateFlag.State_Enabled):
            return QPalette.ColorGroup.Disabled
        if opt.state & QStyle.StateFlag.State_Active:
            return QPalette.ColorGroup.Active
        return QPalette.ColorGroup.Inactive

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            doc = self.get_document(option, index, option.rect.width())
            pos = event.position() - QPointF(option.rect.topLeft())
            anchor = doc.documentLayout().anchorAt(pos)
            if anchor:
                webbrowser.open(anchor)
                return True
        return super().editorEvent(event, model, option, index)
