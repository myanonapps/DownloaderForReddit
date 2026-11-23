"""
A window for reading the chats and private messages imported from Reddit data exports.

The list on the left holds the chat channels or the private message threads, most recently active first, narrowed by
the search box.  Selecting one shows its transcript on the right, and the transcript can be exported as a text file.


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
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFileDialog, QListWidgetItem, QWidget

from ...database.conversation_queries import (CHAT, PRIVATE_MESSAGE, ConversationSummary, chat_messages, chat_summaries,
                                              private_message_thread, private_thread_summaries)
from ...database.export_models import ChatChannel, ExportImport
from ...guiresources.database_views.conversation_viewer_auto import Ui_ConversationViewer
from ...utils import injector, system_util
from ...utils.exporters.conversation_exporter import export_chat_transcript, export_private_message_thread
from ...utils.html_formatting import linkify_urls


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

_KINDS = (CHAT, PRIVATE_MESSAGE)
_SEARCH_DELAY_MS = 250
_DATE_FORMAT = '%Y-%m-%d %H:%M'


@dataclass
class TranscriptEntry:
    """One message as shown in a transcript."""

    author: Optional[str]
    date: Optional[datetime]
    body: Optional[str]
    note: Optional[str] = None
    is_owner: bool = False


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


def render_transcript_html(title: str, entries: Iterable[TranscriptEntry]) -> str:
    """
    Renders a conversation as HTML for the transcript pane.
    :param title: The conversation's title.
    :type title: str
    :param entries: The messages, in the order to show them.
    :type entries: Iterable[TranscriptEntry]
    :return: The HTML document.
    :rtype: str
    """
    parts = [f'<h3>{html.escape(title)}</h3>']
    for entry in entries:
        author = html.escape(entry.author or '[unknown]')
        if entry.is_owner:
            author = f'<span style="color:#2a7ae2">{author}</span>'
        date = entry.date.strftime(_DATE_FORMAT) if entry.date is not None else ''
        note = f' <i>{html.escape(entry.note)}</i>' if entry.note else ''
        parts.append(f'<p><b>{author}</b> <span style="color:gray">{date}</span>{note}<br/>{format_body_html(entry.body)}</p>')
    return ''.join(parts)


class ConversationViewer(QWidget, Ui_ConversationViewer):
    """Lists imported conversations and shows their transcripts."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Builds the window and lists the chats.
        :param parent: The parent widget.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        self.setupUi(self)
        self.db = injector.get_database_handler()
        self.splitter.setSizes([320, 680])
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(_SEARCH_DELAY_MS)
        self.search_timer.timeout.connect(self.load_conversations)

        self.kind_combo.currentIndexChanged.connect(self.load_conversations)
        self.search_line_edit.textChanged.connect(self.search_timer.start)
        self.refresh_button.clicked.connect(self.load_conversations)
        self.export_button.clicked.connect(self.export_transcript)
        self.conversation_list.currentItemChanged.connect(self.show_selected)
        self.load_conversations()

    @property
    def kind(self) -> str:
        """
        The kind of conversation listed.
        :return: CHAT or PRIVATE_MESSAGE.
        :rtype: str
        """
        return _KINDS[self.kind_combo.currentIndex()]

    def selected_summary(self) -> Optional[ConversationSummary]:
        """
        Returns the summary of the selected conversation.
        :return: The summary, or None when nothing is selected.
        :rtype: Optional[ConversationSummary]
        """
        item = self.conversation_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def load_conversations(self) -> None:
        """
        Lists the conversations of the chosen kind that match the search text.
        :return: None
        :rtype: None
        """
        search = self.search_line_edit.text().strip() or None
        with self.db.get_scoped_session() as session:
            summaries = chat_summaries(session, search) if self.kind == CHAT else private_thread_summaries(session, search)
        self.conversation_list.clear()
        self.transcript_browser.clear()
        for summary in summaries:
            last = summary.last_date.strftime('%Y-%m-%d') if summary.last_date is not None else 'no date'
            item = QListWidgetItem(f'{summary.title}\n{summary.message_count:,} messages, last {last}')
            item.setData(Qt.ItemDataRole.UserRole, summary)
            self.conversation_list.addItem(item)
        noun = 'chats' if self.kind == CHAT else 'message threads'
        self.status_label.setText(f'{len(summaries):,} {noun}' if summaries else
                                  f'No {noun}. Import a Reddit data export from File > Import Reddit Data Export.')
        self.export_button.setEnabled(False)
        if summaries:
            self.conversation_list.setCurrentRow(0)

    def show_selected(self) -> None:
        """
        Shows the transcript of the selected conversation.
        :return: None
        :rtype: None
        """
        summary = self.selected_summary()
        self.export_button.setEnabled(summary is not None)
        if summary is None:
            self.transcript_browser.clear()
            return
        with self.db.get_scoped_session() as session:
            owners = {name.lower() for name, in session.query(ExportImport.account_name).distinct() if name}
            if summary.kind == CHAT:
                channel = session.query(ChatChannel).get(summary.key)
                entries = [TranscriptEntry(message.author_name, message.date_posted, message.body,
                                           'thread reply' if message.thread_parent_message_id else None,
                                           (message.author_name or '').lower() in owners)
                           for message in chat_messages(session, summary.key)]
                title = channel.display_name if channel is not None else summary.title
            else:
                entries = [TranscriptEntry(message.sender_name, message.date_sent, message.body,
                                           f'to {message.recipient_name}' if message.recipient_name else None,
                                           (message.sender_name or '').lower() in owners)
                           for message in private_message_thread(session, summary.key)]
                title = summary.title
        self.transcript_browser.setHtml(render_transcript_html(title, entries))

    def export_transcript(self) -> None:
        """
        Saves the selected conversation's transcript as a text file chosen by the user.
        :return: None
        :rtype: None
        """
        summary = self.selected_summary()
        if summary is None:
            return
        settings_manager = injector.get_settings_manager()
        default_name = f'{system_util.clean(summary.title)[:80] or "conversation"}.txt'
        path = QFileDialog.getSaveFileName(self, 'Export Transcript', os.path.join(settings_manager.export_file_path, default_name),
                                           'Text Files (*.txt)')[0]
        if not path:
            return
        try:
            with self.db.get_scoped_session() as session:
                if summary.kind == CHAT:
                    count = export_chat_transcript(session, summary.key, path)
                else:
                    count = export_private_message_thread(session, summary.key, path)
        except (OSError, ValueError) as error:
            logger.warning('Transcript export failed', exc_info=True)
            self.status_label.setText(f'Export failed: {error}')
            return
        self.status_label.setText(f'Exported {count:,} messages to {path}')
