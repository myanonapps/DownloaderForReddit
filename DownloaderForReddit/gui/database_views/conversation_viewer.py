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

A chat's transcript holds only its top level messages.  A message that started a thread shows how many replies it has
and a link that opens the thread pane beside the transcript, where the thread's first message and all of its replies
are listed together, replies to replies indented further.  Selecting messages in the thread pane shows their media.

Chat reactions are not shown as messages: the reactions a message got are shown as small images under it, and the
tooltip names who reacted with what.  A message's context menu can mark the image it consists of as a reaction, or a
reaction as not being one, in every chat at once.  Reaction images not stored yet are fetched in the background.


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

from PyQt6.QtCore import QItemSelectionModel, QModelIndex, QPoint, QSettings, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PyQt6.QtWidgets import QApplication, QFileDialog, QListView, QListWidgetItem, QMenu, QTableWidgetItem, QWidget

from ...core.const import RESOURCES
from ...core.reaction_fetcher import ReactionFetcher, start_fetch_thread
from ...database.chat_threads import ORPHAN_NOTE, ORPHAN_REACTION_NOTE, ChatThreads, ThreadRow, build_chat_threads
from ...database.conversation_queries import (CHAT, PRIVATE_MESSAGE, ConversationSummary, chat_messages, chat_summaries,
                                              conversation_properties, message_content, message_content_query,
                                              private_message_thread,
                                              private_thread_summaries, set_chat_nickname, unextracted_message_ids)
from ...database.export_models import ChatChannel, ChatMessage, ChatReaction, person_name
from ...database.models import Content, RedditObject
from ...guiresources.database_views.conversation_viewer_auto import Ui_ConversationViewer
from ...utils import injector, system_util
from ...utils.chat_reactions import set_reaction_enabled, single_url
from ...utils.exporters.conversation_exporter import export_chat_transcript, export_private_message_thread
from ...viewmodels.database_view_models import ContentListModel
from ...viewmodels.reddit_object_display import ICONS, RedditObjectStateDisplay
from ...viewmodels.transcript_delegate import TranscriptDelegate
from ...viewmodels.transcript_list_model import DATE_FORMAT, ReactionBadge, TranscriptEntry, TranscriptListModel
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


def _entry_badges(entry: TranscriptEntry) -> tuple[ReactionBadge, ...]:
    """
    Returns every reaction a transcript row shows: those the message got, and the message's own when it is a reaction.
    :param entry: The row.
    :type entry: TranscriptEntry
    :return: The badges.
    :rtype: tuple[ReactionBadge, ...]
    """
    return entry.reactions + ((entry.reaction,) if entry.reaction is not None else ())


def downloaded_paths(contents: list[Content]) -> tuple[str, ...]:
    """
    Returns the paths of the downloaded files among a message's content.
    :param contents: The content extracted from the message's links.
    :type contents: list[Content]
    :return: The file paths, oldest first.
    :rtype: tuple[str, ...]
    """
    return tuple(content.get_full_file_path() for content in contents if content.downloaded and content.download_title)


def reaction_badge(reaction: ChatReaction, messages: tuple[ChatMessage, ...] = ()) -> ReactionBadge:
    """
    Describes a reaction for display on a message.
    :param reaction: The reaction.
    :type reaction: ChatReaction
    :param messages: The reaction messages a message got with this reaction; none for a reaction shown on its own.
    :type messages: tuple[ChatMessage, ...]
    :return: The badge, naming who reacted and when.
    :rtype: ReactionBadge
    """
    reactors = tuple(f'{person_name(message.author)} {message.date_posted.strftime(DATE_FORMAT)}' if message.date_posted is not None
                     else person_name(message.author) for message in messages)
    return ReactionBadge(reaction.id, reaction.display_name, reaction.url, reaction.file_path if reaction.has_image else None, reactors)


