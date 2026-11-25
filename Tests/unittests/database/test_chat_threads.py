"""
Tests for arranging the messages of an imported chat channel into its timeline and its threads.


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

from DownloaderForReddit.database.chat_threads import ChatThreads, build_chat_threads
from DownloaderForReddit.database.export_models import ChatMessage
from DownloaderForReddit.database.models import User


def chat_message(message_id: Optional[str], parent_id: Optional[str] = None, minute: int = 0, author: str = 'someone') -> ChatMessage:
    """
    Creates a chat message that is not stored in any database.
    :param message_id: The message's id.
    :type message_id: Optional[str]
    :param parent_id: The id of the message it replies to in a thread, if any.
    :type parent_id: Optional[str]
    :param minute: When it was sent, in minutes after a fixed time.
    :type minute: int
    :param author: The name of the user who wrote it.
    :type author: str
    :return: The message.
    :rtype: ChatMessage
    """
    return ChatMessage(message_id=message_id, thread_parent_message_id=parent_id, body=message_id,
                       date_posted=datetime(2024, 1, 1, 0, minute), author=User(name=author))


def ids(messages: list[ChatMessage]) -> list[Optional[str]]:
    """
    Returns the ids of messages.
    :param messages: The messages.
    :type messages: list[ChatMessage]
    :return: The ids, in the same order.
    :rtype: list[Optional[str]]
    """
    return [message.message_id for message in messages]


def thread_layout(threads: ChatThreads, root_id: str) -> list[tuple[Optional[str], int]]:
    """
    Returns the id and depth of each message of a thread.
    :param threads: The arranged messages.
    :type threads: ChatThreads
    :param root_id: The id of the thread's first message.
    :type root_id: str
    :return: The ids and depths, in the thread's order.
    :rtype: list[tuple[Optional[str], int]]
    """
    return [(row.message.message_id, row.depth) for row in threads.threads[root_id]]


class TestBuildChatThreads(TestCase):
    """Tests for build_chat_threads."""

    def test_no_threads(self) -> None:
        """A channel without replies keeps every message in its timeline and has no threads."""
        threads = build_chat_threads([chat_message('a', minute=0), chat_message('b', minute=1)])
        self.assertEqual(['a', 'b'], ids(threads.timeline))
        self.assertEqual({}, threads.threads)
        self.assertEqual(0, threads.reply_count('a'))
        self.assertIsNone(threads.last_reply_date('a'))

    def test_replies_leave_the_timeline(self) -> None:
        """Replies are taken out of the timeline, which keeps its order, and listed under their thread's root."""
        threads = build_chat_threads([chat_message('root', minute=0), chat_message('other', minute=1),
                                      chat_message('r1', 'root', minute=2), chat_message('later', minute=3),
                                      chat_message('r2', 'root', minute=4)])
        self.assertEqual(['root', 'other', 'later'], ids(threads.timeline))
        self.assertEqual([('root', 0), ('r1', 1), ('r2', 1)], thread_layout(threads, 'root'))
        self.assertEqual(2, threads.reply_count('root'))
        self.assertEqual(datetime(2024, 1, 1, 0, 4), threads.last_reply_date('root'))

    def test_nested_replies_are_depth_first(self) -> None:
        """A reply to a reply comes right after the reply it answers, one level deeper, naming that reply's author."""
        threads = build_chat_threads([chat_message('root', minute=0, author='alice'), chat_message('r1', 'root', minute=1, author='bob'),
                                      chat_message('r2', 'root', minute=2), chat_message('r1a', 'r1', minute=3),
                                      chat_message('r1a1', 'r1a', minute=4)])
        self.assertEqual([('root', 0), ('r1', 1), ('r1a', 2), ('r1a1', 3), ('r2', 1)], thread_layout(threads, 'root'))
        rows = {row.message.message_id: row for row in threads.threads['root']}
        self.assertIsNone(rows['root'].parent_author)
        self.assertEqual('alice', rows['r1'].parent_author)
        self.assertEqual('bob', rows['r1a'].parent_author)
        self.assertEqual(4, threads.reply_count('root'))

    def test_missing_parent_makes_an_orphan(self) -> None:
        """A reply to a message the channel does not hold stays in the timeline as an orphan, and can start a thread."""
        threads = build_chat_threads([chat_message('a', minute=0), chat_message('orphan', 'gone', minute=1),
                                      chat_message('reply', 'orphan', minute=2)])
        self.assertEqual(['a', 'orphan'], ids(threads.timeline))
        self.assertTrue(threads.is_orphan(threads.timeline[1]))
        self.assertFalse(threads.is_orphan(threads.timeline[0]))
        self.assertEqual([('orphan', 0), ('reply', 1)], thread_layout(threads, 'orphan'))

    def test_self_reply_is_an_orphan(self) -> None:
        """A message that names itself as its parent stays in the timeline."""
        threads = build_chat_threads([chat_message('a', 'a')])
        self.assertEqual(['a'], ids(threads.timeline))
        self.assertEqual({}, threads.threads)

    def test_cycle_is_broken_at_its_first_message(self) -> None:
        """Replies that lead back to themselves are rooted at the cycle's first message, so none of them is lost."""
        threads = build_chat_threads([chat_message('x', 'z', minute=0), chat_message('y', 'x', minute=1),
                                      chat_message('z', 'y', minute=2)])
        self.assertEqual(['x'], ids(threads.timeline))
        self.assertEqual([('x', 0), ('y', 1), ('z', 2)], thread_layout(threads, 'x'))

    def test_message_without_id(self) -> None:
        """A message without an id stays in the timeline and starts no thread."""
        threads = build_chat_threads([chat_message(None, minute=0), chat_message('a', minute=1)])
        self.assertEqual([None, 'a'], ids(threads.timeline))
        self.assertEqual(0, threads.reply_count(None))
        self.assertFalse(threads.is_orphan(threads.timeline[0]))
