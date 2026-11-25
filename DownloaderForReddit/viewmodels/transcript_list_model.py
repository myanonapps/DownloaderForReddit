"""
A list model holding the messages of one imported conversation, one row per message, for the conversation viewer.

Each row's display text is a small HTML fragment (author, date, note and body) that TranscriptDelegate renders.  A
chat message that started a thread also shows a link, under THREAD_LINK_PREFIX, that opens the thread; the delegate
indents the rows of a thread by their depth.  Reactions to a message are shown as small images under it, referenced
as REACTION_IMAGE_PREFIX image resources that the delegate adds; a row that is itself a reaction shows its image in
place of its text.


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
THREAD_LINK_PREFIX = 'thread:'
INDENT_TEXT = '    '
AUTHOR_ICON_URL = 'author-icon'
AUTHOR_ICON_SIZE = 16
REACTION_IMAGE_PREFIX = 'reaction:'
REACTION_IMAGE_SIZE = 24
_UNKNOWN_AUTHOR = '[unknown]'


@dataclass
class ReactionBadge:
    """
    One reaction as shown on a message: the reaction's image, and who reacted with it and when (for example
    'alice 2024-01-02 03:04').
    """

    reaction_id: int
    label: str
    url: str
    image_path: Optional[str] = None
    reactors: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        """
        How many times the message got the reaction.
        :return: The number of reactors, at least one.
        :rtype: int
        """
        return max(len(self.reactors), 1)


@dataclass
class TranscriptEntry:  # pylint: disable=too-many-instance-attributes  # plain record of one transcript row
    """
    One message as shown in a transcript.  The icon is the author's reddit object icon (a user, or a subreddit for
    modmail), shown in front of the author's name.  The content paths are the files downloaded from the message's
    links, and the content count also includes media found but not downloaded (yet).  The depth is how far a thread
    reply is nested; a message that started a thread has its thread key, reply count and last reply date set.  The
    reactions are those the message got; reaction is set when the message is itself a reaction, shown on its own
    because the message it reacts to is missing.
    """

    author: Optional[str]
    date: Optional[datetime]
    body: Optional[str]
    note: Optional[str] = None
    icon: Optional[QIcon] = None
    message_id: Optional[int] = None
    content_count: int = 0
    content_paths: tuple[str, ...] = ()
    depth: int = 0
    thread_key: Optional[str] = None
    reply_count: int = 0
    last_reply_date: Optional[datetime] = None
    reactions: tuple[ReactionBadge, ...] = ()
    reaction: Optional[ReactionBadge] = None


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


def thread_link_text(entry: TranscriptEntry) -> str:
    """
    Describes the thread a message started, for the link that opens it.
    :param entry: The message.
    :type entry: TranscriptEntry
    :return: For example '3 replies, last 2024-01-02 03:04'; empty when the message started no thread.
    :rtype: str
    """
    if entry.reply_count == 0 or entry.thread_key is None:
        return ''
    noun = 'reply' if entry.reply_count == 1 else 'replies'
    last = f', last {entry.last_reply_date.strftime(DATE_FORMAT)}' if entry.last_reply_date is not None else ''
    return f'{entry.reply_count:,} {noun}{last}'


def reaction_image_html(badge: ReactionBadge) -> str:
    """
    Renders a reaction's image, referenced as the image resource the delegate adds for it.
    :param badge: The reaction.
    :type badge: ReactionBadge
    :return: The HTML img element.
    :rtype: str
    """
    return (f'<img src="{REACTION_IMAGE_PREFIX}{badge.reaction_id}" width="{REACTION_IMAGE_SIZE}" height="{REACTION_IMAGE_SIZE}" '
            f'style="vertical-align:middle"/>')


def reactions_html(entry: TranscriptEntry) -> str:
    """
    Renders the line of reactions a message got: each reaction's image, followed by how many times when more than once.
    :param entry: The message.
    :type entry: TranscriptEntry
    :return: The HTML, starting with a line break; empty when the message got no reactions.
    :rtype: str
    """
    if not entry.reactions:
        return ''
    badges = '&nbsp;&nbsp;'.join(reaction_image_html(badge) + (f'&nbsp;×{badge.count}' if badge.count > 1 else '')
                                 for badge in entry.reactions)
    return f'<br/>{badges}'


def reactions_text(entry: TranscriptEntry) -> str:
    """
    Describes the reactions a message got, naming each reaction and who reacted with it.
    :param entry: The message.
    :type entry: TranscriptEntry
    :return: For example 'Reactions: heart (alice 2024-01-02 03:04, bob)'; empty when the message got no reactions.
    :rtype: str
    """
    if not entry.reactions:
        return ''
    return 'Reactions: ' + '; '.join(f'{badge.label} ({", ".join(badge.reactors)})' if badge.reactors else badge.label
                                     for badge in entry.reactions)


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
    date in gray, an optional note, and the body below, followed by the media found and the link to the thread the
    message started, and the reactions it got, when there are any.  A message that is itself a reaction shows its
    image in place of the body.  The icon is referenced as the AUTHOR_ICON_URL image resource, which the delegate adds
    to the document.
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
    link_text = thread_link_text(entry)
    thread = (f'<br/><a href="{html.escape(THREAD_LINK_PREFIX + (entry.thread_key or ""))}">{html.escape(link_text)}</a>'
              if link_text else '')
    body = f'<i>reacted</i> {reaction_image_html(entry.reaction)}' if entry.reaction is not None else format_body_html(entry.body)
    return f'{icon}<b>{author}</b> <span style="color:gray">{date}</span>{note}<br/>{body}{media}{thread}{reactions_html(entry)}'


def entry_plain_text(entry: TranscriptEntry) -> str:
    """
    Renders one message as plain text, for copying.
    :param entry: The message.
    :type entry: TranscriptEntry
    :return: A header line with the author, date and note, followed by the body and the reactions the message got,
             every line indented by the message's depth in its thread.
    :rtype: str
    """
    header = ' '.join(part for part in (entry.author or _UNKNOWN_AUTHOR,
                                        entry.date.strftime(DATE_FORMAT) if entry.date is not None else '',
                                        f'({entry.note})' if entry.note else '') if part)
    body = f'reacted {entry.reaction.label}' if entry.reaction is not None else entry.body or ''
    reactions = reactions_text(entry)
    text = f'{header}\n{body}\n{reactions}' if reactions else f'{header}\n{body}'
    indent = INDENT_TEXT * entry.depth
    return '\n'.join(f'{indent}{line}' for line in text.split('\n'))


def entry_tooltip(entry: TranscriptEntry) -> Optional[str]:
    """
    Returns the tooltip of a transcript row: the message's full date, then who reacted to it with what.
    :param entry: The message.
    :type entry: TranscriptEntry
    :return: The tooltip, or None when there is nothing to show.
    :rtype: Optional[str]
    """
    lines = [entry.date.strftime('%Y-%m-%d %H:%M:%S')] if entry.date is not None else []
    for badge in entry.reactions:
        lines.append(f'{badge.label}: {", ".join(badge.reactors)}' if badge.reactors else badge.label)
    if entry.reaction is not None:
        lines.append(f'Reaction: {entry.reaction.label}')
    return '\n'.join(lines) or None


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
        Returns a message's HTML for display, its author's icon for decoration, its full date and reactions as a
        tooltip, or the entry itself for the user role.
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
            return entry_tooltip(entry)
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
