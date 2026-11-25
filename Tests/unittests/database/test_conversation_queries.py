"""
Tests for listing and reading the conversations imported from Reddit data exports, and for rendering transcripts.


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
import tempfile
from datetime import datetime
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from DownloaderForReddit.core.const import DISABLED_OBJECT_KEY, SUBREDDIT_OBJECT, USER_OBJECT
from DownloaderForReddit.database.conversation_queries import (CHAT, PRIVATE_MESSAGE, ConversationSummary, chat_messages, chat_summaries,
                                                               conversation_properties, message_content, message_content_query,
                                                               private_thread_summaries, set_chat_nickname)
from DownloaderForReddit.database.export_models import ChatChannel, ChatMessage, PrivateMessage, person_name
from DownloaderForReddit.database.models import Content, Subreddit, User
from DownloaderForReddit.gui.database_views.conversation_viewer import participant_icon
from DownloaderForReddit.utils.exporters.conversation_exporter import format_chat_transcript
from DownloaderForReddit.viewmodels.reddit_object_display import ICONS, RedditObjectStateDisplay
from DownloaderForReddit.viewmodels.transcript_list_model import (AUTHOR_ICON_URL, TranscriptEntry, TranscriptListModel,
                                                                  format_body_html, render_entry_html)
from Tests.unittests.utils.importers.export_fixture import import_into_memory_database


class TestConversationQueries(TestCase):
    """Tests for the conversation summary and message queries."""

    def setUp(self) -> None:
        """Imports the synthetic export into a fresh in-memory database."""
        with tempfile.TemporaryDirectory() as directory:
            self.db, _ = import_into_memory_database(directory)

    def test_chat_summaries_newest_first(self) -> None:
        """Chats are listed with their counts, the most recently active first."""
        with self.db.get_scoped_session() as session:
            summaries = chat_summaries(session)
        self.assertEqual(['export_owner', 'Group chat', 'export_owner, friend_two'], [summary.title for summary in summaries])
        self.assertEqual([1, 1, 2], [summary.message_count for summary in summaries])
        self.assertTrue(all(summary.kind == CHAT for summary in summaries))

    def test_chat_search(self) -> None:
        """Searching matches message text and author names, without regard to case."""
        with self.db.get_scoped_session() as session:
            self.assertEqual(['export_owner, friend_two'], [summary.title for summary in chat_summaries(session, 'HELLO')])
            self.assertEqual(['Group chat'], [summary.title for summary in chat_summaries(session, 'friend_three')])
            self.assertEqual([], chat_summaries(session, '100%'))

    def test_like_wildcards_are_literal(self) -> None:
        """An underscore in the search text matches only an underscore."""
        with self.db.get_scoped_session() as session:
            self.assertEqual([], chat_summaries(session, 'hi_there'))

    def test_chat_messages_in_order(self) -> None:
        """A channel's messages come oldest first."""
        with self.db.get_scoped_session() as session:
            channel_id = next(summary.key for summary in chat_summaries(session) if summary.title == 'export_owner, friend_two')
            self.assertEqual(['hi there', 'hello!'], [message.body for message in chat_messages(session, channel_id)])

    def test_private_thread_summaries(self) -> None:
        """Threads are titled with their subject and everybody who took part, the export's account included."""
        with self.db.get_scoped_session() as session:
            summaries = private_thread_summaries(session)
        self.assertEqual(['Hello (export_owner, friend_one)', 'Old (deleted, export_owner)', 'Mod notice (export_owner, modsub)',
                          'Gone (ab, deleted)'],
                         [summary.title for summary in summaries])
        self.assertEqual([2, 1, 1, 1], [summary.message_count for summary in summaries])
        self.assertEqual(PRIVATE_MESSAGE, summaries[0].kind)

    def test_private_thread_search(self) -> None:
        """Searching threads matches message bodies."""
        with self.db.get_scoped_session() as session:
            self.assertEqual(['m0'], [summary.key for summary in private_thread_summaries(session, 'archived')])

    def test_message_content_query(self) -> None:
        """The query finds only the content of the given messages of the given kind, oldest first."""
        with self.db.get_scoped_session() as session:
            chat_ids = [message.id for message in session.query(ChatMessage).order_by(ChatMessage.id)]
            private_id = session.query(PrivateMessage.id).order_by(PrivateMessage.id).first()[0]
            first = Content(url='https://i.redd.it/a.jpg', chat_message_id=chat_ids[0])
            second = Content(url='https://i.redd.it/b.jpg', chat_message_id=chat_ids[0])
            other_chat = Content(url='https://i.redd.it/c.jpg', chat_message_id=chat_ids[1])
            private = Content(url='https://i.redd.it/d.jpg', private_message_id=private_id)
            session.add_all([first, second, other_chat, private])
            session.commit()
            self.assertEqual([first.id, second.id], [content.id for content in message_content_query(session, CHAT, [chat_ids[0]])])
            self.assertEqual([private.id], [content.id for content in message_content_query(session, PRIVATE_MESSAGE, [private.private_message_id])])
            self.assertEqual([], message_content_query(session, CHAT, []).all())
            grouped = message_content(session, CHAT, chat_ids)
            self.assertEqual({chat_ids[0]: [first, second], chat_ids[1]: [other_chat]}, grouped)

    def _set_nickname(self, name: str, nickname: str) -> None:
        """
        Gives an imported user a nickname.
        :param name: The user's reddit name.
        :type name: str
        :param nickname: The nickname to set.
        :type nickname: str
        """
        with self.db.get_scoped_session() as session:
            session.query(User).filter(User.name == name).one().nickname = nickname
            session.commit()

    def test_person_name(self) -> None:
        """A person is shown under a non-blank nickname, otherwise the reddit name, and a missing one as deleted."""
        self._set_nickname('friend_two', 'Bestie')
        self._set_nickname('friend_one', '   ')
        with self.db.get_scoped_session() as session:
            self.assertEqual('Bestie', person_name(session.query(User).filter(User.name == 'friend_two').one()))
            self.assertEqual('friend_one', person_name(session.query(User).filter(User.name == 'friend_one').one()))
        self.assertEqual('[deleted]', person_name(None))

    def test_chat_transcript_uses_nicknames(self) -> None:
        """The exported chat transcript names authors by nickname, without a u/ prefix."""
        self._set_nickname('friend_two', 'Bestie')
        with self.db.get_scoped_session() as session:
            channel_id = next(summary.key for summary in chat_summaries(session) if summary.title == 'Bestie, export_owner')
            text = format_chat_transcript(session.query(ChatChannel).get(channel_id), chat_messages(session, channel_id))
        self.assertIn('] Bestie:', text)
        self.assertIn('] export_owner:', text)
        self.assertNotIn('u/', text)

    def test_chat_titles_and_search_use_nickname(self) -> None:
        """A direct chat is titled with its participants' nicknames and can be found by them."""
        self._set_nickname('friend_two', 'Bestie')
        with self.db.get_scoped_session() as session:
            self.assertIn('Bestie, export_owner', [summary.title for summary in chat_summaries(session)])
            self.assertEqual(['Bestie, export_owner'], [summary.title for summary in chat_summaries(session, 'besT')])

    def test_private_thread_titles_and_search_use_nickname(self) -> None:
        """A thread is titled with the participant's nickname and can be found by it."""
        self._set_nickname('friend_one', 'Pal')
        with self.db.get_scoped_session() as session:
            self.assertEqual('Hello (export_owner, Pal)', private_thread_summaries(session)[0].title)
            self.assertEqual(['Hello (export_owner, Pal)'], [summary.title for summary in private_thread_summaries(session, 'pal')])

    def _properties(self, summary: ConversationSummary) -> tuple[dict[str, str], list[tuple[str, Optional[str]]]]:
        """
        Reads a conversation's properties.
        :param summary: The conversation.
        :type summary: ConversationSummary
        :return: The named rows' values by name (participant rows excluded), and each participant row's value with the
            object type of its reddit object (None for an unlinked participant).
        :rtype: tuple[dict[str, str], list[tuple[str, Optional[str]]]]
        """
        with self.db.get_scoped_session() as session:
            rows = conversation_properties(session, summary)
            participants = [(row.value, row.participant.object_type if row.participant is not None else None)
                            for row in rows if row.is_participant]
            named = {row.name: row.value for row in rows if not row.is_participant}
        return named, participants

    def _chat(self, title: str) -> ConversationSummary:
        """
        Finds a listed chat by title.
        :param title: The chat's title.
        :type title: str
        :return: The chat's summary.
        :rtype: ConversationSummary
        """
        with self.db.get_scoped_session() as session:
            return next(summary for summary in chat_summaries(session) if summary.title == title)

    def _thread(self, subject: str) -> ConversationSummary:
        """
        Finds a listed private message thread by the start of its title.
        :param subject: The thread's subject.
        :type subject: str
        :return: The thread's summary.
        :rtype: ConversationSummary
        """
        with self.db.get_scoped_session() as session:
            return next(summary for summary in private_thread_summaries(session) if summary.title.startswith(subject))

    def test_chat_properties(self) -> None:
        """A chat's properties name it, list each participant on its own row with its message count, and list the import."""
        named, participants = self._properties(self._chat('export_owner, friend_two'))
        self.assertEqual('export_owner, friend_two', named['Name'])
        self.assertEqual('—', named['Nickname'])
        self.assertEqual('sendbird_group_channel_1', named['Channel URL'])
        self.assertEqual('direct', named['Type'])
        self.assertEqual([('export_owner (1 message)', USER_OBJECT), ('friend_two (1 message)', USER_OBJECT)], participants)
        self.assertEqual('2', named['Messages'])
        self.assertEqual('2024-04-01 10:00', named['First message'])
        self.assertEqual('2024-04-01 10:01', named['Last message'])
        self.assertTrue(named['Imported from'].startswith('export.zip ('))

    def test_participant_rows_are_labelled_once(self) -> None:
        """Only the first participant row carries the 'Participants' label."""
        with self.db.get_scoped_session() as session:
            rows = conversation_properties(session, self._chat('export_owner, friend_two'))
            self.assertEqual(['Participants', ''], [row.name for row in rows if row.is_participant])

    def test_private_thread_properties(self) -> None:
        """A thread's properties list its subject and every participant, with the messages each sent."""
        named, participants = self._properties(self._thread('Hello'))
        self.assertEqual('Hello', named['Subject'])
        self.assertEqual([('export_owner (1 message sent)', USER_OBJECT), ('friend_one (1 message sent)', USER_OBJECT)], participants)
        self.assertEqual('2', named['Messages'])

    def test_modmail_participant_is_a_subreddit(self) -> None:
        """A modmail sender is a subreddit participant, listed beside the user it wrote to."""
        _, participants = self._properties(self._thread('Mod notice'))
        self.assertEqual([('export_owner (0 messages sent)', USER_OBJECT), ('modsub (1 message sent)', SUBREDDIT_OBJECT)],
                         participants)

    def test_thread_properties_include_recipients_who_never_sent(self) -> None:
        """A participant that only received messages is still listed, with no messages sent."""
        _, participants = self._properties(self._thread('Gone'))
        self.assertEqual(['ab (0 messages sent)', 'deleted (1 message sent)'], [value for value, _ in participants])


