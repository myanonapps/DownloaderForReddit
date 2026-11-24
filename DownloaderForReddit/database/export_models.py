"""
Database models for data imported from a Reddit data export (the "Request your data" zip archive).

These hold the conversations (chat and legacy private messages) that cannot be retrieved through any of the
download sources, along with a record of each import that was performed.  Media linked in a message is extracted into
Content rows tied to that message, and downloaded with the settings of the message's author, into the author's folder.


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

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Enum, distinct
from sqlalchemy.orm import relationship

from .models import BaseModel, RedditObject, Subreddit
from ..core.errors import Error
from ..utils import injector, system_util

if TYPE_CHECKING:
    from .models import User


_ROOM_ID_DISPLAY_LENGTH = 10
_TITLE_DATE_FORMAT = '%Y-%m-%d %H-%M-%S'
DELETED_PERSON = '[deleted]'
NO_SUBJECT = '[no subject]'


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
        return self.room_name

    @property
    def room_name(self) -> str:
        """
        A name made from the channel's room id, for a channel that has no other name.
        :return: 'Chat' followed by the start of the room id, or just 'Chat' when the url holds no room id.
        :rtype: str
        """
        room = (self.channel_url or '').rstrip('/').rsplit('/', 1)[-1].split(':', 1)[0].lstrip('!')
        return f'Chat {room[:_ROOM_ID_DISPLAY_LENGTH]}' if room else 'Chat'


class ImportedMessage(BaseModel):
    """
    What chat messages and private messages share as sources of downloadable content.

    A message's media links are extracted into Content rows tied to the message.  The extraction state columns mirror
    those of a comment.  The naming properties (title, date paths, author, subreddit) let the file naming tokens used
    for posts resolve for a message, so message content is named and saved with its author's post settings, in the
    author's own folder.
    """

    __abstract__ = True

    extracted = Column(Boolean, default=False)
    extraction_date = Column(DateTime, nullable=True)
    extraction_error = Column(Enum(Error), nullable=True)
    error_message = Column(String, nullable=True)

    domain: Optional[str] = None  # read by the content filter's reddit video check; a message has no link domain

    def _message_date(self) -> Optional[datetime]:
        """
        Returns the date the message was sent.
        :return: The date, or None when the export gave none.
        :rtype: Optional[datetime]
        :raises NotImplementedError: When a subclass does not override it.
        """
        raise NotImplementedError

    def _message_author(self) -> Optional[RedditObject]:
        """
        Returns the reddit object that wrote the message.
        :return: The author: a user, or a subreddit for modmail; None for a row that could not be linked.
        :rtype: Optional[RedditObject]
        :raises NotImplementedError: When a subclass does not override it.
        """
        raise NotImplementedError

    def _message_import(self) -> Optional[ExportImport]:
        """
        Returns the import that first stored the message.
        :return: The import, or None for a row that is not linked to one.
        :rtype: Optional[ExportImport]
        :raises NotImplementedError: When a subclass does not override it.
        """
        raise NotImplementedError

    def _conversation_name(self) -> str:
        """
        Returns the name of the conversation the message belongs to.
        :return: The conversation name.
        :rtype: str
        :raises NotImplementedError: When a subclass does not override it.
        """
        raise NotImplementedError

    def _message_subreddit(self) -> Optional[Subreddit]:
        """
        Returns the subreddit the message belongs to: the author, when the author is a subreddit (modmail).
        :return: The subreddit, or None.
        :rtype: Optional[Subreddit]
        """
        author = self._message_author()
        return author if isinstance(author, Subreddit) else None

    @property
    def message_date(self) -> Optional[datetime]:
        """
        The date the message was sent.
        :return: The date, or None when the export gave none.
        :rtype: Optional[datetime]
        """
        return self._message_date()

    @property
    def message_author(self) -> Optional[RedditObject]:
        """
        The reddit object that wrote the message.
        :return: The author, or None for a row that could not be linked.
        :rtype: Optional[RedditObject]
        """
        return self._message_author()

    @property
    def conversation_name(self) -> str:
        """
        The name of the conversation the message belongs to.
        :return: The conversation name.
        :rtype: str
        """
        return self._conversation_name()

    @property
    def subreddit(self) -> Optional[Subreddit]:
        """
        The subreddit the message belongs to: a subreddit chat's subreddit, or a subreddit that sent the message.
        :return: The subreddit, or None.
        :rtype: Optional[Subreddit]
        """
        return self._message_subreddit()

    @property
    def significant_reddit_object(self) -> Optional[RedditObject]:
        """
        The message's author, whose download settings decide whether and how the message's content is downloaded, as
        a significant reddit object's settings do for a post.  An import adds every user found in its conversations to
        the chosen list, so these are normally that list's settings, and the content is saved in the author's folder.
        A subreddit (modmail) author's own settings and folder are used.
        :return: The author, or None for a row that could not be linked.
        :rtype: Optional[RedditObject]
        """
        return self._message_author()

    @property
    def import_owner(self) -> Optional['User']:
        """
        The account whose export first stored the message.
        :return: The import's owner, or None when the message is not linked to an import with an owner.
        :rtype: Optional[User]
        """
        export_import = self._message_import()
        return export_import.owner if export_import is not None else None

    @property
    def title(self) -> str:
        """
        The title message content is named after: the conversation name followed by the time the message was sent.
        :return: The title.
        :rtype: str
        """
        date = self._message_date()
        name = self._conversation_name()
        return f'{name} {date.strftime(_TITLE_DATE_FORMAT)}' if date is not None else name

    @property
    def short_title(self) -> str:
        """
        The title shortened to the length set for short titles.
        :return: The short title.
        :rtype: str
        """
        length = injector.get_settings_manager().short_title_char_length
        return self.title[:length] if length > 0 else self.title

    @property
    def sanitized_title(self) -> str:
        """
        The title with the characters that file names cannot hold replaced.
        :return: The sanitized title.
        :rtype: str
        """
        return system_util.clean(self.title)

    @property
    def sanitized_short_title(self) -> str:
        """
        The short title with the characters that file names cannot hold replaced.
        :return: The sanitized short title.
        :rtype: str
        """
        return system_util.clean(self.short_title)

    @property
    def date_posted_path(self) -> Optional[str]:
        """
        The date the message was sent, formatted for use in a file path.
        :return: The formatted date, or None when no date is set.
        :rtype: Optional[str]
        """
        return self.get_path_date(self._message_date())

    @property
    def datetime_posted_path(self) -> Optional[str]:
        """
        The date and time the message was sent, formatted for use in a file path.
        :return: The formatted date and time, or None when no date is set.
        :rtype: Optional[str]
        """
        return self.get_path_datetime(self._message_date())

    def set_extracted(self) -> None:
        """
        Records that the message's links were extracted, and commits.
        :return: None
        :rtype: None
        """
        self.extracted = True
        self.extraction_date = datetime.now()
        self.extraction_error = None
        self.error_message = None
        self.get_session().commit()

    def set_extraction_failed(self, error: Error, message: str) -> None:
        """
        Records that extracting the message's links failed, and commits.
        :param error: The kind of failure.
        :type error: Error
        :param message: A description of the failure.
        :type message: str
        :return: None
        :rtype: None
        """
        self.extracted = False
        self.extraction_date = datetime.now()
        self.extraction_error = error
        self.error_message = message
        self.get_session().commit()


class ChatMessage(ImportedMessage):
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

    @property
    def reddit_id(self) -> str:
        """
        The message's id, under the name the media id naming token reads.
        :return: The chat message id.
        :rtype: str
        """
        return self.message_id

    def _message_date(self) -> Optional[datetime]:
        """
        Returns the date the message was sent.
        :return: The date, or None when the export gave none.
        :rtype: Optional[datetime]
        """
        return self.date_posted

    def _message_author(self) -> Optional[RedditObject]:
        """
        Returns the reddit object that wrote the message.
        :return: The author, or None for a row that could not be linked.
        :rtype: Optional[RedditObject]
        """
        return self.author

    def _message_import(self) -> Optional[ExportImport]:
        """
        Returns the import that first stored the message.
        :return: The import, or None.
        :rtype: Optional[ExportImport]
        """
        return self.export_import

    def _message_subreddit(self) -> Optional[Subreddit]:
        """
        Returns a subreddit chat's subreddit, otherwise the subreddit that wrote the message, if any.
        :return: The subreddit, or None.
        :rtype: Optional[Subreddit]
        """
        if self.channel is not None and self.channel.subreddit is not None:
            return self.channel.subreddit
        return super()._message_subreddit()

    def _conversation_name(self) -> str:
        """
        Returns the channel's display name.  The participants of an unnamed channel are found with one query instead of
        by loading every message in the channel, since this runs for each message that has media.
        :return: The channel name.
        :rtype: str
        """
        channel = self.channel
        if channel is None:
            return 'Chat'
        session = self.get_session()
        if (channel.nickname and channel.nickname.strip()) or channel.channel_name or session is None:
            return channel.display_name
        author_ids = session.query(distinct(ChatMessage.author_id)).filter(ChatMessage.channel_id == channel.id)
        participants = session.query(RedditObject).filter(RedditObject.id.in_(author_ids)).all()
        if not participants:
            return channel.room_name
        return ', '.join(sorted((participant.nickname_or_name for participant in participants), key=str.lower))


class PrivateMessage(ImportedMessage):
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

    @property
    def author(self) -> Optional[RedditObject]:
        """
        The sender, under the name the author naming tokens read.
        :return: The sender, or None for a row that could not be linked.
        :rtype: Optional[RedditObject]
        """
        return self.sender

    def _message_date(self) -> Optional[datetime]:
        """
        Returns the date the message was sent.
        :return: The date, or None when the export gave none.
        :rtype: Optional[datetime]
        """
        return self.date_sent

    def _message_author(self) -> Optional[RedditObject]:
        """
        Returns the sender.
        :return: The sender, or None for a row that could not be linked.
        :rtype: Optional[RedditObject]
        """
        return self.sender

    def _message_import(self) -> Optional[ExportImport]:
        """
        Returns the import that first stored the message.
        :return: The import, or None.
        :rtype: Optional[ExportImport]
        """
        return self.export_import

    def _conversation_name(self) -> str:
        """
        Returns the message's subject, which names its thread.
        :return: The subject, or a placeholder when the message has none.
        :rtype: str
        """
        return self.subject.strip() if self.subject and self.subject.strip() else NO_SUBJECT
