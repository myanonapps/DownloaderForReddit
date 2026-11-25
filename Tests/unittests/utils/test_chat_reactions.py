"""
Tests for recognizing chat reactions and for the library of reactions shared by every chat.


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

from datetime import datetime
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock

from DownloaderForReddit.database.conversation_queries import CHAT, ConversationSummary, unextracted_message_ids
from DownloaderForReddit.database.database_handler import DatabaseHandler
from DownloaderForReddit.database.export_models import ChatChannel, ChatMessage, ChatReaction
from DownloaderForReddit.database.models import Content, User
from DownloaderForReddit.utils import injector
from DownloaderForReddit.utils.chat_reactions import (link_chat_reactions, reaction_url, reaction_usage, rename_reaction,
                                                      set_reaction_enabled, single_url)


HEART = 'https://i.redd.it/8r21ukpfa7081.gif'
LAUGH = 'https://i.redd.it/jvuspmbga7081.gif'
UPLOAD = 'https://matrix.redditspace.com/_matrix/media/v3/download/reddit.com/1a9dqx3tisfh1'


class TestReactionUrl(TestCase):
    """Tests for telling which message texts are reaction images."""

    def test_single_reaction_image(self) -> None:
        """A message that is only an i.redd.it GIF or PNG url, surrounding blanks aside, is a reaction image."""
        self.assertEqual(HEART, reaction_url(f'  {HEART}\n'))
        self.assertEqual(HEART.upper(), reaction_url(HEART.upper()))
        self.assertEqual('https://i.redd.it/abc.png', reaction_url('https://i.redd.it/abc.png'))
        self.assertEqual('https://i.redd.it/abc.PNG', reaction_url('https://i.redd.it/abc.PNG'))

    def test_other_texts_are_not_reactions(self) -> None:
        """Uploads, other image types, other hosts, text around the url and several urls are not reaction images."""
        for body in (UPLOAD, 'https://i.redd.it/abc.jpg', 'https://i.redd.it/abc.webp', 'https://example.com/a.png',
                     f'look {HEART}', f'{HEART} {LAUGH}', '', None, 'https://i.redd.it/a/b.gif'):
            with self.subTest(body=body):
                self.assertIsNone(reaction_url(body))

    def test_single_url(self) -> None:
        """Any message that is only one url gives that url; anything else gives none."""
        self.assertEqual(UPLOAD, single_url(f' {UPLOAD} '))
        self.assertIsNone(single_url(f'see {UPLOAD}'))
        self.assertIsNone(single_url(None))


class TestChatReactions(TestCase):
    """Tests for linking, marking and listing reactions, against an in-memory database."""

    def setUp(self) -> None:
        """Gives each test a fresh in-memory database with two chats between alice and bob."""
        injector.settings_manager = MagicMock()
        self.db = DatabaseHandler(in_memory=True)
        injector.database_handler = self.db
        with self.db.get_scoped_session() as session:
            session.add_all([User(name='alice'), User(name='bob'), ChatChannel(channel_url='chat-1'), ChatChannel(channel_url='chat-2')])
            session.commit()
        self.minute = 0

    def add(self, message_id: str, body: str, parent: Optional[str] = None, *, channel: str = 'chat-1', author: str = 'alice') -> int:  # pylint: disable=too-many-arguments  # test helper; the options are keyword-only
        """
        Stores a chat message with links not extracted yet.
        :param message_id: The message's id.
        :type message_id: str
        :param body: The message text.
        :type body: str
        :param parent: The id of the message it replies to, if any.
        :type parent: Optional[str]
        :param channel: The url of its chat.
        :type channel: str
        :param author: The name of the user who wrote it.
        :type author: str
        :return: The message's database id.
        :rtype: int
        """
        self.minute += 1
        with self.db.get_scoped_session() as session:
            message = ChatMessage(message_id=message_id, body=body, thread_parent_message_id=parent, extracted=False,
                                  date_posted=datetime(2024, 1, 1, 0, self.minute),
                                  channel=session.query(ChatChannel).filter(ChatChannel.channel_url == channel).one(),
                                  author=session.query(User).filter(User.name == author).one())
            session.add(message)
            session.commit()
            return message.id

    def link(self) -> int:
        """
        Links every stored message and commits.
        :return: The number of messages linked.
        :rtype: int
        """
        with self.db.get_scoped_session() as session:
            linked = link_chat_reactions(session)
            session.commit()
            return linked

    def reaction_of(self, message_id: str) -> Optional[str]:
        """
        Returns the url of the reaction a message is linked to.
        :param message_id: The message's id.
        :type message_id: str
        :return: The url, or None when the message is not linked to a reaction.
        :rtype: Optional[str]
        """
        with self.db.get_scoped_session() as session:
            message = session.query(ChatMessage).filter(ChatMessage.message_id == message_id).one()
            return message.reaction.url if message.reaction is not None else None

    def is_reaction(self, message_id: str) -> bool:
        """
        Tells whether a message is shown as a reaction.
        :param message_id: The message's id.
        :type message_id: str
        :return: True when it is linked to an enabled reaction.
        :rtype: bool
        """
        with self.db.get_scoped_session() as session:
            return session.query(ChatMessage).filter(ChatMessage.message_id == message_id).one().is_reaction

    def test_replies_with_reaction_gifs_are_linked(self) -> None:
        """Replies that are only a reaction image are linked and extracted; other messages, top level images included, are left alone."""
        self.add('root', 'hello')
        self.add('reaction', HEART, 'root', author='bob')
        self.add('top', LAUGH)
        self.add('upload', UPLOAD, 'root')
        self.add('text', f'look {HEART}', 'root')
        self.assertEqual(1, self.link())
        self.assertEqual(HEART, self.reaction_of('reaction'))
        for message_id in ('root', 'top', 'upload', 'text'):
            self.assertIsNone(self.reaction_of(message_id))
        with self.db.get_scoped_session() as session:
            self.assertTrue(session.query(ChatMessage).filter(ChatMessage.message_id == 'reaction').one().extracted)
            self.assertFalse(session.query(ChatMessage).filter(ChatMessage.message_id == 'top').one().extracted)

    def test_linking_again_changes_nothing(self) -> None:
        """Linking is idempotent."""
        self.add('root', 'hello')
        self.add('reaction', HEART, 'root')
        self.assertEqual(1, self.link())
        self.assertEqual(0, self.link())

    def test_one_reaction_is_shared_by_every_chat(self) -> None:
        """The same image in two chats is one reaction."""
        self.add('root-1', 'hello')
        self.add('reaction-1', HEART, 'root-1')
        self.add('root-2', 'hi', channel='chat-2')
        self.add('reaction-2', HEART.upper(), 'root-2', channel='chat-2')
        self.assertEqual(2, self.link())
        with self.db.get_scoped_session() as session:
            self.assertEqual(1, session.query(ChatReaction).count())

    def test_known_reaction_links_messages_that_are_not_replies(self) -> None:
        """Once an image is a reaction, a message that is only that image is a reaction even when it is not a reply."""
        self.add('root', 'hello')
        self.add('reaction', HEART, 'root')
        self.add('top', HEART)
        self.assertEqual(2, self.link())
        self.assertTrue(self.is_reaction('top'))

    def test_new_import_links_only_the_given_messages(self) -> None:
        """Linking a list of message ids leaves other messages alone."""
        self.add('root', 'hello')
        first = self.add('reaction-1', HEART, 'root')
        self.add('reaction-2', LAUGH, 'root')
        with self.db.get_scoped_session() as session:
            self.assertEqual(1, link_chat_reactions(session, [first]))
            session.commit()
        self.assertIsNone(self.reaction_of('reaction-2'))

    def test_unmarking_keeps_the_url_from_being_recognized(self) -> None:
        """A reaction marked as not one shows its messages as messages, lets their media download, and is not relinked."""
        self.add('root', 'hello')
        self.add('reaction', HEART, 'root')
        self.link()
        with self.db.get_scoped_session() as session:
            set_reaction_enabled(session, HEART, False)
        self.assertFalse(self.is_reaction('reaction'))
        self.add('later', HEART, 'root')
        self.link()
        self.assertFalse(self.is_reaction('later'))
        with self.db.get_scoped_session() as session:
            channel_id = session.query(ChatChannel).filter(ChatChannel.channel_url == 'chat-1').one().id
            ids = unextracted_message_ids(session, ConversationSummary(CHAT, channel_id, 'chat', 3, None))
            self.assertEqual(3, len(ids))

    def test_unmarking_keeps_extracted_messages_with_content(self) -> None:
        """Messages whose media was already extracted stay extracted when their reaction is marked as not one."""
        self.add('root', 'hello')
        message_id = self.add('reaction', HEART, 'root')
        self.link()
        with self.db.get_scoped_session() as session:
            session.add(Content(url=HEART, chat_message_id=message_id))
            session.commit()
            set_reaction_enabled(session, HEART, False)
            self.assertTrue(session.query(ChatMessage).get(message_id).extracted)

    def test_marking_links_every_chat(self) -> None:
        """Marking an image as a reaction links every message that is only that image, in every chat."""
        self.add('a', UPLOAD)
        self.add('b', f' {UPLOAD} ', channel='chat-2')
        self.add('c', f'see {UPLOAD}')
        with self.db.get_scoped_session() as session:
            set_reaction_enabled(session, UPLOAD, True)
        self.assertTrue(self.is_reaction('a'))
        self.assertTrue(self.is_reaction('b'))
        self.assertFalse(self.is_reaction('c'))

    def test_reactions_are_not_offered_for_download(self) -> None:
        """Reaction messages are not offered for download."""
        self.add('root', f'look {UPLOAD}')
        self.add('reaction', HEART, 'root')
        self.link()
        with self.db.get_scoped_session() as session:
            channel_id = session.query(ChatChannel).filter(ChatChannel.channel_url == 'chat-1').one().id
            ids = unextracted_message_ids(session, ConversationSummary(CHAT, channel_id, 'chat', 2, None))
            self.assertEqual(1, len(ids))

    def test_usage_and_names(self) -> None:
        """Usage counts the uses and chats of each reaction, the most used first, under the names given them."""
        self.add('root-1', 'hello')
        self.add('heart-1', HEART, 'root-1')
        self.add('heart-2', HEART, 'root-1', author='bob')
        self.add('root-2', 'hi', channel='chat-2')
        self.add('heart-3', HEART, 'root-2', channel='chat-2')
        self.add('laugh', LAUGH, 'root-2', channel='chat-2')
        self.link()
        with self.db.get_scoped_session() as session:
            usage = reaction_usage(session)
            self.assertEqual([(HEART, 3, 2), (LAUGH, 1, 1)], [(record.url, record.uses, record.chats) for record in usage])
            self.assertEqual('8r21ukpfa7081', usage[0].display_name)
            self.assertEqual(datetime(2024, 1, 1, 0, 5), usage[0].last_used)
            rename_reaction(session, usage[0].reaction_id, ' Heart ')
            self.assertEqual('Heart', reaction_usage(session)[0].display_name)
            rename_reaction(session, usage[0].reaction_id, '  ')
            self.assertEqual('8r21ukpfa7081', reaction_usage(session)[0].display_name)
            self.assertIsNone(rename_reaction(session, 999, 'x'))