class TestChatNicknames(TestCase):
    """Tests for the nicknames the user gives chat channels."""

    def setUp(self) -> None:
        """Imports the synthetic export into a fresh in-memory database."""
        with tempfile.TemporaryDirectory() as directory:
            self.db, _ = import_into_memory_database(directory)
        with self.db.get_scoped_session() as session:
            self.channel_id = session.query(ChatChannel).filter(ChatChannel.channel_url == 'sendbird_group_channel_1').one().id

    def _set(self, nickname: str) -> Optional[str]:
        """
        Sets the direct chat's nickname.
        :param nickname: The nickname typed by the user.
        :type nickname: str
        :return: The chat's display name afterwards.
        :rtype: Optional[str]
        """
        with self.db.get_scoped_session() as session:
            return set_chat_nickname(session, self.channel_id, nickname)

    def test_nickname_names_the_chat(self) -> None:
        """A nickname is stored trimmed and names the chat in the list, the properties and the exported header."""
        self.assertEqual('Old friends', self._set('  Old friends '))
        with self.db.get_scoped_session() as session:
            channel = session.query(ChatChannel).get(self.channel_id)
            self.assertEqual('Old friends', channel.nickname)
            self.assertIn('Old friends', [summary.title for summary in chat_summaries(session)])
            summary = next(summary for summary in chat_summaries(session) if summary.key == self.channel_id)
            named = {row.name: row.value for row in conversation_properties(session, summary)}
            self.assertEqual('Old friends', named['Nickname'])
            self.assertTrue(format_chat_transcript(channel, chat_messages(session, self.channel_id)).startswith('Chat: Old friends'))

    def test_nickname_overrides_channel_name(self) -> None:
        """A nickname is shown in place of the name Reddit gave the channel."""
        with self.db.get_scoped_session() as session:
            named = session.query(ChatChannel).filter(ChatChannel.channel_url == 'sendbird_group_channel_2').one()
            self.assertEqual('Mine', set_chat_nickname(session, named.id, 'Mine'))

    def test_blank_nickname_reverts(self) -> None:
        """Clearing the nickname stores None and names the chat after its participants again."""
        self._set('Old friends')
        self.assertEqual('export_owner, friend_two', self._set('   '))
        with self.db.get_scoped_session() as session:
            self.assertIsNone(session.query(ChatChannel).get(self.channel_id).nickname)

    def test_search_matches_nickname(self) -> None:
        """A chat can be found by its nickname, without regard to case."""
        self._set('Old friends')
        with self.db.get_scoped_session() as session:
            self.assertEqual(['Old friends'], [summary.title for summary in chat_summaries(session, 'OLD FR')])

    def test_unknown_channel(self) -> None:
        """Setting the nickname of a channel that does not exist changes nothing."""
        with self.db.get_scoped_session() as session:
            self.assertIsNone(set_chat_nickname(session, 999, 'x'))


