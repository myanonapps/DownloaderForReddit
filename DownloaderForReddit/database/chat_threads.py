"""
Arranges the messages of an imported chat channel into its main timeline and its threads.

Reddit chat threads reply to a message by its id (``ChatMessage.thread_parent_message_id``).  Most replies point to the
message that started the thread, a few reply to another reply, and some point to a message the export does not hold.
Shown in date order, a thread's replies end up scattered among unrelated messages, so the timeline is built from the
top level messages only and each thread is kept apart, root first, then its replies depth first.


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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .export_models import ChatMessage, person_name


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

ORPHAN_NOTE = 'reply to a message not in the export'


@dataclass
class ThreadRow:
    """
    One message of a thread.  The depth is 0 for the message that started the thread, 1 for a reply to it, 2 for a
    reply to a reply, and so on; the parent author names whom a reply answers, and is None for the thread's root.
    """

    message: ChatMessage
    depth: int
    parent_author: Optional[str] = None


@dataclass
class ChatThreads:
    """
    A channel's messages arranged into threads.  The timeline holds the top level messages in the order they were
    given.  Each thread is keyed by its root's message id and lists the root, then every reply depth first, replies to
    the same message in the order they were given; only roots with at least one reply have a thread.  Orphans are the
    ids of top level messages that reply to a message missing from the channel.
    """

    timeline: list[ChatMessage] = field(default_factory=list)
    threads: dict[str, list[ThreadRow]] = field(default_factory=dict)
    orphans: set[str] = field(default_factory=set)

    def reply_count(self, root_id: Optional[str]) -> int:
        """
        Returns how many replies a thread holds, at any depth.
        :param root_id: The message id of the thread's root.
        :type root_id: Optional[str]
        :return: The number of replies; 0 when the message started no thread.
        :rtype: int
        """
        rows = self.threads.get(root_id) if root_id is not None else None
        return len(rows) - 1 if rows else 0

    def last_reply_date(self, root_id: Optional[str]) -> Optional[datetime]:
        """
        Returns when the newest reply of a thread was sent.
        :param root_id: The message id of the thread's root.
        :type root_id: Optional[str]
        :return: The date, or None when the message started no thread or no reply has a date.
        :rtype: Optional[datetime]
        """
        rows = self.threads.get(root_id) if root_id is not None else None
        dates = [row.message.date_posted for row in (rows or [])[1:] if row.message.date_posted is not None]
        return max(dates) if dates else None

    def is_orphan(self, message: ChatMessage) -> bool:
        """
        Tells whether a top level message replies to a message the channel does not hold.
        :param message: The message.
        :type message: ChatMessage
        :return: True for an orphaned reply.
        :rtype: bool
        """
        return message.message_id is not None and message.message_id in self.orphans


def _parent_links(messages: list[ChatMessage]) -> tuple[dict[str, str], set[str]]:
    """
    Finds the parent of each message that replies to another message of the channel.
    :param messages: The channel's messages.
    :type messages: list[ChatMessage]
    :return: The parent id of each reply, keyed by the reply's id, and the ids of replies whose parent is missing.
    :rtype: tuple[dict[str, str], set[str]]
    """
    known = {message.message_id for message in messages if message.message_id is not None}
    parents: dict[str, str] = {}
    orphans: set[str] = set()
    for message in messages:
        message_id, parent_id = message.message_id, message.thread_parent_message_id
        if message_id is None or not parent_id:
            continue
        if parent_id in known and parent_id != message_id:
            parents[message_id] = parent_id
        else:
            orphans.add(message_id)
    return parents, orphans


def _break_cycles(messages: list[ChatMessage], parents: dict[str, str]) -> None:
    """
    Removes parent links until no chain of replies leads back to itself, so every message has a root.  In each cycle,
    the message given first loses its parent and becomes the root.
    :param messages: The channel's messages, in the order they were given.
    :type messages: list[ChatMessage]
    :param parents: The parent id of each reply, changed in place.
    :type parents: dict[str, str]
    :return: None
    :rtype: None
    """
    order = {message.message_id: position for position, message in enumerate(messages) if message.message_id is not None}
    settled: set[str] = set()
    for message in messages:
        path: list[str] = []
        on_path: set[str] = set()
        current: Optional[str] = message.message_id
        while current is not None and current not in settled and current not in on_path:
            path.append(current)
            on_path.add(current)
            current = parents.get(current)
        if current is not None and current in on_path:
            cycle = path[path.index(current):]
            first = min(cycle, key=lambda message_id: order[message_id])
            del parents[first]
            logger.debug('Chat thread cycle of %d messages broken at %s', len(cycle), first)
        settled.update(path)


def build_chat_threads(messages: list[ChatMessage]) -> ChatThreads:
    """
    Arranges a channel's messages into its timeline and threads.  A reply whose parent is not among the messages stays
    in the timeline and is recorded as an orphan; replies to it still form a thread under it.
    :param messages: The channel's messages, oldest first, as chat_messages returns them.
    :type messages: list[ChatMessage]
    :return: The timeline and the threads.
    :rtype: ChatThreads
    """
    parents, orphans = _parent_links(messages)
    _break_cycles(messages, parents)
    by_id = {message.message_id: message for message in messages if message.message_id is not None}
    children: dict[str, list[ChatMessage]] = {}
    for message in messages:
        parent_id = parents.get(message.message_id) if message.message_id is not None else None
        if parent_id is not None:
            children.setdefault(parent_id, []).append(message)

    result = ChatThreads(orphans=orphans)
    for message in messages:
        if message.message_id is not None and message.message_id in parents:
            continue
        result.timeline.append(message)
        if message.message_id is None or message.message_id not in children:
            continue
        rows = [ThreadRow(message, 0)]
        stack = [(child, 1) for child in reversed(children[message.message_id])]
        while stack:
            reply, depth = stack.pop()
            rows.append(ThreadRow(reply, depth, person_name(by_id[parents[reply.message_id]].author)))
            stack.extend((child, depth + 1) for child in reversed(children.get(reply.message_id, [])))
        result.threads[message.message_id] = rows
    return result
