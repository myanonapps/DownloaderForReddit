"""
Database models for data imported from a Reddit data export (the "Request your data" zip archive).

These hold the conversations (chat and legacy private messages) that cannot be retrieved through any of the
download sources, along with a record of each import that was performed.


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
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from .models import BaseModel

if TYPE_CHECKING:
    from .models import RedditObject


_ROOM_ID_DISPLAY_LENGTH = 10
DELETED_PERSON = '[deleted]'


def person_name(reddit_object: Optional['RedditObject']) -> str:
    """
    Returns the name a participant in an imported conversation is shown under.  A participant is a reddit object: a
    user, or a subreddit for modmail.
    :param reddit_object: The user or subreddit the message points to.  Imports always link one (a placeholder user for
                          deleted accounts), so None only occurs for rows that could not be linked.
    :type reddit_object: Optional[RedditObject]
    :return: The nickname when one is set, otherwise the reddit name, or a placeholder when there is no reddit object.
    :rtype: str
    """
    return reddit_object.nickname_or_name if reddit_object is not None else DELETED_PERSON


class ExportImport(BaseModel):
    """A single import of a Reddit data export archive."""

    __tablename__ = 'export_import'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String)
    file_sha256 = Column(String, index=True)
    import_date = Column(DateTime, default=datetime.now)
    post_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    chat_message_count = Column(Integer, default=0)
    private_message_count = Column(Integer, default=0)

    owner_id = Column(ForeignKey('user.id'), nullable=True)
    owner = relationship('User', backref='export_imports')
    download_session_id = Column(ForeignKey('download_session.id'), nullable=True)
    download_session = relationship('DownloadSession', backref='export_imports')

    def __str__(self) -> str:
        """
        Returns a readable description of the import.
        :return: The description.
        :rtype: str
        """
        return f'Export import: {person_name(self.owner)} ({self.file_name})'

    @property
    def import_date_display(self) -> Optional[str]:
        """
        The import date formatted for display.
        :return: The formatted date, or None when no date is set.
        :rtype: Optional[str]
        """
        return self.get_display_datetime(self.import_date)


class ChatChannel(BaseModel):
    """
    A chat channel (direct chat, group chat or subreddit chat) found in an export.  A channel is identified by its url
    and belongs to no account: exports of several accounts that took part in it all add their messages to the same
    channel.
    """

    __tablename__ = 'chat_channel'

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_url = Column(String, unique=True)
    channel_name = Column(String(collation='NOCASE'), nullable=True)
    nickname = Column(String(collation='NOCASE'), nullable=True)
    conversation_type = Column(String, nullable=True)

    subreddit_id = Column(ForeignKey('subreddit.id'), nullable=True)
    subreddit = relationship('Subreddit', backref='chat_channels')
    messages = relationship('ChatMessage', back_populates='channel')

    def __str__(self) -> str:
        """
        Returns a readable description of the channel.
        :return: 'Chat: ' followed by the channel's display name.
        :rtype: str
        """
        return f'Chat: {self.display_name}'

    @property
    def participants(self) -> list['RedditObject']:
        """
        Every reddit object (user, or subreddit) that wrote in the channel.
        :return: The participants, sorted by the name they are shown under, without regard to case.
        :rtype: list[RedditObject]
        """
        authors = {message.author for message in self.messages if message.author is not None}
        return sorted(authors, key=lambda participant: participant.nickname_or_name.lower())

    @property
    def display_name(self) -> str:
        """
        The name used to show the channel: the nickname the user gave it, otherwise the name Reddit gave it.  Reddit's
        export usually leaves direct chats unnamed, so those are named after all of their participants (under their
        nicknames where they have one), or after the room id when nobody is known to have written in them.
        :return: The display name.
        :rtype: str
        """
        if self.nickname and self.nickname.strip():
            return self.nickname
        if self.channel_name:
            return self.channel_name
        participants = self.participants
        if participants:
            return ', '.join(participant.nickname_or_name for participant in participants)
        room = (self.channel_url or '').rstrip('/').rsplit('/', 1)[-1].split(':', 1)[0].lstrip('!')
        return f'Chat {room[:_ROOM_ID_DISPLAY_LENGTH]}' if room else 'Chat'


class ChatMessage(BaseModel):
    """A single message sent in a chat channel."""

    __tablename__ = 'chat_message'

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String, unique=True)
    body = Column(Text, nullable=True)
    date_posted = Column(DateTime, nullable=True, index=True)
    date_updated = Column(DateTime, nullable=True)
    thread_parent_message_id = Column(String, nullable=True)

    channel_id = Column(ForeignKey('chat_channel.id'))
    channel = relationship('ChatChannel', back_populates='messages')
    author_id = Column(ForeignKey('reddit_object.id'), nullable=True)
    author = relationship('RedditObject', backref='chat_messages')
    export_import_id = Column(ForeignKey('export_import.id'), nullable=True)
    export_import = relationship('ExportImport', backref='chat_messages')

    def __str__(self) -> str:
        """
        Returns a readable description of the message.
        :return: The description.
        :rtype: str
        """
        return f'Chat message: {self.message_id}'

    @property
    def date_posted_display(self) -> Optional[str]:
        """
        The date the message was sent, formatted for display.
        :return: The formatted date, or None when no date is set.
        :rtype: Optional[str]
        """
        return self.get_display_datetime(self.date_posted)


class PrivateMessage(BaseModel):
    """A legacy reddit private message (inbox message) found in an export."""

    __tablename__ = 'private_message'

    id = Column(Integer, primary_key=True, autoincrement=True)
    reddit_id = Column(String(collation='NOCASE'), unique=True)
    thread_id = Column(String(collation='NOCASE'), nullable=True, index=True)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    date_sent = Column(DateTime, nullable=True, index=True)
    archived = Column(Boolean, default=False)

    sender_id = Column(ForeignKey('reddit_object.id'), nullable=True)
    sender = relationship('RedditObject', foreign_keys=sender_id, backref='sent_private_messages')
    recipient_id = Column(ForeignKey('reddit_object.id'), nullable=True)
    recipient = relationship('RedditObject', foreign_keys=recipient_id, backref='received_private_messages')
    export_import_id = Column(ForeignKey('export_import.id'), nullable=True)
    export_import = relationship('ExportImport', backref='private_messages')

    def __str__(self) -> str:
        """
        Returns a readable description of the message.
        :return: The description.
        :rtype: str
        """
        return f'Private message: {self.subject}'

    @property
    def date_sent_display(self) -> Optional[str]:
        """
        The date the message was sent, formatted for display.
        :return: The formatted date, or None when no date is set.
        :rtype: Optional[str]
        """
        return self.get_display_datetime(self.date_sent)