class TestTranscriptRendering(TestCase):
    """Tests for the transcript rows."""

    def test_body_is_escaped_and_linked(self) -> None:
        """Markup in a body is escaped, links become anchors and line breaks are kept."""
        rendered = format_body_html('<b>hi</b>\nsee https://example.com/x')
        self.assertIn('&lt;b&gt;hi&lt;/b&gt;<br/>', rendered)
        self.assertIn('<a href="https://example.com/x">', rendered)

    def test_empty_body(self) -> None:
        """An empty body is shown as a placeholder."""
        self.assertEqual('<i>[no text]</i>', format_body_html(None))

    def test_render_entry(self) -> None:
        """A row shows its author, date and note, with the author escaped and a missing author shown as unknown."""
        rendered = render_entry_html(TranscriptEntry('<someone>', datetime(2024, 1, 2, 3, 4), 'hello', note='thread reply'))
        self.assertTrue(rendered.startswith('<b>&lt;someone&gt;</b> <span style="color:gray">2024-01-02 03:04</span> <i>thread reply</i><br/>'))
        self.assertIn('<b>[unknown]</b>', render_entry_html(TranscriptEntry(None, None, 'anon')))

    def test_model_rows_and_copy_text(self) -> None:
        """The model has one row per message and copies the chosen rows in transcript order."""
        model = TranscriptListModel()
        model.set_entries([TranscriptEntry('a', datetime(2024, 1, 2, 3, 4), 'first'),
                           TranscriptEntry('b', None, 'second', note='to a')])
        self.assertEqual(2, model.rowCount())
        self.assertEqual(render_entry_html(model.entries[1]), model.data(model.index(1)))
        self.assertEqual('a 2024-01-02 03:04\nfirst\n\nb (to a)\nsecond', model.plain_text([1, 0]))
        model.clear()
        self.assertEqual(0, model.rowCount())

    def test_author_icon_only_when_given(self) -> None:
        """The author's icon is put in front of the name only when the entry has one."""
        self.assertNotIn('<img', render_entry_html(TranscriptEntry('a', None, 'x')))
        rendered = render_entry_html(TranscriptEntry('a', None, 'x', icon=QIcon()))
        self.assertTrue(rendered.startswith(f'<img src="{AUTHOR_ICON_URL}"'))
        self.assertLess(rendered.index('<img'), rendered.index('<b>a</b>'))


