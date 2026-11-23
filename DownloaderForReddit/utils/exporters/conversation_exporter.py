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

from ...database.conversation_queries import chat_messages, private_message_thread
from ...database.export_models import ChatChannel, ChatMessage, PrivateMessage


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

_UNKNOWN_AUTHOR = '[unknown]'
_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def _format_date(value: Optional[datetime]) -> str:
    """
    Formats a message date for a transcript.
    :param value: The date, in UTC.
    :type value: Optional[datetime]
    :return: The formatted date, or a placeholder when there is none.
    :rtype: str
    """
    return f'{value.strftime(_DATE_FORMAT)} UTC' if value is not None else '[no date]'


def format_chat_transcript(channel: ChatChannel, messages: Iterable[ChatMessage]) -> str:
    """
    Formats a chat channel as a transcript, one message per block.
    :param channel: The channel.
    :type channel: ChatChannel
    :param messages: The channel's messages, in the order to show them.
    :type messages: Iterable[ChatMessage]
    :return: The transcript text.
    :rtype: str
    """
    lines = [f'Chat: {channel.display_name}']
    if channel.subreddit_name:
        lines.append(f'Subreddit: r/{channel.subreddit_name}')
    if channel.conversation_type:
        lines.append(f'Type: {channel.conversation_type}')
    lines.append('')
    for message in messages:
        reply = ' (thread reply)' if message.thread_parent_message_id else ''
        lines.append(f'[{_format_date(message.date_posted)}] {message.author_name or _UNKNOWN_AUTHOR}{reply}:')
        lines.append(message.body or '')
        lines.append('')
    return '\n'.join(lines)


def format_private_message_thread(messages: list[PrivateMessage]) -> str:
    """
    Formats a private message thread as a transcript.
    :param messages: The thread's messages, in the order to show them.
    :type messages: list[PrivateMessage]
    :return: The transcript text.
    :rtype: str
    """
    subject = next((message.subject for message in messages if message.subject), '[no subject]')
    lines = [f'Subject: {subject}', '']
    for message in messages:
        sender = message.sender_name or _UNKNOWN_AUTHOR
        recipient = message.recipient_name or _UNKNOWN_AUTHOR
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
