"""
A window for reading the chats and private messages imported from Reddit data exports.

The list on the left holds the chat channels or the private message threads, most recently active first, narrowed by
the search box.  Selecting one shows its transcript in the middle, one row per message with the author's icon, and the
transcript can be exported as a text file.  The info button next to the transcript title opens a properties pane on
the right that describes the selected conversation (its identity, participants, dates and the imports it came from)
and lets a chat be given a nickname.  Messages whose links held media say how many files were found and downloaded;
the files can be opened from the transcript's context menu, and the media of the selected conversation can be
downloaded with its download button, which asks the main window to run the download.  The media button opens a pane
under the transcript that shows thumbnails of the media of the selected messages, as the database viewer's content
view does; a thumbnail opens its file when double clicked.  Participants are users, or subreddits for modmail, and each
is shown with the icon the rest of the application uses for that kind of reddit object.


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
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QItemSelectionModel, QModelIndex, QPoint, QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PyQt6.QtWidgets import QApplication, QFileDialog, QListWidgetItem, QMenu, QTableWidgetItem, QWidget

from ...core.const import RESOURCES
from ...database.conversation_queries import (CHAT, PRIVATE_MESSAGE, ConversationSummary, chat_messages, chat_summaries,
                                              conversation_properties, message_content, message_content_query,
                                              private_message_thread,
                                              private_thread_summaries, set_chat_nickname, unextracted_message_ids)
from ...database.export_models import ChatChannel, person_name
from ...database.models import Content, RedditObject
from ...guiresources.database_views.conversation_viewer_auto import Ui_ConversationViewer
from ...utils import injector, system_util
from ...utils.exporters.conversation_exporter import export_chat_transcript, export_private_message_thread
from ...viewmodels.database_view_models import ContentListModel
from ...viewmodels.reddit_object_display import ICONS, RedditObjectStateDisplay
from ...viewmodels.transcript_delegate import TranscriptDelegate
from ...viewmodels.transcript_list_model import TranscriptEntry, TranscriptListModel
from .database_viewer import DEFAULT_ICON_SIZE


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

_KINDS = (CHAT, PRIVATE_MESSAGE)
_SEARCH_DELAY_MS = 250
_INFO_ICON_PATH = os.path.join(RESOURCES, 'images', 'info.svg')
_EXPORT_ICON_PATH = os.path.join(RESOURCES, 'images', 'download.svg')
_CONTENT_ICON_PATH = os.path.join(RESOURCES, 'images', 'image_placeholder.png')
_CONTENT_LOAD_PERCENT = 80  # how far down the media pane is scrolled before its next page is loaded


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


def downloaded_paths(contents: list[Content]) -> tuple[str, ...]:
    """
    Returns the paths of the downloaded files among a message's content.
    :param contents: The content extracted from the message's links.
    :type contents: list[Content]
    :return: The file paths, oldest first.
    :rtype: tuple[str, ...]
    """
    return tuple(content.get_full_file_path() for content in contents if content.downloaded and content.download_title)


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


class ConversationViewer(QWidget, Ui_ConversationViewer):  # pylint: disable=too-many-instance-attributes,too-many-public-methods  # a window with four panes and their slots
    """Lists imported conversations and shows their transcripts."""

    # Asks for the media linked in messages to be downloaded: chat message ids, private message ids.
    download_requested = pyqtSignal(list, list)

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
        # ContentListModel reads the content's relationships while it draws, long after a query returns, so the
        # media pane keeps a session of its own open, as the database viewer does.
        self.content_session = self.db.get_session()
        self.content_query = None
        self.content_model = ContentListModel()
        self.qsettings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, 'DownloaderForReddit',
                                   'ConversationViewer')
        self.icon_size = DEFAULT_ICON_SIZE

        self.kind_combo.currentIndexChanged.connect(self.load_conversations)
        self.nickname_line_edit.editingFinished.connect(self.save_nickname)
        self.search_line_edit.textChanged.connect(self.search_timer.start)
        self.refresh_button.clicked.connect(self.load_conversations)
        self.export_button.clicked.connect(self.export_transcript)
        self.download_content_button.clicked.connect(self.download_content)
        self.transcript_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.transcript_view.customContextMenuRequested.connect(self.transcript_context_menu)
        self.properties_button.toggled.connect(self.set_properties_visible)
        self.properties_close_button.clicked.connect(lambda: self.properties_button.setChecked(False))
        self.conversation_list.currentItemChanged.connect(self.show_selected)
        self._setup_content_pane()
        self.load_settings()
        self.load_conversations()

    def _setup_content_pane(self) -> None:
        """
        Attaches the media pane's model to its view and connects the pane's controls.
        :return: None
        :rtype: None
        """
        self.content_button.setIcon(QIcon(_CONTENT_ICON_PATH))
        self.content_view.setModel(self.content_model)
        self.content_view.verticalScrollBar().setSingleStep(20)
        self.transcript_splitter.setStretchFactor(0, 3)
        self.transcript_splitter.setStretchFactor(1, 2)
        self.transcript_view.selectionModel().selectionChanged.connect(self.show_selected_content)
        self.content_button.toggled.connect(self.set_content_visible)
        self.content_close_button.clicked.connect(lambda: self.content_button.setChecked(False))
        self.icon_slider.valueChanged.connect(self.set_icon_size)
        self.content_view.doubleClicked.connect(self.open_selected_content)
        self.content_view.customContextMenuRequested.connect(self.content_context_menu)
        self.content_view.verticalScrollBar().valueChanged.connect(self.load_more_content)

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
        self.download_content_button.setEnabled(False)
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
        self.show_selected_content()

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
        self.download_content_button.setEnabled(summary is not None)
        if summary is None:
            self.clear_transcript()
            return
        with self.db.get_scoped_session() as session:
            if summary.kind == CHAT:
                channel = session.query(ChatChannel).get(summary.key)
                messages = chat_messages(session, summary.key)
                content = message_content(session, CHAT, [message.id for message in messages])
                entries = [TranscriptEntry(person_name(message.author), message.date_posted, message.body,
                                           'thread reply' if message.thread_parent_message_id else None,
                                           participant_icon(self.icon_display, message.author), message.id,
                                           len(content.get(message.id, [])), downloaded_paths(content.get(message.id, [])))
                           for message in messages]
                title = channel.display_name if channel is not None else summary.title
            else:
                messages = private_message_thread(session, summary.key)
                content = message_content(session, PRIVATE_MESSAGE, [message.id for message in messages])
                entries = [TranscriptEntry(person_name(message.sender), message.date_sent, message.body,
                                           f'to {person_name(message.recipient)}', participant_icon(self.icon_display, message.sender),
                                           message.id, len(content.get(message.id, [])),
                                           downloaded_paths(content.get(message.id, [])))
                           for message in messages]
                title = summary.title
        self.transcript_title_label.setText(title)
        self.transcript_model.set_entries(entries)
        self.transcript_view.scrollToBottom()
        self.show_properties()
        self.show_selected_content()

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

    def download_content(self) -> None:
        """
        Asks for the media linked in the selected conversation's messages to be downloaded.  Only messages whose links
        have not been extracted yet, or failed to be, are sent.
        :return: None
        :rtype: None
        """
        summary = self.selected_summary()
        if summary is None:
            return
        with self.db.get_scoped_session() as session:
            message_ids = unextracted_message_ids(session, summary)
        if not message_ids:
            self.status_label.setText('There is no media left to download in this conversation.')
            return
        if summary.kind == CHAT:
            self.download_requested.emit(message_ids, [])
        else:
            self.download_requested.emit([], message_ids)
        self.status_label.setText(f'Downloading media from {len(message_ids):,} messages. Refresh to see the files when it finishes.')

    def transcript_context_menu(self, position: QPoint) -> None:
        """
        Shows the transcript's context menu: copy, and for a message with downloaded media, opening its files or
        their folder.
        :param position: Where the menu was asked for, in the view's viewport coordinates.
        :type position: QPoint
        :return: None
        :rtype: None
        """
        entry = self.transcript_view.indexAt(position).data(Qt.ItemDataRole.UserRole)
        paths = entry.content_paths if isinstance(entry, TranscriptEntry) else ()
        menu = QMenu(self.transcript_view)
        menu.addAction(self.copy_action)
        menu.addSeparator()
        open_action = menu.addAction('Open media' if len(paths) < 2 else f'Open media ({len(paths)} files)')
        open_action.setEnabled(bool(paths))
        open_action.triggered.connect(lambda: self.open_paths(paths))
        folder_action = menu.addAction('Open media folder')
        folder_action.setEnabled(bool(paths))
        folder_action.triggered.connect(lambda: self.open_paths(paths[:1], folder=True))
        index = self.transcript_view.indexAt(position)
        show_action = menu.addAction('Show media')
        show_action.setEnabled(isinstance(entry, TranscriptEntry) and entry.content_count > 0)
        show_action.triggered.connect(lambda: self.show_media_of(index))
        menu.exec(self.transcript_view.viewport().mapToGlobal(position))

    def show_media_of(self, index: QModelIndex) -> None:
        """
        Opens the media pane on one message: the message becomes the only one selected, so the pane shows its media.
        :param index: The message's row in the transcript.
        :type index: QModelIndex
        :return: None
        :rtype: None
        """
        if not index.isValid():
            return
        self.transcript_view.selectionModel().select(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.content_button.setChecked(True)

    def open_paths(self, paths: tuple[str, ...], folder: bool = False) -> None:
        """
        Opens files, or the folders they are in, with the system's default application.
        :param paths: The file paths.
        :type paths: tuple[str, ...]
        :param folder: Whether to open each file's folder instead of the file.
        :type folder: bool
        :return: None
        :rtype: None
        """
        for path in paths:
            target = os.path.dirname(path) if folder else path
            try:
                system_util.open_in_system(target)
            except OSError:
                logger.warning('Could not open %s', target, exc_info=True)
                self.status_label.setText(f'Could not open {target}')

    def set_content_visible(self, visible: bool) -> None:
        """
        Shows or hides the media pane, filling it with the media of the selected messages when it is shown.
        :param visible: Whether the pane is shown.
        :type visible: bool
        :return: None
        :rtype: None
        """
        self.content_frame.setVisible(visible)
        if visible:
            self.show_selected_content()

    def selected_message_ids(self) -> list[int]:
        """
        Returns the database ids of the selected messages.
        :return: The ids, in transcript order.
        :rtype: list[int]
        """
        entries = self.transcript_model.entries
        rows = sorted({index.row() for index in self.transcript_view.selectionModel().selectedIndexes()})
        return [entries[row].message_id for row in rows if 0 <= row < len(entries) and entries[row].message_id is not None]

    def show_selected_content(self) -> None:
        """
        Fills the media pane with the content of the selected messages: downloaded files as thumbnails, and media not
        downloaded (yet) with the placeholders and overlays the database viewer uses.  The pane's session is expired
        first, so files downloaded since it was last filled show.  Nothing is looked up while the pane is hidden.
        :return: None
        :rtype: None
        """
        if self.content_frame.isHidden():
            return
        summary = self.selected_summary()
        message_ids = self.selected_message_ids() if summary is not None else []
        kind = summary.kind if summary is not None else CHAT
        self.content_session.expire_all()
        self.content_query = message_content_query(self.content_session, kind, message_ids)
        self.content_model.set_data(self.content_query)
        self.content_view.scrollToTop()
        if not message_ids:
            self.content_count_label.setText('Select messages to see their media')
            return
        count = self.content_model.total_items
        files = 'file' if count == 1 else 'files'
        messages = 'message' if len(message_ids) == 1 else 'messages'
        self.content_count_label.setText(f'{count:,} {files} in {len(message_ids):,} {messages}')

    def load_more_content(self, value: int) -> None:
        """
        Loads the next page of the media pane once it is scrolled most of the way down.
        :param value: The scroll bar's position.
        :type value: int
        :return: None
        :rtype: None
        """
        maximum = self.content_view.verticalScrollBar().maximum()
        if self.content_query is not None and maximum > 0 and value >= maximum * _CONTENT_LOAD_PERCENT / 100:
            self.content_model.load_next_page(self.content_query)

    def set_icon_size(self, size: int) -> None:
        """
        Sets the size of the thumbnails in the media pane.
        :param size: The width and height of a thumbnail, in pixels.
        :type size: int
        :return: None
        :rtype: None
        """
        self.icon_size = size
        self.content_view.setIconSize(QSize(size, size))
        self.content_view.setGridSize(QSize(size + 24, size + 36))

    def selected_content(self) -> list[Content]:
        """
        Returns the content selected in the media pane.
        :return: The content, in the pane's order.
        :rtype: list[Content]
        """
        items = self.content_model.items
        rows = sorted({index.row() for index in self.content_view.selectedIndexes()})
        return [items[row] for row in rows if 0 <= row < len(items)]

    def open_selected_content(self) -> None:
        """
        Opens the first downloaded file selected in the media pane with the system's default application.
        :return: None
        :rtype: None
        """
        selected = self.selected_content()
        paths = downloaded_paths(selected)
        if paths:
            self.open_paths(paths[:1])
        elif selected:
            self.status_label.setText('That media has not been downloaded.')

    def content_context_menu(self, position: QPoint) -> None:
        """
        Shows the media pane's context menu: opening the selected file or its folder, and copying the selected files'
        paths.
        :param position: Where the menu was asked for, in the view's viewport coordinates.
        :type position: QPoint
        :return: None
        :rtype: None
        """
        paths = downloaded_paths(self.selected_content())
        menu = QMenu(self.content_view)
        open_action = menu.addAction('Open')
        open_action.setEnabled(bool(paths))
        open_action.triggered.connect(lambda: self.open_paths(paths[:1]))
        folder_action = menu.addAction('Open folder')
        folder_action.setEnabled(bool(paths))
        folder_action.triggered.connect(lambda: self.open_paths(paths[:1], folder=True))
        menu.addSeparator()
        copy_action = menu.addAction('Copy as path')
        copy_action.setEnabled(bool(paths))
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText('\n'.join(str(Path(path)) for path in paths)))
        menu.exec(self.content_view.viewport().mapToGlobal(position))

    def load_settings(self) -> None:
        """
        Restores the thumbnail size and whether the media pane is open.
        :return: None
        :rtype: None
        """
        size = self.qsettings.value('icon_size', DEFAULT_ICON_SIZE, type=int)
        self.icon_slider.blockSignals(True)
        self.icon_slider.setValue(size)
        self.icon_slider.blockSignals(False)
        self.set_icon_size(self.icon_slider.value())
        self.content_button.setChecked(self.qsettings.value('content_visible', False, type=bool))

    def save_settings(self) -> None:
        """
        Saves the thumbnail size and whether the media pane is open.
        :return: None
        :rtype: None
        """
        self.qsettings.setValue('icon_size', self.icon_size)
        self.qsettings.setValue('content_visible', self.content_button.isChecked())
        self.qsettings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:  # pylint: disable=invalid-name  # Qt override
        """
        Saves the media pane's settings when the window is closed.
        :param event: The close event.
        :type event: QCloseEvent
        :return: None
        :rtype: None
        """
        self.save_settings()
        super().closeEvent(event)
