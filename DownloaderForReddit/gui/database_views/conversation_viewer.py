"""
A window for reading the chats and private messages imported from Reddit data exports.

The list on the left holds the chat channels or the private message threads, most recently active first, narrowed by
the search box.  Selecting one shows its transcript in the middle, one row per message with the author's icon, and the
transcript can be exported as a text file.  The info button next to the transcript title opens a properties pane on
the right that describes the selected conversation (its identity, participants, dates and the imports it came from)
and lets a chat be given a nickname.  Participants are users, or subreddits for modmail, and each is shown with the
icon the rest of the application uses for that kind of reddit object.


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

import logging
import os
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import QApplication, QFileDialog, QListWidgetItem, QTableWidgetItem, QWidget

from ...core.const import RESOURCES
from ...database.conversation_queries import (CHAT, PRIVATE_MESSAGE, ConversationSummary, chat_messages, chat_summaries,
                                              conversation_properties, private_message_thread, private_thread_summaries,
                                              set_chat_nickname)
from ...database.export_models import ChatChannel, person_name
from ...database.models import RedditObject
from ...guiresources.database_views.conversation_viewer_auto import Ui_ConversationViewer
from ...utils import injector, system_util
from ...utils.exporters.conversation_exporter import export_chat_transcript, export_private_message_thread
from ...viewmodels.reddit_object_display import ICONS, RedditObjectStateDisplay
from ...viewmodels.transcript_delegate import TranscriptDelegate
from ...viewmodels.transcript_list_model import TranscriptEntry, TranscriptListModel


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

_KINDS = (CHAT, PRIVATE_MESSAGE)
_SEARCH_DELAY_MS = 250
_INFO_ICON_PATH = os.path.join(RESOURCES, 'images', 'info.svg')
_EXPORT_ICON_PATH = os.path.join(RESOURCES, 'images', 'download.svg')


def participant_icon(display: RedditObjectStateDisplay, participant: Optional[RedditObject]) -> QIcon:
    """
    Returns the icon shown in front of a conversation participant's name.  A participant is a user, or a subreddit
    for modmail; each gets the icon the rest of the application shows for that kind of reddit object in its state.
    :param display: Decides icons for reddit objects from the display settings.
    :type display: RedditObjectStateDisplay
    :param participant: The participant, or None for a message that could not be linked to one.
    :type participant: Optional[RedditObject]
    :return: The icon; a blank one, so names stay aligned, when there is no participant or no icon for its kind.
    :rtype: QIcon
    """
    if participant is None or participant.object_type not in ICONS:
        return display.blank()
    return display.icon(participant)


def _summary_text(summary: ConversationSummary) -> str:
    """
    Returns the text of a conversation's entry in the list: its title, then its message count and last date.
    :param summary: The conversation.
    :type summary: ConversationSummary
    :return: The two-line text.
    :rtype: str
    """
    last = summary.last_date.strftime('%Y-%m-%d') if summary.last_date is not None else 'no date'
    return f'{summary.title}\n{summary.message_count:,} messages, last {last}'


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
        self.splitter.setSizes([300, 700, 280])
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(_SEARCH_DELAY_MS)
        self.search_timer.timeout.connect(self.load_conversations)

        self.transcript_model = TranscriptListModel(self)
        self.transcript_view.setModel(self.transcript_model)
        self.transcript_delegate = TranscriptDelegate(self.transcript_view)
        self.transcript_view.setItemDelegate(self.transcript_delegate)
        self.copy_action = QAction('Copy', self.transcript_view)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.copy_action.triggered.connect(self.copy_selected_messages)
        self.transcript_view.addAction(self.copy_action)
        self.icon_display = RedditObjectStateDisplay(injector.get_settings_manager())
        self.nickname_channel_id: Optional[int] = None
        self.properties_button.setIcon(QIcon(_INFO_ICON_PATH))
        self.export_button.setIcon(QIcon(_EXPORT_ICON_PATH))

        self.kind_combo.currentIndexChanged.connect(self.load_conversations)
        self.nickname_line_edit.editingFinished.connect(self.save_nickname)
        self.search_line_edit.textChanged.connect(self.search_timer.start)
        self.refresh_button.clicked.connect(self.load_conversations)
        self.export_button.clicked.connect(self.export_transcript)
        self.properties_button.toggled.connect(self.set_properties_visible)
        self.properties_close_button.clicked.connect(lambda: self.properties_button.setChecked(False))
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
        self.clear_transcript()
        for summary in summaries:
            item = QListWidgetItem(_summary_text(summary))
            item.setData(Qt.ItemDataRole.UserRole, summary)
            item.setToolTip(summary.title)
            self.conversation_list.addItem(item)
        noun = 'chats' if self.kind == CHAT else 'message threads'
        self.status_label.setText(f'{len(summaries):,} {noun}' if summaries else
                                  f'No {noun}. Import a Reddit data export from File > Import Reddit Data Export.')
        self.export_button.setEnabled(False)
        if summaries:
            self.conversation_list.setCurrentRow(0)

    def clear_transcript(self) -> None:
        """
        Empties the transcript, its title and the properties pane.
        :return: None
        :rtype: None
        """
        self.transcript_model.clear()
        self.transcript_title_label.clear()
        self.properties_table.setRowCount(0)
        self._fill_nickname(None, None)

    def _fill_nickname(self, channel_id: Optional[int], nickname: Optional[str]) -> None:
        """
        Shows a chat's nickname in the properties pane, or disables the nickname field when no chat is selected.
        :param channel_id: The chat channel the field now edits, or None when it edits nothing.
        :type channel_id: Optional[int]
        :param nickname: The channel's stored nickname.
        :type nickname: Optional[str]
        :return: None
        :rtype: None
        """
        self.nickname_channel_id = channel_id
        self.nickname_line_edit.blockSignals(True)
        self.nickname_line_edit.setText(nickname or '')
        self.nickname_line_edit.blockSignals(False)
        self.nickname_line_edit.setEnabled(channel_id is not None)

    def show_selected(self) -> None:
        """
        Shows the transcript of the selected conversation, scrolled to its newest message, and its properties when the
        properties pane is open.
        :return: None
        :rtype: None
        """
        summary = self.selected_summary()
        self.export_button.setEnabled(summary is not None)
        if summary is None:
            self.clear_transcript()
            return
        with self.db.get_scoped_session() as session:
            if summary.kind == CHAT:
                channel = session.query(ChatChannel).get(summary.key)
                entries = [TranscriptEntry(person_name(message.author), message.date_posted, message.body,
                                           'thread reply' if message.thread_parent_message_id else None,
                                           participant_icon(self.icon_display, message.author))
                           for message in chat_messages(session, summary.key)]
                title = channel.display_name if channel is not None else summary.title
            else:
                entries = [TranscriptEntry(person_name(message.sender), message.date_sent, message.body,
                                           f'to {person_name(message.recipient)}', participant_icon(self.icon_display, message.sender))
                           for message in private_message_thread(session, summary.key)]
                title = summary.title
        self.transcript_title_label.setText(title)
        self.transcript_model.set_entries(entries)
        self.transcript_view.scrollToBottom()
        self.show_properties()

    def set_properties_visible(self, visible: bool) -> None:
        """
        Shows or hides the properties pane, filling it for the selected conversation when it is shown.
        :param visible: Whether the pane is shown.
        :type visible: bool
        :return: None
        :rtype: None
        """
        self.properties_frame.setVisible(visible)
        if visible:
            self.show_properties()

    def show_properties(self) -> None:
        """
        Fills the properties pane with the selected conversation's properties, each participant with its icon, and the
        nickname field with a chat's nickname.  Nothing is looked up while the pane is hidden.
        :return: None
        :rtype: None
        """
        if self.properties_frame.isHidden():
            return
        summary = self.selected_summary()
        items: list[tuple[QTableWidgetItem, QTableWidgetItem]] = []
        channel_id, nickname = None, None
        if summary is not None:
            with self.db.get_scoped_session() as session:
                for row in conversation_properties(session, summary):
                    name_item = QTableWidgetItem(row.name)
                    name_item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                    value_item = QTableWidgetItem(row.value)
                    value_item.setToolTip(row.value)
                    if row.is_participant:
                        value_item.setIcon(participant_icon(self.icon_display, row.participant))
                    items.append((name_item, value_item))
                if summary.kind == CHAT:
                    channel = session.query(ChatChannel).get(summary.key)
                    if channel is not None:
                        channel_id, nickname = channel.id, channel.nickname
        self.properties_table.setRowCount(len(items))
        for row_number, (name_item, value_item) in enumerate(items):
            self.properties_table.setItem(row_number, 0, name_item)
            self.properties_table.setItem(row_number, 1, value_item)
        self.properties_table.resizeColumnToContents(0)
        self.properties_table.resizeRowsToContents()
        self._fill_nickname(channel_id, nickname)

    def save_nickname(self) -> None:
        """
        Stores the nickname typed for the chat the nickname field shows, then renames that chat in the list, the
        transcript title and the properties.  Nothing is stored when the nickname did not change.
        :return: None
        :rtype: None
        """
        channel_id = self.nickname_channel_id
        if channel_id is None:
            return
        text = self.nickname_line_edit.text().strip()
        with self.db.get_scoped_session() as session:
            channel = session.query(ChatChannel).get(channel_id)
            if channel is None or (channel.nickname or '') == text:
                return
            title = set_chat_nickname(session, channel_id, text)
        if title is None:
            return
        for row in range(self.conversation_list.count()):
            item = self.conversation_list.item(row)
            summary = item.data(Qt.ItemDataRole.UserRole)
            if summary.kind == CHAT and summary.key == channel_id:
                summary.title = title
                item.setData(Qt.ItemDataRole.UserRole, summary)
                item.setText(_summary_text(summary))
                item.setToolTip(title)
        selected = self.selected_summary()
        if selected is not None and selected.kind == CHAT and selected.key == channel_id:
            self.transcript_title_label.setText(title)
            self.show_properties()

    def copy_selected_messages(self) -> None:
        """
        Copies the selected messages to the clipboard as plain text.
        :return: None
        :rtype: None
        """
        rows = [index.row() for index in self.transcript_view.selectionModel().selectedIndexes()]
        if rows:
            QApplication.clipboard().setText(self.transcript_model.plain_text(rows))

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
