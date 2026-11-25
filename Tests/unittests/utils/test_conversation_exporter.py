"""
Tests for exporting imported chats and private message threads as text transcripts.


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
from unittest import TestCase

from DownloaderForReddit.database.chat_threads import ORPHAN_NOTE, ORPHAN_REACTION_NOTE
from DownloaderForReddit.database.export_models import ChatChannel, ChatReaction
from DownloaderForReddit.utils.exporters.conversation_exporter import export_chat_transcript, export_private_message_thread, format_chat_transcript
from Tests.unittests.database.test_chat_threads import chat_message
from Tests.unittests.utils.importers.export_fixture import ACCOUNT, import_into_memory_database


class TestConversationExporter(TestCase):
    """Tests for the transcript exports."""

    def setUp(self) -> None:
        """Imports the synthetic export into a fresh in-memory database, keeping a directory for the exported files."""
        self.temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with  # cleaned up in tearDown
        self.db, _ = import_into_memory_database(self.temp_dir.name)

    def tearDown(self) -> None:
        """Removes the temporary directory."""
        self.temp_dir.cleanup()

    def read(self, path: str) -> str:
        """
        Reads an exported file.
        :param path: The file path.
        :type path: str
        :return: The file's text.
        :rtype: str
        """
        with open(path, encoding='utf-8') as file:
            return file.read()

    def test_chat_transcript(self) -> None:
        """A chat transcript lists the channel and its messages in order."""
        path = os.path.join(self.temp_dir.name, 'chat.txt')
        with self.db.get_scoped_session() as session:
            channel = session.query(ChatChannel).filter(ChatChannel.channel_url == 'sendbird_group_channel_1').one()
            count = export_chat_transcript(session, channel.id, path)
        text = self.read(path)
        self.assertEqual(2, count)
        self.assertTrue(text.startswith(f'Chat: {ACCOUNT}, friend_two'))
        self.assertLess(text.index('hi there'), text.index('hello!'))
        self.assertIn(f'[2024-04-01 10:00:00 UTC] {ACCOUNT}:', text)

    def test_chat_threads_follow_their_root(self) -> None:
        """Thread replies follow the message that started the thread, indented by depth, with notes in the headers."""
        messages = [chat_message('root', minute=0, author='alice'), chat_message('other', minute=1, author='bob'),
                    chat_message('r1', 'root', minute=2, author='bob'), chat_message('r1a', 'r1', minute=3, author='carol'),
                    chat_message('orphan', 'gone', minute=4, author='dave')]
        text = format_chat_transcript(ChatChannel(channel_name='Room'), messages)
        expected = ('Chat: Room\n\n'
                    '[2024-01-01 00:00:00 UTC] alice (2 replies):\nroot\n\n'
                    '    [2024-01-01 00:02:00 UTC] bob:\n    r1\n\n'
                    '        [2024-01-01 00:03:00 UTC] carol (replying to bob):\n        r1a\n\n'
                    '[2024-01-01 00:01:00 UTC] bob:\nother\n\n'
                    f'[2024-01-01 00:04:00 UTC] dave ({ORPHAN_NOTE}):\norphan\n')
        self.assertEqual(expected, text)

    def test_chat_reactions(self) -> None:
        """Reactions are listed under the message they react to; a reaction to a missing message is a line of its own."""
        heart = ChatReaction(url='https://i.redd.it/heart.gif', name='Heart', enabled=True)
        messages = [chat_message('root', minute=0, author='alice'),
                    chat_message('like', 'root', minute=1, author='bob', reaction=heart),
                    chat_message('lost', 'gone', minute=2, author='carol', reaction=heart)]
        text = format_chat_transcript(ChatChannel(channel_name='Room'), messages)
        expected = ('Chat: Room\n\n'
                    '[2024-01-01 00:00:00 UTC] alice:\nroot\nReactions: bob (Heart, 2024-01-01 00:01:00 UTC)\n\n'
                    f'[2024-01-01 00:02:00 UTC] carol reacted Heart ({ORPHAN_REACTION_NOTE})\n')
        self.assertEqual(expected, text)

    def test_unknown_channel_raises(self) -> None:
        """Exporting a channel that does not exist raises ValueError."""
        with self.db.get_scoped_session() as session, self.assertRaises(ValueError):
            export_chat_transcript(session, 999, os.path.join(self.temp_dir.name, 'none.txt'))

    def test_private_message_thread(self) -> None:
        """A private message thread lists its subject and both directions of the conversation."""
        path = os.path.join(self.temp_dir.name, 'thread.txt')
        with self.db.get_scoped_session() as session:
            count = export_private_message_thread(session, 'm1', path)
        text = self.read(path)
        self.assertEqual(2, count)
        self.assertTrue(text.startswith('Subject: Hello'))
        self.assertIn(f'{ACCOUNT} -> friend_one:', text)
        self.assertIn(f'friend_one -> {ACCOUNT}:', text)
