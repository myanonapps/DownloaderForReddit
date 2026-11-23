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

import tempfile
from datetime import datetime
from unittest import TestCase

from DownloaderForReddit.database.conversation_queries import (CHAT, PRIVATE_MESSAGE, chat_messages, chat_summaries,
                                                               private_thread_summaries)
from DownloaderForReddit.gui.database_views.conversation_viewer import (TranscriptEntry, format_body_html,
                                                                        render_transcript_html)
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
        self.assertEqual(['Chat abcdefghij', 'Group chat', 'friend_two'], [summary.title for summary in summaries])
        self.assertEqual([1, 1, 2], [summary.message_count for summary in summaries])
        self.assertTrue(all(summary.kind == CHAT for summary in summaries))

    def test_chat_search(self) -> None:
        """Searching matches message text and author names, without regard to case."""
        with self.db.get_scoped_session() as session:
            self.assertEqual(['friend_two'], [summary.title for summary in chat_summaries(session, 'HELLO')])
            self.assertEqual(['Group chat'], [summary.title for summary in chat_summaries(session, 'friend_three')])
            self.assertEqual([], chat_summaries(session, '100%'))

    def test_like_wildcards_are_literal(self) -> None:
        """An underscore in the search text matches only an underscore."""
        with self.db.get_scoped_session() as session:
            self.assertEqual([], chat_summaries(session, 'hi_there'))

    def test_chat_messages_in_order(self) -> None:
        """A channel's messages come oldest first."""
        with self.db.get_scoped_session() as session:
            channel_id = next(summary.key for summary in chat_summaries(session) if summary.title == 'friend_two')
            self.assertEqual(['hi there', 'hello!'], [message.body for message in chat_messages(session, channel_id)])

    def test_private_thread_summaries(self) -> None:
        """Threads are titled with their subject and the other participants."""
        with self.db.get_scoped_session() as session:
            summaries = private_thread_summaries(session)
        self.assertEqual(['Hello (friend_one)', 'Old ([deleted])'], [summary.title for summary in summaries])
        self.assertEqual([2, 1], [summary.message_count for summary in summaries])
        self.assertEqual(PRIVATE_MESSAGE, summaries[0].kind)

    def test_private_thread_search(self) -> None:
        """Searching threads matches message bodies."""
        with self.db.get_scoped_session() as session:
            self.assertEqual(['m0'], [summary.key for summary in private_thread_summaries(session, 'archived')])


class TestTranscriptRendering(TestCase):
    """Tests for the transcript HTML."""

    def test_body_is_escaped_and_linked(self) -> None:
        """Markup in a body is escaped, links become anchors and line breaks are kept."""
        rendered = format_body_html('<b>hi</b>\nsee https://example.com/x')
        self.assertIn('&lt;b&gt;hi&lt;/b&gt;<br/>', rendered)
        self.assertIn('<a href="https://example.com/x">', rendered)

    def test_empty_body(self) -> None:
        """An empty body is shown as a placeholder."""
        self.assertEqual('<i>[no text]</i>', format_body_html(None))

    def test_render_transcript(self) -> None:
        """Each entry shows its author, date and note, and the title is escaped."""
        rendered = render_transcript_html('<chat>', [
            TranscriptEntry('someone', datetime(2024, 1, 2, 3, 4), 'hello', note='thread reply'),
            TranscriptEntry(None, None, 'anon'),
        ])
        self.assertIn('<h3>&lt;chat&gt;</h3>', rendered)
        self.assertIn('<b>someone</b> <span style="color:gray">2024-01-02 03:04</span> <i>thread reply</i>', rendered)
        self.assertIn('<b>[unknown]</b>', rendered)
