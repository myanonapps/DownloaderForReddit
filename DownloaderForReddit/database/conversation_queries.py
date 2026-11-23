"""
Queries over the conversations imported from Reddit data exports: chat channels and private message threads.


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

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .export_models import ChatChannel, ChatMessage, ExportImport, PrivateMessage


CHAT = 'CHAT'
PRIVATE_MESSAGE = 'PRIVATE_MESSAGE'
_NO_SUBJECT = '[no subject]'


@dataclass
class ConversationSummary:
    """One line in a list of conversations."""

    kind: str
    key: Union[int, str]  # the channel id for a chat, the thread id for private messages
    title: str
    message_count: int
    last_date: Optional[datetime]


def _like(text: str) -> str:
    """
    Builds a case-insensitive LIKE pattern that matches the text anywhere, with LIKE's wildcards escaped.
    :param text: The text to look for.
    :type text: str
    :return: The pattern, for use with escape='\\'.
    :rtype: str
    """
    escaped = text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def chat_messages(session: Session, channel_id: int) -> list[ChatMessage]:
    """
    Returns a channel's messages, oldest first.
    :param session: The database session.
    :type session: Session
    :param channel_id: The channel's database id.
    :type channel_id: int
    :return: The messages.
    :rtype: list[ChatMessage]
    """
    return session.query(ChatMessage).filter(ChatMessage.channel_id == channel_id) \
        .order_by(ChatMessage.date_posted, ChatMessage.id).all()


def private_message_thread(session: Session, thread_id: str) -> list[PrivateMessage]:
    """
    Returns the messages of a private message thread, oldest first.
    :param session: The database session.
    :type session: Session
    :param thread_id: The thread id shared by the messages.
    :type thread_id: str
    :return: The messages.
    :rtype: list[PrivateMessage]
    """
    return session.query(PrivateMessage).filter(PrivateMessage.thread_id == thread_id) \
        .order_by(PrivateMessage.date_sent, PrivateMessage.id).all()


def chat_summaries(session: Session, search: Optional[str] = None) -> list[ConversationSummary]:
    """
    Lists the chat channels, most recently active first.
    :param session: The database session.
    :type session: Session
    :param search: When given, only channels with a message, author or name containing this text are listed.
    :type search: Optional[str]
    :return: The channel summaries.
    :rtype: list[ConversationSummary]
    """
    query = session.query(ChatChannel, func.count(ChatMessage.id), func.max(ChatMessage.date_posted)) \
        .outerjoin(ChatMessage, ChatMessage.channel_id == ChatChannel.id).group_by(ChatChannel.id)
    if search:
        pattern = _like(search)
        matching = session.query(ChatMessage.channel_id).filter(or_(ChatMessage.body.ilike(pattern, escape='\\'),
                                                                    ChatMessage.author_name.ilike(pattern, escape='\\')))
        query = query.filter(or_(ChatChannel.id.in_(matching), ChatChannel.channel_name.ilike(pattern, escape='\\')))
    summaries = [ConversationSummary(CHAT, channel.id, channel.display_name, count, last_date)
                 for channel, count, last_date in query]
    return sorted(summaries, key=lambda summary: summary.last_date or datetime.min, reverse=True)


def private_thread_summaries(session: Session, search: Optional[str] = None) -> list[ConversationSummary]:
    """
    Lists the private message threads, most recently active first.  A thread is titled with its subject and the
    people in it other than the account owner.
    :param session: The database session.
    :type session: Session
    :param search: When given, only threads with a message, subject or participant containing this text are listed.
    :type search: Optional[str]
    :return: The thread summaries.
    :rtype: list[ConversationSummary]
    """
    query = session.query(PrivateMessage.thread_id, func.count(PrivateMessage.id), func.max(PrivateMessage.date_sent)) \
        .filter(PrivateMessage.thread_id.isnot(None)).group_by(PrivateMessage.thread_id)
    if search:
        pattern = _like(search)
        matching = session.query(PrivateMessage.thread_id).filter(or_(
            PrivateMessage.body.ilike(pattern, escape='\\'), PrivateMessage.subject.ilike(pattern, escape='\\'),
            PrivateMessage.sender_name.ilike(pattern, escape='\\'), PrivateMessage.recipient_name.ilike(pattern, escape='\\')))
        query = query.filter(PrivateMessage.thread_id.in_(matching))
    owners = {name.lower() for name, in session.query(ExportImport.account_name).distinct() if name}
    summaries = []
    for thread_id, count, last_date in query:
        messages = private_message_thread(session, thread_id)
        subject = next((message.subject for message in messages if message.subject), _NO_SUBJECT)
        people = {name for message in messages for name in (message.sender_name, message.recipient_name)
                  if name and name.lower() not in owners}
        title = f'{subject} ({", ".join(sorted(people, key=str.lower))})' if people else subject
        summaries.append(ConversationSummary(PRIVATE_MESSAGE, thread_id, title, count, last_date))
    return sorted(summaries, key=lambda summary: summary.last_date or datetime.min, reverse=True)