class TestParticipantIcons(TestCase):
    """Tests for the icons shown in front of conversation participants, which are users or subreddits."""

    @classmethod
    def setUpClass(cls) -> None:
        """Creates the QApplication icons need, without opening a window."""
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        """Imports the synthetic export into a fresh in-memory database and shows every state as an icon."""
        with tempfile.TemporaryDirectory() as directory:
            self.db, _ = import_into_memory_database(directory)
        self.display = RedditObjectStateDisplay(MagicMock(iconize_reddit_objects=True))

    def test_user_and_subreddit_icons(self) -> None:
        """A user gets a user icon and a modmail subreddit gets a forum icon, both chosen by state."""
        with self.db.get_scoped_session() as session:
            user = session.query(User).filter(User.name == 'export_owner').one()
            subreddit = session.query(Subreddit).filter(Subreddit.name == 'modsub').one()
            subreddit.download_enabled = False
            self.assertIs(self.display.icon(user), participant_icon(self.display, user))
            self.assertIn(participant_icon(self.display, user), ICONS[USER_OBJECT].values())
            self.assertIs(ICONS[SUBREDDIT_OBJECT][DISABLED_OBJECT_KEY], participant_icon(self.display, subreddit))

    def test_missing_participant_gets_blank_icon(self) -> None:
        """A message that could not be linked to a participant gets the blank icon, so names stay aligned."""
        self.assertIs(self.display.blank(), participant_icon(self.display, None))
