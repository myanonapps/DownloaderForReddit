"""
An item delegate that draws the messages of a conversation transcript as wrapped rich text rows.

Rows keep the view's alternating background, a selected row is outlined instead of filled so that its text keeps its
colors, and links in a message open in the browser and show a pointing cursor.


Copyright (C) 2017, Kyle Hickey


This file is part of the Downloader for Reddit.

Downloader for Reddit is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Downloader for Reddit is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Downloader for Reddit.  If not, see <http://www.gnu.org/licenses/>.
"""

from PyQt6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QObject, QPointF, QRectF, QSize, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QMouseEvent, QPainter, QPalette, QPen, QTextDocument
from PyQt6.QtWidgets import QAbstractItemView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .transcript_list_model import AUTHOR_ICON_SIZE, AUTHOR_ICON_URL


_PADDING = 6
_OUTLINE_WIDTH = 2
_OUTLINE_RADIUS = 4


class TranscriptDelegate(QStyledItemDelegate):
    """Draws transcript rows as rich text laid out to the width of the view."""

    def __init__(self, view: QAbstractItemView) -> None:
        """
        Creates the delegate for a view and watches the view's mouse movement to show a pointing cursor over links.
        :param view: The view the delegate draws for.
        :type view: QAbstractItemView
        """
        super().__init__(view)
        self.view = view
        view.setMouseTracking(True)
        view.viewport().installEventFilter(self)

    def _text_width(self, row_width: int) -> int:
        """
        Returns the width that message text is laid out at: the view's visible width (or the row's width before the
        view has one) less the padding on both sides.
        :param row_width: The width of the row being laid out.
        :type row_width: int
        :return: The width in pixels, at least one.
        :rtype: int
        """
        return max((self.view.viewport().width() or row_width) - 2 * _PADDING, 1)

    @staticmethod
    def _document(index: QModelIndex, width: int) -> QTextDocument:
        """
        Lays out a row's HTML, with the author's icon (the row's decoration) available as the image the HTML refers to.
        :param index: The row.
        :type index: QModelIndex
        :param width: The width to wrap the text at.
        :type width: int
        :return: The laid out document.
        :rtype: QTextDocument
        """
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            doc.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(AUTHOR_ICON_URL),
                            icon.pixmap(AUTHOR_ICON_SIZE, AUTHOR_ICON_SIZE))
        doc.setHtml(index.data(Qt.ItemDataRole.DisplayRole) or '')
        doc.setTextWidth(width)
        return doc

    @staticmethod
    def _color_group(option: QStyleOptionViewItem) -> QPalette.ColorGroup:
        """
        Returns the palette color group matching a row's state.
        :param option: The style options for the row.
        :type option: QStyleOptionViewItem
        :return: The color group.
        :rtype: QPalette.ColorGroup
        """
        if not option.state & QStyle.StateFlag.State_Enabled:
            return QPalette.ColorGroup.Disabled
        if option.state & QStyle.StateFlag.State_Active:
            return QPalette.ColorGroup.Active
        return QPalette.ColorGroup.Inactive

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """
        Draws a row: its alternating background, its text, and an outline when it is selected.
        :param painter: The painter.
        :type painter: QPainter
        :param option: The style options for the row.
        :type option: QStyleOptionViewItem
        :param index: The row.
        :type index: QModelIndex
        :return: None
        :rtype: None
        """
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        group = self._color_group(opt)
        alternate = bool(opt.features & QStyleOptionViewItem.ViewItemFeature.Alternate)
        painter.fillRect(opt.rect, opt.palette.brush(group, QPalette.ColorRole.AlternateBase if alternate else QPalette.ColorRole.Base))

        doc = self._document(index, self._text_width(opt.rect.width()))
        painter.save()
        painter.translate(QPointF(opt.rect.topLeft()) + QPointF(_PADDING, _PADDING))
        painter.setClipRect(0, 0, opt.rect.width() - 2 * _PADDING, opt.rect.height() - 2 * _PADDING)
        doc.drawContents(painter)
        painter.restore()

        if opt.state & QStyle.StateFlag.State_Selected:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(opt.palette.brush(group, QPalette.ColorRole.Highlight), _OUTLINE_WIDTH)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = _OUTLINE_WIDTH / 2
            painter.drawRoundedRect(QRectF(opt.rect).adjusted(inset, inset, -inset, -inset), _OUTLINE_RADIUS, _OUTLINE_RADIUS)
            painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # pylint: disable=invalid-name  # Qt override
        """
        Returns the size of a row: the view's width, and the height of its wrapped text plus padding.
        :param option: The style options for the row.
        :type option: QStyleOptionViewItem
        :param index: The row.
        :type index: QModelIndex
        :return: The size.
        :rtype: QSize
        """
        width = self._text_width(option.rect.width())
        doc = self._document(index, width)
        return QSize(width + 2 * _PADDING, int(doc.size().height()) + 2 * _PADDING)

    def anchor_at(self, index: QModelIndex, position: QPointF) -> str:
        """
        Returns the link under a point of the view.
        :param index: The row under the point.
        :type index: QModelIndex
        :param position: The point, in viewport coordinates.
        :type position: QPointF
        :return: The link's url, or an empty string when the point is not over a link.
        :rtype: str
        """
        if not index.isValid():
            return ''
        rect = self.view.visualRect(index)
        doc = self._document(index, self._text_width(rect.width()))
        return doc.documentLayout().anchorAt(position - QPointF(rect.topLeft()) - QPointF(_PADDING, _PADDING))

    def editorEvent(self, event: QEvent, model: QAbstractItemModel, option: QStyleOptionViewItem, index: QModelIndex) -> bool:  # pylint: disable=invalid-name  # Qt override
        """
        Opens a link in the browser when it is clicked.
        :param event: The event.
        :type event: QEvent
        :param model: The model.
        :type model: QAbstractItemModel
        :param option: The style options for the row.
        :type option: QStyleOptionViewItem
        :param index: The row.
        :type index: QModelIndex
        :return: True when the event opened a link, otherwise the default handling's result.
        :rtype: bool
        """
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            anchor = self.anchor_at(index, event.position())
            if anchor:
                QDesktopServices.openUrl(QUrl(anchor))
                return True
        return super().editorEvent(event, model, option, index)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # pylint: disable=invalid-name  # Qt override
        """
        Shows a pointing cursor while the mouse is over a link in the view.
        :param watched: The object the event is for.
        :type watched: QObject
        :param event: The event.
        :type event: QEvent
        :return: Whether the event was consumed; it never is here.
        :rtype: bool
        """
        if watched is self.view.viewport():
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                position = event.position()
                over_link = bool(self.anchor_at(self.view.indexAt(position.toPoint()), position))
                self.view.viewport().setCursor(Qt.CursorShape.PointingHandCursor if over_link else Qt.CursorShape.ArrowCursor)
            elif event.type() == QEvent.Type.Leave:
                self.view.viewport().unsetCursor()
            return False
        return super().eventFilter(watched, event)
