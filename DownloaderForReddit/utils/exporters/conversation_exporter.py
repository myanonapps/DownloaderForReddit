"""
Exports imported chat channels and private message threads as readable text transcripts.


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
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from ...database.chat_threads import ORPHAN_NOTE, ORPHAN_REACTION_NOTE, ChatThreads, ThreadRow, build_chat_threads
from ...database.conversation_queries import chat_messages, private_message_thread
from ...database.export_models import ChatChannel, ChatMessage, PrivateMessage, person_name


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
_INDENT = '    '


def _format_date(value: Optional[datetime]) -> str:
    """
    Formats a message date for a transcript.
    :param value: The date, in UTC.
    :type value: Optional[datetime]
    :return: The formatted date, or a placeholder when there is none.
    :rtype: str
    """
    return f'{value.strftime(_DATE_FORMAT)} UTC' if value is not None else '[no date]'


def _chat_message_lines(row: ThreadRow, threads: ChatThreads) -> list[str]:
    """
    Formats one chat message for a transcript: a header with its date, author and notes, then its body and the
    reactions it got, every line indented by the message's depth in its thread, followed by a blank line.  A reaction
    to a message the channel does not hold is written as a single line naming the reaction.
    :param row: The message and its place in its thread; depth 0 for a top level message.
    :type row: ThreadRow
    :param threads: The channel's messages arranged into threads.
    :type threads: ChatThreads
    :return: The lines.
    :rtype: list[str]
    """
    message = row.message
    indent = _INDENT * row.depth
    notes = []
    if row.depth == 0:
        if threads.is_orphan(message):
            notes.append(ORPHAN_REACTION_NOTE if message.is_reaction else ORPHAN_NOTE)
        replies = threads.reply_count(message.message_id)
        if replies:
            notes.append(f'{replies} {"reply" if replies == 1 else "replies"}')
    elif row.depth >= 2:
        notes.append(f'replying to {row.parent_author}')
    note = f' ({"; ".join(notes)})' if notes else ''
    header = f'{indent}[{_format_date(message.date_posted)}] {person_name(message.author)}'
    if message.is_reaction:
        return [f'{header} reacted {message.reaction.display_name}{note}', '']
    lines = [f'{header}{note}:']
    lines.extend(f'{indent}{line}' for line in (message.body or '').split('\n'))
    reactions = threads.reactions_to(message)
    if reactions:
        lines.append(f'{indent}Reactions: ' + ', '.join(f'{person_name(reaction.author)} ({reaction.reaction.display_name}, '
                                                          f'{_format_date(reaction.date_posted)})' for reaction in reactions))
    lines.append('')
    return lines


def format_chat_transcript(channel: ChatChannel, messages: Iterable[ChatMessage]) -> str:
    """
    Formats a chat channel as a transcript, one message per block.  Each thread's replies follow the message that
    started it, indented by their depth, instead of being scattered among the channel's other messages.
    :param channel: The channel.
    :type channel: ChatChannel
    :param messages: The channel's messages, oldest first.
    :type messages: Iterable[ChatMessage]
    :return: The transcript text, with people shown under their nicknames where they have one.
    :rtype: str
    """
    lines = [f'Chat: {channel.display_name}']
    if channel.subreddit is not None:
        lines.append(f'Subreddit: {channel.subreddit.nickname_or_name}')
    if channel.conversation_type:
        lines.append(f'Type: {channel.conversation_type}')
    lines.append('')
    threads = build_chat_threads(list(messages))
    for message in threads.timeline:
        for row in threads.threads.get(message.message_id or '', [ThreadRow(message, 0)]):
            lines.extend(_chat_message_lines(row, threads))
    return '\n'.join(lines)


def format_private_message_thread(messages: list[PrivateMessage]) -> str:
    """
    Formats a private message thread as a transcript.
    :param messages: The thread's messages, in the order to show them.
    :type messages: list[PrivateMessage]
    :return: The transcript text, with people shown under their nicknames where they have one.
    :rtype: str
    """
    subject = next((message.subject for message in messages if message.subject), '[no subject]')
    lines = [f'Subject: {subject}', '']
    for message in messages:
        sender = person_name(message.sender)
        recipient = person_name(message.recipient)
        lines.append(f'[{_format_date(message.date_sent)}] {sender} -> {recipient}:')
        lines.append(message.body or '')
        lines.append('')
    return '\n'.join(lines)


def export_chat_transcript(session: Session, channel_id: int, file_path: str) -> int:
    """
    Writes a chat channel's transcript to a text file, replacing the file if it exists.
    :param session: The database session.
    :type session: Session
    :param channel_id: The channel's database id.
    :type channel_id: int
    :param file_path: The file to write.
    :type file_path: str
    :return: The number of messages written.
    :rtype: int
    :raises ValueError: When no channel has the id.
    :raises OSError: When the file cannot be written.
    """
    channel = session.query(ChatChannel).get(channel_id)
    if channel is None:
        raise ValueError(f'No chat channel with id {channel_id}')
    messages = chat_messages(session, channel_id)
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(format_chat_transcript(channel, messages))
    logger.info('Exported chat transcript of %d messages to %s', len(messages), file_path)
    return len(messages)


def export_private_message_thread(session: Session, thread_id: str, file_path: str) -> int:
    """
    Writes a private message thread's transcript to a text file, replacing the file if it exists.
    :param session: The database session.
    :type session: Session
    :param thread_id: The thread id.
    :type thread_id: str
    :param file_path: The file to write.
    :type file_path: str
    :return: The number of messages written.
    :rtype: int
    :raises OSError: When the file cannot be written.
    """
    messages = private_message_thread(session, thread_id)
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(format_private_message_thread(messages))
    logger.info('Exported private message thread of %d messages to %s', len(messages), file_path)
    return len(messages)
