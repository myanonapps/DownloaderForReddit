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

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Union

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from .export_models import ChatChannel, ChatMessage, ExportImport, PrivateMessage, person_name
from .models import Content, RedditObject


CHAT = 'CHAT'
PRIVATE_MESSAGE = 'PRIVATE_MESSAGE'
_NO_SUBJECT = '[no subject]'
_NONE = '—'
_DATE_FORMAT = '%Y-%m-%d %H:%M'
_ID_QUERY_SIZE = 500  # stays below SQLite's bound parameter limit
PARTICIPANTS = 'Participants'


@dataclass
class ConversationSummary:
    """One line in a list of conversations."""

    kind: str
    key: Union[int, str]  # the channel id for a chat, the thread id for private messages
    title: str
    message_count: int
    last_date: Optional[datetime]


@dataclass
class PropertyRow:
    """
    One row of a conversation's properties.  A participant row also holds the participant's reddit object (a user,
    or a subreddit for modmail, or None for messages that could not be linked) so the pane can show its icon.
    """

    name: str
    value: str
    is_participant: bool = False
    participant: Optional[RedditObject] = None


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


def _participants_matching(session: Session, pattern: str) -> Query:
    """
    Builds a query for the ids of the reddit objects whose reddit name or nickname matches a LIKE pattern, so that a
    search finds a participant's conversations under either name.
    :param session: The database session.
    :type session: Session
    :param pattern: A LIKE pattern built by _like.
    :type pattern: str
    :return: The query, selecting RedditObject.id.
    :rtype: Query
    """
    return session.query(RedditObject.id).filter(or_(RedditObject.name.ilike(pattern, escape='\\'),
                                                     RedditObject.nickname.ilike(pattern, escape='\\')))


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
    :param search: When given, only channels with a message, author (by reddit name or nickname), channel name or
        channel nickname containing this text are listed.
    :type search: Optional[str]
    :return: The channel summaries, titled as ChatChannel.display_name.
    :rtype: list[ConversationSummary]
    """
    query = session.query(ChatChannel, func.count(ChatMessage.id), func.max(ChatMessage.date_posted)) \
        .outerjoin(ChatMessage, ChatMessage.channel_id == ChatChannel.id).group_by(ChatChannel.id)
    if search:
        pattern = _like(search)
        matching = session.query(ChatMessage.channel_id).filter(or_(
            ChatMessage.body.ilike(pattern, escape='\\'), ChatMessage.author_id.in_(_participants_matching(session, pattern))))
        query = query.filter(or_(ChatChannel.id.in_(matching), ChatChannel.channel_name.ilike(pattern, escape='\\'),
                                 ChatChannel.nickname.ilike(pattern, escape='\\')))
    summaries = [ConversationSummary(CHAT, channel.id, channel.display_name, count, last_date)
                 for channel, count, last_date in query]
    return sorted(summaries, key=lambda summary: summary.last_date or datetime.min, reverse=True)


def _thread_subject(messages: list[PrivateMessage]) -> str:
    """
    Returns a private message thread's subject: the first one set among its messages.
    :param messages: The thread's messages, oldest first.
    :type messages: list[PrivateMessage]
    :return: The subject, or a placeholder when no message has one.
    :rtype: str
    """
    return next((message.subject for message in messages if message.subject), _NO_SUBJECT)


def _thread_title(messages: list[PrivateMessage]) -> str:
    """
    Titles a private message thread with its subject and every participant (user, or subreddit for modmail) that sent
    or received a message in it, shown under their nicknames where they have one.
    :param messages: The thread's messages.
    :type messages: list[PrivateMessage]
    :return: The title.
    :rtype: str
    """
    subject = _thread_subject(messages)
    names = {person_name(participant) for message in messages for participant in (message.sender, message.recipient)}
    return f'{subject} ({", ".join(sorted(names, key=str.lower))})' if names else subject


def private_thread_summaries(session: Session, search: Optional[str] = None) -> list[ConversationSummary]:
    """
    Lists the private message threads, most recently active first.  A thread is titled with its subject and everybody
    who took part in it.
    :param session: The database session.
    :type session: Session
    :param search: When given, only threads with a message, subject or participant (by reddit name or nickname)
        containing this text are listed.
    :type search: Optional[str]
    :return: The thread summaries.
    :rtype: list[ConversationSummary]
    """
    query = session.query(PrivateMessage.thread_id, func.count(PrivateMessage.id), func.max(PrivateMessage.date_sent)) \
        .filter(PrivateMessage.thread_id.isnot(None)).group_by(PrivateMessage.thread_id)
    if search:
        pattern = _like(search)
        participants = _participants_matching(session, pattern)
        matching = session.query(PrivateMessage.thread_id).filter(or_(
            PrivateMessage.body.ilike(pattern, escape='\\'), PrivateMessage.subject.ilike(pattern, escape='\\'),
            PrivateMessage.sender_id.in_(participants), PrivateMessage.recipient_id.in_(participants)))
        query = query.filter(PrivateMessage.thread_id.in_(matching))
    summaries = []
    for thread_id, count, last_date in query:
        title = _thread_title(private_message_thread(session, thread_id))
        summaries.append(ConversationSummary(PRIVATE_MESSAGE, thread_id, title, count, last_date))
    return sorted(summaries, key=lambda summary: summary.last_date or datetime.min, reverse=True)


def _format_date(date: Optional[datetime]) -> str:
    """
    Formats a date for the properties of a conversation.
    :param date: The date.
    :type date: Optional[datetime]
    :return: The formatted date, or a dash when there is none.
    :rtype: str
    """
    return date.strftime(_DATE_FORMAT) if date is not None else _NONE


def _participant_rows(counts: dict[Optional[RedditObject], int], suffix: str) -> list[PropertyRow]:
    """
    Lists the participants of a conversation, one row each, with how many messages each wrote, ordered by the name
    they are shown under without regard to case.  A participant is a user, or a subreddit for modmail.
    :param counts: Each participant (None for a message that could not be linked) mapped to their message count.
    :type counts: dict[Optional[RedditObject], int]
    :param suffix: Text after the word 'message(s)', for example ' sent'.
    :type suffix: str
    :return: The rows, the first named 'Participants' and the rest unnamed, or a single dash row when there are none.
    :rtype: list[PropertyRow]
    """
    ordered = sorted(counts.items(), key=lambda item: person_name(item[0]).lower())
    rows = [PropertyRow('' if position else PARTICIPANTS, f'{person_name(participant)} ({count:,} message{"" if count == 1 else "s"}{suffix})',
                        is_participant=True, participant=participant)
            for position, (participant, count) in enumerate(ordered)]
    return rows or [PropertyRow(PARTICIPANTS, _NONE)]


def _import_lines(imports: Iterable[Optional[ExportImport]]) -> str:
    """
    Lists the export imports that messages came from, oldest import first, one per line.
    :param imports: The messages' imports; None and repeats are skipped.
    :type imports: Iterable[Optional[ExportImport]]
    :return: The lines, or a dash when there are none.
    :rtype: str
    """
    distinct = sorted({export_import for export_import in imports if export_import is not None},
                      key=lambda export_import: export_import.import_date or datetime.min)
    return '\n'.join(f'{export_import.file_name} ({_format_date(export_import.import_date)})' for export_import in distinct) or _NONE


def _chat_properties(session: Session, channel_id: int) -> list[PropertyRow]:
    """
    Describes a chat channel.
    :param session: The database session.
    :type session: Session
    :param channel_id: The channel's database id.
    :type channel_id: int
    :return: The property rows, or an empty list when the channel does not exist.
    :rtype: list[PropertyRow]
    """
    channel = session.query(ChatChannel).get(channel_id)
    if channel is None:
        return []
    messages = chat_messages(session, channel_id)
    dates = [message.date_posted for message in messages if message.date_posted is not None]
    return [
        PropertyRow('Name', channel.display_name),
        PropertyRow('Nickname', channel.nickname or _NONE),
        PropertyRow('Channel name', channel.channel_name or _NONE),
        PropertyRow('Channel URL', channel.channel_url or _NONE),
        PropertyRow('Type', channel.conversation_type or _NONE),
        PropertyRow('Subreddit', channel.subreddit.name if channel.subreddit is not None else _NONE),
        *_participant_rows(Counter(message.author for message in messages), ''),
        PropertyRow('Messages', f'{len(messages):,}'),
        PropertyRow('First message', _format_date(min(dates, default=None))),
        PropertyRow('Last message', _format_date(max(dates, default=None))),
        PropertyRow('Imported from', _import_lines(message.export_import for message in messages)),
    ]


def _thread_properties(session: Session, thread_id: str) -> list[PropertyRow]:
    """
    Describes a private message thread.  Every user or subreddit that sent or received a message is a participant,
    with the number of messages they sent.
    :param session: The database session.
    :type session: Session
    :param thread_id: The thread id shared by the messages.
    :type thread_id: str
    :return: The property rows, or an empty list when the thread has no messages.
    :rtype: list[PropertyRow]
    """
    messages = private_message_thread(session, thread_id)
    if not messages:
        return []
    counts: dict[Optional[RedditObject], int] = {message.recipient: 0 for message in messages}
    counts.update(Counter(message.sender for message in messages))
    dates = [message.date_sent for message in messages if message.date_sent is not None]
    return [
        PropertyRow('Subject', _thread_subject(messages)),
        PropertyRow('Thread id', thread_id),
        *_participant_rows(counts, ' sent'),
        PropertyRow('Messages', f'{len(messages):,}'),
        PropertyRow('First message', _format_date(min(dates, default=None))),
        PropertyRow('Last message', _format_date(max(dates, default=None))),
        PropertyRow('Imported from', _import_lines(message.export_import for message in messages)),
    ]


def conversation_properties(session: Session, summary: ConversationSummary) -> list[PropertyRow]:
    """
    Describes a conversation for the properties pane: its identity, its participants with their message counts, its
    size and dates, and the export imports its messages came from.  Participant rows hold the participant's reddit
    object, which is only usable while the session is open.
    :param session: The database session.
    :type session: Session
    :param summary: The conversation, as listed.
    :type summary: ConversationSummary
    :return: The property rows, in display order; empty when the conversation no longer exists.
    :rtype: list[PropertyRow]
    """
    if summary.kind == CHAT:
        return _chat_properties(session, summary.key)
    return _thread_properties(session, summary.key)


def set_chat_nickname(session: Session, channel_id: int, nickname: str) -> Optional[str]:
    """
    Stores the nickname the user gave a chat channel and commits it.  Surrounding whitespace is removed, and a blank
    nickname is stored as None so the channel is named by Reddit's name or its participants again.
    :param session: The database session.
    :type session: Session
    :param channel_id: The channel's database id.
    :type channel_id: int
    :param nickname: The nickname typed by the user.
    :type nickname: str
    :return: The channel's display name after the change, or None when the channel does not exist.
    :rtype: Optional[str]
    """
    channel = session.query(ChatChannel).get(channel_id)
    if channel is None:
        return None
    channel.nickname = nickname.strip() or None
    session.commit()
    return channel.display_name


def message_content(session: Session, kind: str, message_ids: Iterable[int]) -> dict[int, list[Content]]:
    """
    Returns the content extracted from messages' links, grouped by message.
    :param session: The database session.
    :type session: Session
    :param kind: CHAT for chat messages, PRIVATE_MESSAGE for private messages.
    :type kind: str
    :param message_ids: The database ids of the messages.
    :type message_ids: Iterable[int]
    :return: Each message id that has content mapped to its content, oldest first.
    :rtype: dict[int, list[Content]]
    """
    column = Content.chat_message_id if kind == CHAT else Content.private_message_id
    grouped: dict[int, list[Content]] = {}
    ids = list(message_ids)
    for start in range(0, len(ids), _ID_QUERY_SIZE):
        chunk = ids[start:start + _ID_QUERY_SIZE]
        for content in session.query(Content).filter(column.in_(chunk)).order_by(Content.id):
            grouped.setdefault(getattr(content, column.key), []).append(content)
    return grouped


def unextracted_message_ids(session: Session, summary: ConversationSummary) -> list[int]:
    """
    Returns the messages of a conversation whose links have not been extracted, or failed to be.  Messages without
    links are recorded as extracted when they are imported, so these are the messages that may have media to download.
    :param session: The database session.
    :type session: Session
    :param summary: The conversation.
    :type summary: ConversationSummary
    :return: The message ids, oldest first.
    :rtype: list[int]
    """
    if summary.kind == CHAT:
        query = session.query(ChatMessage.id).filter(ChatMessage.channel_id == summary.key) \
            .filter(or_(ChatMessage.extracted.is_(None), ChatMessage.extracted.is_(False))) \
            .order_by(ChatMessage.date_posted, ChatMessage.id)
    else:
        query = session.query(PrivateMessage.id).filter(PrivateMessage.thread_id == summary.key) \
            .filter(or_(PrivateMessage.extracted.is_(None), PrivateMessage.extracted.is_(False))) \
            .order_by(PrivateMessage.date_sent, PrivateMessage.id)
    return [message_id for message_id, in query]
