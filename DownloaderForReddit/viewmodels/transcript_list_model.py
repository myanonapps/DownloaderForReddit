"""
A list model holding the messages of one imported conversation, one row per message, for the conversation viewer.

Each row's display text is a small HTML fragment (author, date, note and body) that TranscriptDelegate renders.


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

import html
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from PyQt6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt
from PyQt6.QtGui import QIcon

from ..utils.html_formatting import linkify_urls


DATE_FORMAT = '%Y-%m-%d %H:%M'
AUTHOR_ICON_URL = 'author-icon'
AUTHOR_ICON_SIZE = 16
_UNKNOWN_AUTHOR = '[unknown]'


@dataclass
class TranscriptEntry:  # pylint: disable=too-many-instance-attributes  # plain record of one transcript row
    """
    One message as shown in a transcript.  The icon is the author's reddit object icon (a user, or a subreddit for
    modmail), shown in front of the author's name.  The content paths are the files downloaded from the message's
    links, and the content count also includes media found but not downloaded (yet).
    """

    author: Optional[str]
    date: Optional[datetime]
    body: Optional[str]
    note: Optional[str] = None
    icon: Optional[QIcon] = None
    message_id: Optional[int] = None
    content_count: int = 0
    content_paths: tuple[str, ...] = ()


def media_marker(entry: TranscriptEntry) -> str:
    """
    Describes the media found in a message's links, for the line under its text.
    :param entry: The message.
    :type entry: TranscriptEntry
    :return: For example '[2 media files downloaded]' or '[1 of 2 media files downloaded]'; empty when the message has
             no media.
    :rtype: str
    """
    if entry.content_count == 0:
        return ''
    noun = 'media file' if entry.content_count == 1 else 'media files'
    downloaded = len(entry.content_paths)
    if downloaded == entry.content_count:
        return f'[{entry.content_count} {noun} downloaded]'
    return f'[{downloaded} of {entry.content_count} {noun} downloaded]'


def format_body_html(body: Optional[str]) -> str:
    """
    Turns a message body into safe HTML: special characters are escaped, links are made clickable and line breaks are
    kept.
    :param body: The message text.
    :type body: Optional[str]
    :return: The HTML.
    :rtype: str
    """
    if not body:
        return '<i>[no text]</i>'
    return linkify_urls(html.escape(body, quote=False)).replace('\n', '<br/>')


def render_entry_html(entry: TranscriptEntry) -> str:
    """
    Renders one message as HTML for a transcript row: the author's icon when there is one, the author in bold, the
    date in gray, an optional note, and the body below.  The icon is referenced as the AUTHOR_ICON_URL image resource,
    which the delegate adds to the document.
    :param entry: The message.
    :type entry: TranscriptEntry
    :return: The HTML fragment.
    :rtype: str
    """
    icon = (f'<img src="{AUTHOR_ICON_URL}" width="{AUTHOR_ICON_SIZE}" height="{AUTHOR_ICON_SIZE}" style="vertical-align:middle"/>&nbsp;'
            if entry.icon is not None else '')
    author = html.escape(entry.author or _UNKNOWN_AUTHOR)
    date = entry.date.strftime(DATE_FORMAT) if entry.date is not None else ''
    note = f' <i>{html.escape(entry.note)}</i>' if entry.note else ''
    marker = media_marker(entry)
    media = f'<br/><span style="color:gray">{html.escape(marker)}</span>' if marker else ''
    return f'{icon}<b>{author}</b> <span style="color:gray">{date}</span>{note}<br/>{format_body_html(entry.body)}{media}'


def entry_plain_text(entry: TranscriptEntry) -> str:
    """
    Renders one message as plain text, for copying.
    :param entry: The message.
    :type entry: TranscriptEntry
    :return: A header line with the author, date and note, followed by the body.
    :rtype: str
    """
    header = ' '.join(part for part in (entry.author or _UNKNOWN_AUTHOR,
                                        entry.date.strftime(DATE_FORMAT) if entry.date is not None else '',
                                        f'({entry.note})' if entry.note else '') if part)
    return f'{header}\n{entry.body or ""}'


class TranscriptListModel(QAbstractListModel):
    """Holds the messages of the conversation shown in the viewer, oldest first."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """
        Creates an empty model.
        :param parent: The parent object.
        :type parent: Optional[QObject]
        """
        super().__init__(parent)
        self.entries: list[TranscriptEntry] = []
        self._html: list[str] = []

    def set_entries(self, entries: Iterable[TranscriptEntry]) -> None:
        """
        Replaces the messages shown.
        :param entries: The messages, oldest first.
        :type entries: Iterable[TranscriptEntry]
        :return: None
        :rtype: None
        """
        self.beginResetModel()
        self.entries = list(entries)
        self._html = [render_entry_html(entry) for entry in self.entries]
        self.endResetModel()

    def clear(self) -> None:
        """
        Removes all messages.
        :return: None
        :rtype: None
        """
        self.set_entries([])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # pylint: disable=invalid-name  # Qt override
        """
        Returns the number of messages.
        :param parent: The parent index; rows only exist at the top level.
        :type parent: QModelIndex
        :return: The number of rows.
        :rtype: int
        """
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """
        Returns a message's HTML for display, its author's icon for decoration, its full date as a tooltip, or the
        entry itself for the user role.
        :param index: The row.
        :type index: QModelIndex
        :param role: The data role.
        :type role: int
        :return: The data, or None for roles and rows that have none.
        :rtype: Any
        """
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        entry = self.entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._html[index.row()]
        if role == Qt.ItemDataRole.DecorationRole:
            return entry.icon
        if role == Qt.ItemDataRole.ToolTipRole:
            return entry.date.strftime('%Y-%m-%d %H:%M:%S') if entry.date is not None else None
        if role == Qt.ItemDataRole.UserRole:
            return entry
        return None

    def plain_text(self, rows: Iterable[int]) -> str:
        """
        Returns messages as plain text, in transcript order, separated by blank lines.
        :param rows: The rows to include, in any order.
        :type rows: Iterable[int]
        :return: The text.
        :rtype: str
        """
        return '\n\n'.join(entry_plain_text(self.entries[row]) for row in sorted(set(rows)) if 0 <= row < len(self.entries))
