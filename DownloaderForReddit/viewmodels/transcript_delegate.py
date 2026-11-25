"""
An item delegate that draws the messages of a conversation transcript as wrapped rich text rows.

Rows keep the view's alternating background, a selected row is outlined instead of filled so that its text keeps its
colors, and links in a message open in the browser and show a pointing cursor.  A link to a thread is not opened but
reported through the thread_link_clicked signal.  Thread replies are indented by their depth, with a thin rail drawn
for each level.  The images of the reactions a row shows are loaded from their files once, scaled, and kept.


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

import os
from typing import Optional

from PyQt6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QObject, QPointF, QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon, QMouseEvent, QPainter, QPalette, QPen, QPixmap, QTextDocument
from PyQt6.QtWidgets import QAbstractItemView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..core.const import RESOURCES
from .transcript_list_model import (AUTHOR_ICON_SIZE, AUTHOR_ICON_URL, REACTION_IMAGE_PREFIX, REACTION_IMAGE_SIZE, THREAD_LINK_PREFIX,
                                    ReactionBadge, TranscriptEntry)


_PADDING = 6
_OUTLINE_WIDTH = 2
_OUTLINE_RADIUS = 4
_INDENT_PX = 18
_MAX_VISUAL_DEPTH = 8  # deeper replies are drawn at this depth so their text keeps a usable width
_RAIL_WIDTH = 2
_PLACEHOLDER_PATH = os.path.join(RESOURCES, 'images', 'image_placeholder.png')


class TranscriptDelegate(QStyledItemDelegate):
    """Draws transcript rows as rich text laid out to the width of the view."""

    # A thread link was clicked: the message id of the thread's root.
    thread_link_clicked = pyqtSignal(str)

    def __init__(self, view: QAbstractItemView) -> None:
        """
        Creates the delegate for a view and watches the view's mouse movement to show a pointing cursor over links.
        :param view: The view the delegate draws for.
        :type view: QAbstractItemView
        """
        super().__init__(view)
        self.view = view
        self._reaction_pixmaps: dict[Optional[str], QPixmap] = {}
        view.setMouseTracking(True)
        view.viewport().installEventFilter(self)

    @staticmethod
    def _levels(index: QModelIndex) -> int:
        """
        Returns how many levels a row is indented: its depth in its thread, capped at the deepest depth drawn.
        :param index: The row.
        :type index: QModelIndex
        :return: The number of levels; 0 for a row that is not a thread reply.
        :rtype: int
        """
        entry = index.data(Qt.ItemDataRole.UserRole)
        return min(entry.depth, _MAX_VISUAL_DEPTH) if isinstance(entry, TranscriptEntry) else 0

    def _text_width(self, row_width: int, indent: int) -> int:
        """
        Returns the width that message text is laid out at: the view's visible width (or the row's width before the
        view has one) less the padding on both sides and the row's indentation.
        :param row_width: The width of the row being laid out.
        :type row_width: int
        :param indent: The row's indentation in pixels.
        :type indent: int
        :return: The width in pixels, at least one.
        :rtype: int
        """
        return max((self.view.viewport().width() or row_width) - 2 * _PADDING - indent, 1)

    def reaction_pixmap(self, path: Optional[str]) -> QPixmap:
        """
        Returns a reaction's image at the size reactions are shown, centered on a transparent square; the first frame
        of an animated image.  A placeholder is used when the image has not been fetched or cannot be read.
        :param path: The image file, or None when it has not been fetched.
        :type path: Optional[str]
        :return: The pixmap.
        :rtype: QPixmap
        """
        key = path if path is not None and os.path.isfile(path) else None
        pixmap = self._reaction_pixmaps.get(key)
        if pixmap is None:
            image = QPixmap(key) if key is not None else QPixmap()
            if image.isNull():
                image = QPixmap(_PLACEHOLDER_PATH)
            pixmap = QPixmap(REACTION_IMAGE_SIZE, REACTION_IMAGE_SIZE)
            pixmap.fill(Qt.GlobalColor.transparent)
            if not image.isNull():
                scaled = image.scaled(REACTION_IMAGE_SIZE, REACTION_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
                painter = QPainter(pixmap)
                painter.drawPixmap((REACTION_IMAGE_SIZE - scaled.width()) // 2, (REACTION_IMAGE_SIZE - scaled.height()) // 2, scaled)
                painter.end()
            self._reaction_pixmaps[key] = pixmap
        return pixmap

    def clear_reaction_images(self) -> None:
        """
        Forgets the reaction images loaded so far, so images fetched since are read from their files.
        :return: None
        :rtype: None
        """
        self._reaction_pixmaps.clear()

    def _document(self, index: QModelIndex, width: int) -> QTextDocument:
        """
        Lays out a row's HTML, with the author's icon (the row's decoration) and the images of its reactions available
        as the images the HTML refers to.
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
        entry = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(entry, TranscriptEntry):
            badges: tuple[ReactionBadge, ...] = entry.reactions + ((entry.reaction,) if entry.reaction is not None else ())
            for badge in badges:
                doc.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(f'{REACTION_IMAGE_PREFIX}{badge.reaction_id}'),
                                self.reaction_pixmap(badge.image_path))
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
        Draws a row: its alternating background, a rail for each level it is indented, its text, and an outline when
        it is selected.
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

        levels = self._levels(index)
        indent = levels * _INDENT_PX
        if levels:
            painter.save()
            painter.setPen(QPen(opt.palette.brush(group, QPalette.ColorRole.Mid), _RAIL_WIDTH))
            for level in range(levels):
                x = opt.rect.left() + _PADDING + level * _INDENT_PX + _INDENT_PX // 2
                painter.drawLine(x, opt.rect.top(), x, opt.rect.bottom())
            painter.restore()

        doc = self._document(index, self._text_width(opt.rect.width(), indent))
        painter.save()
        painter.translate(QPointF(opt.rect.topLeft()) + QPointF(_PADDING + indent, _PADDING))
        painter.setClipRect(0, 0, opt.rect.width() - 2 * _PADDING - indent, opt.rect.height() - 2 * _PADDING)
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
        indent = self._levels(index) * _INDENT_PX
        width = self._text_width(option.rect.width(), indent)
        doc = self._document(index, width)
        return QSize(width + 2 * _PADDING + indent, int(doc.size().height()) + 2 * _PADDING)

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
        indent = self._levels(index) * _INDENT_PX
        doc = self._document(index, self._text_width(rect.width(), indent))
        return doc.documentLayout().anchorAt(position - QPointF(rect.topLeft()) - QPointF(_PADDING + indent, _PADDING))

    def editorEvent(self, event: QEvent, model: QAbstractItemModel, option: QStyleOptionViewItem, index: QModelIndex) -> bool:  # pylint: disable=invalid-name  # Qt override
        """
        Opens a link in the browser when it is clicked, or reports a clicked thread link through thread_link_clicked.
        :param event: The event.
        :type event: QEvent
        :param model: The model.
        :type model: QAbstractItemModel
        :param option: The style options for the row.
        :type option: QStyleOptionViewItem
        :param index: The row.
        :type index: QModelIndex
        :return: True when the event opened a link or a thread, otherwise the default handling's result.
        :rtype: bool
        """
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            anchor = self.anchor_at(index, event.position())
            if anchor.startswith(THREAD_LINK_PREFIX):
                self.thread_link_clicked.emit(anchor[len(THREAD_LINK_PREFIX):])
                return True
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
