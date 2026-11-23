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
from typing import Optional

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from .models import BaseModel


_ROOM_ID_DISPLAY_LENGTH = 10


class ExportImport(BaseModel):
    """A single import of a Reddit data export archive."""

    __tablename__ = 'export_import'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String)
    file_sha256 = Column(String, index=True)
    account_name = Column(String(collation='NOCASE'))
    import_date = Column(DateTime, default=datetime.now)
    post_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    chat_message_count = Column(Integer, default=0)
    private_message_count = Column(Integer, default=0)

    download_session_id = Column(ForeignKey('download_session.id'), nullable=True)
    download_session = relationship('DownloadSession', backref='export_imports')

    def __str__(self) -> str:
        """
        Returns a readable description of the import.
        :return: The description.
        :rtype: str
        """
        return f'Export import: {self.account_name} ({self.file_name})'

    @property
    def import_date_display(self) -> Optional[str]:
        """
        The import date formatted for display.
        :return: The formatted date, or None when no date is set.
        :rtype: Optional[str]
        """
        return self.get_display_datetime(self.import_date)


class ChatChannel(BaseModel):
    """A chat channel (direct chat, group chat or subreddit chat) found in an export."""

    __tablename__ = 'chat_channel'

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_url = Column(String, unique=True)
    channel_name = Column(String(collation='NOCASE'), nullable=True)
    subreddit_name = Column(String(collation='NOCASE'), nullable=True)
    conversation_type = Column(String, nullable=True)

    export_import_id = Column(ForeignKey('export_import.id'), nullable=True)
    export_import = relationship('ExportImport', backref='chat_channels')
    messages = relationship('ChatMessage', back_populates='channel')

    def __str__(self) -> str:
        """
        Returns a readable description of the channel.
        :return: The channel name, or its url when it has no name.
        :rtype: str
        """
        return f'Chat: {self.display_name}'

    @property
    def participant_names(self) -> list[str]:
        """
        The people who wrote in the channel, other than the account the export belongs to.
        :return: The names, sorted without regard to case.
        :rtype: list[str]
        """
        owner = (self.export_import.account_name or '').lower() if self.export_import is not None else ''
        names = {message.author_name for message in self.messages if message.author_name}
        return sorted((name for name in names if name.lower() != owner), key=str.lower)

    @property
    def display_name(self) -> str:
        """
        The name used to show the channel.  Reddit's export usually leaves direct chats unnamed, so they are named
        after the other participants, or after the room id when only the account owner wrote in them.
        :return: The display name.
        :rtype: str
        """
        if self.channel_name:
            return self.channel_name
        participants = self.participant_names
        if participants:
            return ', '.join(participants)
        room = (self.channel_url or '').rstrip('/').rsplit('/', 1)[-1].split(':', 1)[0].lstrip('!')
        return f'Chat {room[:_ROOM_ID_DISPLAY_LENGTH]}' if room else 'Chat'


class ChatMessage(BaseModel):
    """A single message sent in a chat channel."""

    __tablename__ = 'chat_message'

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String, unique=True)
    author_name = Column(String(collation='NOCASE'), nullable=True)
    body = Column(Text, nullable=True)
    date_posted = Column(DateTime, nullable=True, index=True)
    date_updated = Column(DateTime, nullable=True)
    thread_parent_message_id = Column(String, nullable=True)

    channel_id = Column(ForeignKey('chat_channel.id'))
    channel = relationship('ChatChannel', back_populates='messages')
    author_id = Column(ForeignKey('user.id'), nullable=True)
    author = relationship('User', backref='chat_messages')
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
    permalink = Column(String, nullable=True)
    sender_name = Column(String(collation='NOCASE'), nullable=True)
    recipient_name = Column(String(collation='NOCASE'), nullable=True)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    date_sent = Column(DateTime, nullable=True, index=True)
    archived = Column(Boolean, default=False)

    sender_id = Column(ForeignKey('user.id'), nullable=True)
    sender = relationship('User', foreign_keys=sender_id, backref='sent_private_messages')
    recipient_id = Column(ForeignKey('user.id'), nullable=True)
    recipient = relationship('User', foreign_keys=recipient_id, backref='received_private_messages')
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