def reaction_badges(reactions: list[ChatMessage]) -> tuple[ReactionBadge, ...]:
    """
    Groups the reactions a message got by reaction, in the order each reaction was first used.
    :param reactions: The reaction messages, oldest first.
    :type reactions: list[ChatMessage]
    :return: One badge per reaction.
    :rtype: tuple[ReactionBadge, ...]
    """
    groups: dict[int, list[ChatMessage]] = {}
    for message in reactions:
        groups.setdefault(message.reaction_id, []).append(message)
    return tuple(reaction_badge(messages[0].reaction, tuple(messages)) for messages in groups.values())


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
        self.splitter.setSizes([300, 700, 420, 280])
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(_SEARCH_DELAY_MS)
        self.search_timer.timeout.connect(self.load_conversations)

        self.transcript_model = TranscriptListModel(self)
        self.transcript_view.setModel(self.transcript_model)
        self.transcript_delegate = TranscriptDelegate(self.transcript_view)
        self.transcript_view.setItemDelegate(self.transcript_delegate)
        self.copy_action = self._copy_action(self.transcript_view)
        self.thread_model = TranscriptListModel(self)
        self.thread_delegate = TranscriptDelegate(self.thread_view)
        self.thread_copy_action = self._copy_action(self.thread_view)
        # The rows of each thread of the chat shown, keyed by the message id of the thread's first message.
        self.thread_entries: dict[str, list[TranscriptEntry]] = {}
        # The view whose selected messages the media pane shows.
        self.media_source_view: QListView = self.transcript_view
        # The message id of the first message of the thread the thread pane shows.
        self.open_thread_key: Optional[str] = None
        self.reaction_thread: Optional[QThread] = None
        self.reaction_fetcher: Optional[ReactionFetcher] = None
        self.reaction_fetch_tried = False
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
        self.transcript_view.customContextMenuRequested.connect(lambda position: self.transcript_context_menu(self.transcript_view, position))
        self.properties_button.toggled.connect(self.set_properties_visible)
        self.properties_close_button.clicked.connect(lambda: self.properties_button.setChecked(False))
        self.conversation_list.currentItemChanged.connect(self.show_selected)
        self._setup_thread_pane()
        self._setup_content_pane()
        self.load_settings()
        self.load_conversations()

    def _setup_thread_pane(self) -> None:
        """
        Attaches the thread pane's model and delegate to its view and connects the thread links of both views.
        :return: None
        :rtype: None
        """
        self.thread_view.setModel(self.thread_model)
        self.thread_view.setItemDelegate(self.thread_delegate)
        self.thread_view.customContextMenuRequested.connect(lambda position: self.transcript_context_menu(self.thread_view, position))
        self.transcript_delegate.thread_link_clicked.connect(self.show_thread)
        self.thread_delegate.thread_link_clicked.connect(self.show_thread)
        self.thread_close_button.clicked.connect(self.close_thread)

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
        self.transcript_view.selectionModel().selectionChanged.connect(lambda: self.use_selection_of(self.transcript_view))
        self.thread_view.selectionModel().selectionChanged.connect(lambda: self.use_selection_of(self.thread_view))
        self.content_button.toggled.connect(self.set_content_visible)
        self.content_close_button.clicked.connect(lambda: self.content_button.setChecked(False))
        self.icon_slider.valueChanged.connect(self.set_icon_size)
        self.content_view.doubleClicked.connect(self.open_selected_content)
        self.content_view.customContextMenuRequested.connect(self.content_context_menu)
        self.content_view.verticalScrollBar().valueChanged.connect(self.load_more_content)

    def _copy_action(self, view: QListView) -> QAction:
        """
        Creates the action that copies the messages selected in a transcript view, bound to the copy shortcut while
        the view has focus.
        :param view: The transcript view or the thread view.
        :type view: QListView
        :return: The action, already added to the view.
        :rtype: QAction
        """
        action = QAction('Copy', view)
        action.setShortcut(QKeySequence.StandardKey.Copy)
        action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        action.triggered.connect(lambda: self.copy_selected_messages(view))
        view.addAction(action)
        return action

    def _model_of(self, view: QListView) -> TranscriptListModel:
        """
        Returns the model a transcript view shows.
        :param view: The transcript view or the thread view.
        :type view: QListView
        :return: The view's model.
        :rtype: TranscriptListModel
        """
        return self.thread_model if view is self.thread_view else self.transcript_model

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
        Empties the transcript, its title, the thread pane and the properties pane.
        :return: None
        :rtype: None
        """
        self.close_thread(refresh_media=False)
        self.thread_entries = {}
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
        self.close_thread(refresh_media=False)
        self.thread_entries = {}
        missing_images = False
        with self.db.get_scoped_session() as session:
            if summary.kind == CHAT:
                channel = session.query(ChatChannel).get(summary.key)
                messages = chat_messages(session, summary.key)
                content = message_content(session, CHAT, [message.id for message in messages])
                threads = build_chat_threads(messages)
                entries = [self._chat_entry(message, content, threads) for message in threads.timeline]
                self.thread_entries = {key: [self._chat_entry(row.message, content, threads, row) for row in rows]
                                       for key, rows in threads.threads.items()}
                shown = [*entries, *(entry for rows in self.thread_entries.values() for entry in rows)]
                missing_images = any(badge.image_path is None for entry in shown for badge in _entry_badges(entry))
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
        if missing_images:
            self.fetch_reaction_images()

    def refresh_conversation(self) -> None:
        """
        Shows the selected conversation again, after its messages changed, keeping the thread pane on the thread it
        showed.
        :return: None
        :rtype: None
        """
        key = self.open_thread_key
        position = self.transcript_view.verticalScrollBar().value()
        self.show_selected()
        self.transcript_view.verticalScrollBar().setValue(position)
        if key is not None:
            self.show_thread(key)

    def fetch_reaction_images(self) -> None:
        """
        Fetches the reaction images not stored yet, in the background, once per window; the conversation is shown again
        when any image was stored.
        :return: None
        :rtype: None
        """
        if self.reaction_fetch_tried or self.reaction_thread is not None:
            return
        self.reaction_fetch_tried = True
        self.reaction_thread, self.reaction_fetcher = start_fetch_thread(self.reaction_images_fetched, self.reaction_fetch_done)

    def reaction_images_fetched(self, fetched: int, failed: int) -> None:
        """
        Shows the reaction images just stored.
        :param fetched: The number of images stored.
        :type fetched: int
        :param failed: The number of images that could not be fetched.
        :type failed: int
        :return: None
        :rtype: None
        """
        logger.debug('Reaction images fetched: %d, failed: %d', fetched, failed)
        if fetched:
            self.transcript_delegate.clear_reaction_images()
            self.thread_delegate.clear_reaction_images()
            self.refresh_conversation()

    def reaction_fetch_done(self) -> None:
        """
        Releases the reaction fetch thread once it has finished.
        :return: None
        :rtype: None
        """
        if self.reaction_thread is not None:
            self.reaction_thread.wait()
        self.reaction_thread = None
        self.reaction_fetcher = None

    def _chat_entry(self, message: ChatMessage, content: dict[int, list[Content]], threads: ChatThreads,
                    row: Optional[ThreadRow] = None) -> TranscriptEntry:
        """
        Builds the transcript row of a chat message.  In the transcript a message that started a thread carries the
        thread's key, reply count and last reply date, so its row links to the thread; in the thread pane a reply is
        indented by its depth, and a reply to a reply names whom it answers.
        :param message: The message.
        :type message: ChatMessage
        :param content: The content of the chat's messages, keyed by message id.
        :type content: dict[int, list[Content]]
        :param threads: The chat's messages arranged into threads.
        :type threads: ChatThreads
        :param row: The message's place in a thread, when the row is for the thread pane; None for the transcript.
        :type row: Optional[ThreadRow]
        :return: The row.
        :rtype: TranscriptEntry
        """
        contents = content.get(message.id, [])
        depth = row.depth if row is not None else 0
        note = None
        if depth == 0 and threads.is_orphan(message):
            note = ORPHAN_REACTION_NOTE if message.is_reaction else ORPHAN_NOTE
        elif row is not None and row.depth >= 2:
            note = f'replying to {row.parent_author}'
        reply_count = threads.reply_count(message.message_id) if row is None else 0
        return TranscriptEntry(person_name(message.author), message.date_posted, message.body, note,
                               participant_icon(self.icon_display, message.author), message.id, len(contents),
                               downloaded_paths(contents), depth=depth,
                               thread_key=message.message_id if reply_count else None, reply_count=reply_count,
                               last_reply_date=threads.last_reply_date(message.message_id) if reply_count else None,
                               reactions=reaction_badges(threads.reactions_to(message)),
                               reaction=reaction_badge(message.reaction) if message.is_reaction else None)

    def show_thread(self, key: str) -> None:
        """
        Opens the thread pane on one thread of the chat shown: the thread's first message, then its replies.
        :param key: The message id of the thread's first message.
        :type key: str
        :return: None
        :rtype: None
        """
        entries = self.thread_entries.get(key)
        if not entries:
            logger.debug('No thread %s in the chat shown', key)
            return
        root = entries[0]
        date = root.date.strftime(DATE_FORMAT) if root.date is not None else ''
        self.open_thread_key = key
        self.thread_title_label.setText(f'Thread · {root.author} {date}'.rstrip())
        self.thread_model.set_entries(entries)
        self.thread_frame.setVisible(True)
        self.thread_view.scrollToTop()
        if self.media_source_view is self.thread_view:
            self.show_selected_content()

    def close_thread(self, refresh_media: bool = True) -> None:
        """
        Hides and empties the thread pane.  When the media pane showed the thread's messages, it goes back to the
        messages selected in the transcript.
        :param refresh_media: Whether to refill the media pane when it showed the thread's messages.
        :type refresh_media: bool
        :return: None
        :rtype: None
        """
        self.open_thread_key = None
        self.thread_frame.setVisible(False)
        self.thread_model.clear()
        self.thread_title_label.clear()
        if self.media_source_view is self.thread_view:
            self.media_source_view = self.transcript_view
            if refresh_media:
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

    def copy_selected_messages(self, view: QListView) -> None:
        """
        Copies the messages selected in a transcript view to the clipboard as plain text.
        :param view: The transcript view or the thread view.
        :type view: QListView
        :return: None
        :rtype: None
        """
        rows = [index.row() for index in view.selectionModel().selectedIndexes()]
        if rows:
            QApplication.clipboard().setText(self._model_of(view).plain_text(rows))

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

    def transcript_context_menu(self, view: QListView, position: QPoint) -> None:
        """
        Shows the context menu of the transcript or the thread pane: copy, opening the thread a message started,
        marking a chat message's image as a reaction or a reaction as not being one, and for a message with downloaded
        media, opening its files or their folder.
        :param view: The transcript view or the thread view.
        :type view: QListView
        :param position: Where the menu was asked for, in the view's viewport coordinates.
        :type position: QPoint
        :return: None
        :rtype: None
        """
        index = view.indexAt(position)
        entry = index.data(Qt.ItemDataRole.UserRole)
        paths = entry.content_paths if isinstance(entry, TranscriptEntry) else ()
        menu = QMenu(view)
        menu.addAction(self.thread_copy_action if view is self.thread_view else self.copy_action)
        if isinstance(entry, TranscriptEntry) and entry.thread_key is not None:
            thread_key = entry.thread_key
            thread_action = menu.addAction('Open thread')
            thread_action.triggered.connect(lambda: self.show_thread(thread_key))
        if isinstance(entry, TranscriptEntry):
            self._add_reaction_actions(menu, entry)
        menu.addSeparator()
        open_action = menu.addAction('Open media' if len(paths) < 2 else f'Open media ({len(paths)} files)')
        open_action.setEnabled(bool(paths))
        open_action.triggered.connect(lambda: self.open_paths(paths))
        folder_action = menu.addAction('Open media folder')
        folder_action.setEnabled(bool(paths))
        folder_action.triggered.connect(lambda: self.open_paths(paths[:1], folder=True))
        show_action = menu.addAction('Show media')
        show_action.setEnabled(isinstance(entry, TranscriptEntry) and entry.content_count > 0)
        show_action.triggered.connect(lambda: self.show_media_of(view, index))
        menu.exec(view.viewport().mapToGlobal(position))

    def _add_reaction_actions(self, menu: QMenu, entry: TranscriptEntry) -> None:
        """
        Adds the actions that change what counts as a reaction to a chat message's context menu: marking the image a
        message consists of as a reaction, and marking a reaction (the message's own, or one it got) as not being one.
        :param menu: The context menu.
        :type menu: QMenu
        :param entry: The message the menu is for.
        :type entry: TranscriptEntry
        :return: None
        :rtype: None
        """
        summary = self.selected_summary()
        if summary is None or summary.kind != CHAT:
            return
        if entry.reaction is not None:
            url = entry.reaction.url
            menu.addAction('Not a reaction (all chats)').triggered.connect(lambda: self.set_reaction(url, False))
            return
        url = single_url(entry.body)
        if url is not None:
            menu.addAction('Treat this image as a reaction (all chats)').triggered.connect(lambda: self.set_reaction(url, True))
        if entry.reactions:
            submenu = menu.addMenu('Not a reaction (all chats)')
            for badge in entry.reactions:
                submenu.addAction(badge.label).triggered.connect(lambda _checked=False, target=badge.url: self.set_reaction(target, False))

    def set_reaction(self, url: str, enabled: bool) -> None:
        """
        Marks an image url as a reaction, or as not being one, in every chat, and shows the conversation again.
        :param url: The image url.
        :type url: str
        :param enabled: True to treat the url as a reaction, False to treat it as ordinary media.
        :type enabled: bool
        :return: None
        :rtype: None
        """
        with self.db.get_scoped_session() as session:
            set_reaction_enabled(session, url, enabled)
        self.status_label.setText(f'{url} is {"now" if enabled else "no longer"} treated as a reaction in every chat')
        self.reaction_fetch_tried = False
        self.refresh_conversation()

    def show_media_of(self, view: QListView, index: QModelIndex) -> None:
        """
        Opens the media pane on one message: the message becomes the only one selected, so the pane shows its media.
        :param view: The transcript view or the thread view the message is in.
        :type view: QListView
        :param index: The message's row in the view.
        :type index: QModelIndex
        :return: None
        :rtype: None
        """
        if not index.isValid():
            return
        view.selectionModel().select(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.media_source_view = view
        self.content_button.setChecked(True)
        self.show_selected_content()

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

    def use_selection_of(self, view: QListView) -> None:
        """
        Makes the media pane show the messages selected in a view, after its selection changed.
        :param view: The transcript view or the thread view.
        :type view: QListView
        :return: None
        :rtype: None
        """
        self.media_source_view = view
        self.show_selected_content()

    def selected_message_ids(self) -> list[int]:
        """
        Returns the database ids of the messages selected in the view the media pane follows: the transcript, or the
        thread pane once messages were selected there.
        :return: The ids, in the view's order.
        :rtype: list[int]
        """
        view = self.media_source_view
        entries = self._model_of(view).entries
        rows = sorted({index.row() for index in view.selectionModel().selectedIndexes()})
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
        Saves the media pane's settings, and stops fetching reaction images, when the window is closed.
        :param event: The close event.
        :type event: QCloseEvent
        :return: None
        :rtype: None
        """
        self.save_settings()
        if self.reaction_fetcher is not None:
            self.reaction_fetcher.stop()
        super().closeEvent(event)
