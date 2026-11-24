"""
Writes the records of a Reddit data export archive into the database.

Every record type is upserted on its reddit id, so importing a newer export of the same account only adds what is new.
Rows are written in chunks, and a stop event is checked between chunks so a long import can be cancelled.


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
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from itertools import islice
from typing import Callable, Iterable, Iterator, Optional, TypeVar
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ....core.const import SUBREDDIT_OBJECT, USER_OBJECT
from ....database.models import Post, Comment, User, Subreddit, DownloadSession, ListAssociation, RedditObject, RedditObjectList
from ....database.export_models import ExportImport, ChatChannel, ChatMessage, PrivateMessage
from ...html_formatting import markdown_to_html
from ... import injector
from .export_reader import RedditExportReader, is_deleted_name, person_reference, strip_user_prefix
from .export_records import ExportPost, ExportComment, ExportChatMessage, ExportPrivateMessage


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

RecordT = TypeVar('RecordT')
ProgressCallback = Callable[[str, int], None]

_USER_NAME = re.compile(r'^[A-Za-z0-9_-]{3,20}$')
_UNTITLED = '[untitled]'
_TITLE_FROM_BODY_LENGTH = 100
_ID_QUERY_SIZE = 500  # stays below SQLite's bound parameter limit


@dataclass
class ExportImportOptions:
    """What to import from an export archive, and how."""

    account_name: str
    import_posts: bool = True
    import_comments: bool = True
    import_chats: bool = True
    import_private_messages: bool = True
    chunk_size: int = 500
    # The user list a newly created account is added to.  An account that is already in the database is left alone.
    account_list_id: Optional[int] = None


@dataclass
class ExportImportStats:  # pylint: disable=too-many-instance-attributes  # plain record of import counts
    """The outcome of an import, reported back to the GUI."""

    export_import_id: Optional[int] = None
    download_session_id: Optional[int] = None
    posts_added: int = 0
    posts_skipped: int = 0
    comments_added: int = 0
    comments_skipped: int = 0
    chat_channels_added: int = 0
    chat_messages_added: int = 0
    chat_messages_skipped: int = 0
    private_messages_added: int = 0
    private_messages_skipped: int = 0
    posts_hydrated: int = 0
    comments_hydrated: int = 0
    not_found: int = 0
    cancelled: bool = False
    new_post_ids: list[int] = field(default_factory=list)

    @property
    def total_added(self) -> int:
        """
        The number of posts, comments and messages added by the import.
        :return: The total.
        :rtype: int
        """
        return self.posts_added + self.comments_added + self.chat_messages_added + self.private_messages_added


def chunked(items: Iterable[RecordT], size: int) -> Iterator[list[RecordT]]:
    """
    Splits an iterable into lists of at most size items.
    :param items: The items to split.
    :type items: Iterable[RecordT]
    :param size: The largest number of items per list.
    :type size: int
    :return: An iterator of lists.
    :rtype: Iterator[list[RecordT]]
    """
    iterator = iter(items)
    while True:
        chunk = list(islice(iterator, max(size, 1)))
        if not chunk:
            return
        yield chunk


def attach_orphan_comments(session: Session) -> int:
    """
    Links comments that were stored without their post to that post, once the post is in the database.
    :param session: The database session to use; the caller commits.
    :type session: Session
    :return: The number of comments linked.
    :rtype: int
    """
    orphans = session.query(Comment).filter(Comment.post_id.is_(None), Comment.link_reddit_id.isnot(None)).all()
    if not orphans:
        return 0
    link_ids = {comment.link_reddit_id for comment in orphans}
    posts: dict[str, int] = {}
    for link_chunk in chunked(link_ids, _ID_QUERY_SIZE):
        for post_id, reddit_id in session.query(Post.id, Post.reddit_id).filter(Post.reddit_id.in_(link_chunk)):
            posts[reddit_id.lower()] = post_id
    linked = 0
    for comment in orphans:
        post_id = posts.get(comment.link_reddit_id.lower())
        if post_id is not None:
            comment.post_id = post_id
            linked += 1
    return linked


class RedditExportImporter:  # pylint: disable=too-many-instance-attributes,too-few-public-methods  # run() is the single entry point; the rest are lookup caches
    """Imports one export archive into the database."""

    def __init__(self, reader: RedditExportReader, options: ExportImportOptions,
                 stop_event: Optional[threading.Event] = None, progress_callback: Optional[ProgressCallback] = None) -> None:
        """
        :param reader: The open archive to import.
        :type reader: RedditExportReader
        :param options: What to import.
        :type options: ExportImportOptions
        :param stop_event: When set, the import stops after the current chunk.
        :type stop_event: Optional[threading.Event]
        :param progress_callback: Called after each chunk with a record type name and the number of records handled.
        :type progress_callback: Optional[ProgressCallback]
        """
        self.reader = reader
        self.options = options
        self.stop_event = stop_event or threading.Event()
        self.progress_callback = progress_callback
        self.stats = ExportImportStats()
        self._users: dict[str, User] = {}
        self._subreddits: dict[str, Subreddit] = {}
        self._channels: dict[str, ChatChannel] = {}
        self._owner: Optional[User] = None

    def run(self) -> ExportImportStats:
        """
        Runs the import.
        :return: What was imported.
        :rtype: ExportImportStats
        """
        with injector.get_database_handler().get_scoped_session() as session:
            download_session = DownloadSession(name=f'Export import: {self.options.account_name}', start_time=datetime.now(),
                                               extraction_thread_count=0, download_thread_count=0)
            self._owner = self._get_owner(session)
            export_import = ExportImport(file_name=os.path.basename(self.reader.zip_path), file_sha256=self.reader.file_sha256(),
                                         owner=self._owner, download_session=download_session)
            session.add_all([download_session, export_import])
            session.commit()
            self.stats.export_import_id = export_import.id
            self.stats.download_session_id = download_session.id

            steps = (
                (self.options.import_posts, self._import_posts),
                (self.options.import_comments, self._import_comments),
                (self.options.import_chats, self._import_chat_messages),
                (self.options.import_private_messages, self._import_private_messages),
            )
            for enabled, step in steps:
                if enabled and not self._stopped():
                    step(session, export_import)

            attach_orphan_comments(session)
            export_import.post_count = self.stats.posts_added
            export_import.comment_count = self.stats.comments_added
            export_import.chat_message_count = self.stats.chat_messages_added
            export_import.private_message_count = self.stats.private_messages_added
            download_session.end_time = datetime.now()
            session.commit()
        self.stats.cancelled = self.stop_event.is_set()
        logger.info('Export import finished: %s', self.stats)
        return self.stats

    def _stopped(self) -> bool:
        """
        Whether the import has been asked to stop.
        :return: True when the stop event is set.
        :rtype: bool
        """
        return self.stop_event.is_set()

    def _report(self, record_type: str, count: int) -> None:
        """
        Passes chunk progress to the progress callback, if there is one.
        :param record_type: The kind of record handled, for example 'posts'.
        :type record_type: str
        :param count: The number of records in the chunk.
        :type count: int
        :return: None
        :rtype: None
        """
        if self.progress_callback is not None:
            self.progress_callback(record_type, count)

    def _get_owner(self, session: Session) -> User:
        """
        Returns the account the export belongs to, creating it if needed.  As when a user is added to a list, a new
        owner is created significant, and an existing user is left as it is.  A new owner is added to the user list
        named in the options, and takes that list's download defaults.
        :param session: The database session.
        :type session: Session
        :return: The owner.
        :rtype: User
        :raises ValueError: When the account name is not a valid reddit user name, or the list id names no user list.
        """
        account_list = None
        if self.options.account_list_id is not None:
            account_list = session.query(RedditObjectList).filter(RedditObjectList.id == self.options.account_list_id) \
                .filter(RedditObjectList.list_type == USER_OBJECT).first()
            if account_list is None:
                raise ValueError(f'There is no user list with id {self.options.account_list_id}')
        name = strip_user_prefix(self.options.account_name)
        if not name or not _USER_NAME.match(name) or is_deleted_name(name):
            raise ValueError(f'{self.options.account_name!r} is not a valid reddit user name')
        defaults = account_list.get_default_dict() if account_list is not None else None
        owner = self._get_user(session, name, significant=True, defaults=defaults)
        if account_list is not None and owner in session.new:
            session.add(ListAssociation(reddit_object=owner, reddit_object_list=account_list))
            logger.info('Added %s to user list %s', owner.name, account_list.name)
        return owner

    def _get_person(self, session: Session, name: Optional[str]) -> RedditObject:
        """
        Returns the reddit object for a person named in a conversation, creating it, insignificant, if needed.  Every
        name gets one: a subreddit sender (modmail) becomes a Subreddit, a deleted or missing account the shared
        deleted placeholder user, and any other name a User.
        :param session: The database session.
        :type session: Session
        :param name: The name as the export gives it.
        :type name: Optional[str]
        :return: The reddit object.
        :rtype: RedditObject
        """
        object_type, bare_name = person_reference(name)
        if object_type == SUBREDDIT_OBJECT:
            return self._get_subreddit(session, bare_name)
        return self._get_user(session, bare_name)

    def _get_user(self, session: Session, name: str, significant: bool = False,
                  defaults: Optional[dict[str, object]] = None) -> User:
        """
        Returns the User with a name, creating it if needed.
        :param session: The database session.
        :type session: Session
        :param name: The bare user name.
        :type name: str
        :param significant: Whether a newly created user is significant.  An existing user's flag is never changed.
        :type significant: bool
        :param defaults: Download settings for a newly created user, usually a list's defaults.  Never applied to an
                         existing user.
        :type defaults: Optional[dict[str, object]]
        :return: The user.
        :rtype: User
        """
        key = name.lower()
        user = self._users.get(key)
        if user is None:
            user = session.query(User).filter(User.name == name).first()
            if user is None:
                user = User(name=name, significant=significant, **(defaults or {}))
                session.add(user)
            self._users[key] = user
        return user

    def _get_subreddit(self, session: Session, name: Optional[str]) -> Optional[Subreddit]:
        """
        Returns the Subreddit with a name, creating it if needed.
        :param session: The database session.
        :type session: Session
        :param name: The subreddit name, with or without an 'r/' prefix.
        :type name: Optional[str]
        :return: The subreddit, or None when no name is given.
        :rtype: Optional[Subreddit]
        """
        if not name:
            return None
        name = name.strip().removeprefix('/r/').removeprefix('r/')
        if not name:
            return None
        key = name.lower()
        subreddit = self._subreddits.get(key)
        if subreddit is None:
            subreddit = session.query(Subreddit).filter(Subreddit.name == name).first()
            if subreddit is None:
                subreddit = Subreddit(name=name)
                session.add(subreddit)
            self._subreddits[key] = subreddit
        return subreddit

    @staticmethod
    def _existing_ids(session: Session, column: object, ids: list[str]) -> set[str]:
        """
        Returns which of the ids are already stored, lowercased because reddit ids are compared without case.
        :param session: The database session.
        :type session: Session
        :param column: The id column to check, for example Post.reddit_id.
        :type column: object
        :param ids: The ids to look for.
        :type ids: list[str]
        :return: The ids that exist.
        :rtype: set[str]
        """
        found: set[str] = set()
        for id_chunk in chunked(ids, _ID_QUERY_SIZE):
            found.update(row[0].lower() for row in session.query(column).filter(column.in_(id_chunk)))
        return found

    def _import_posts(self, session: Session, export_import: ExportImport) -> None:
        """
        Imports posts.csv.
        :param session: The database session.
        :type session: Session
        :param export_import: The import being run.
        :type export_import: ExportImport
        :return: None
        :rtype: None
        """
        for chunk in chunked(self.reader.iter_posts(), self.options.chunk_size):
            if self._stopped():
                return
            existing = self._existing_ids(session, Post.reddit_id, [record.reddit_id for record in chunk])
            new_posts = []
            for record in chunk:
                if record.reddit_id.lower() in existing:
                    self.stats.posts_skipped += 1
                    continue
                existing.add(record.reddit_id.lower())
                new_posts.append(self._make_post(session, record, export_import))
            session.add_all(new_posts)
            session.commit()
            self.stats.posts_added += len(new_posts)
            self.stats.new_post_ids.extend(post.id for post in new_posts)
            self._report('posts', len(chunk))

    def _make_post(self, session: Session, record: ExportPost, export_import: ExportImport) -> Post:
        """
        Builds a Post from an exported post.  It is left unextracted so the normal extraction can download its media.
        :param session: The database session.
        :type session: Session
        :param record: The exported post.
        :type record: ExportPost
        :param export_import: The import being run.
        :type export_import: ExportImport
        :return: The new, unsaved post.
        :rtype: Post
        """
        subreddit = self._get_subreddit(session, record.subreddit)
        is_self = record.is_self
        url = record.url or record.permalink
        if is_self:
            domain = f'self.{subreddit.name}' if subreddit is not None else 'self'
        else:
            domain = urlparse(url).netloc.lower().removeprefix('www.') if url else None
        title = record.title or (record.body or '')[:_TITLE_FROM_BODY_LENGTH] or _UNTITLED
        return Post(
            title=title,
            date_posted=record.date_posted,
            domain=domain,
            score=0,
            reddit_id=record.reddit_id,
            url=url,
            is_self=is_self,
            text=record.body,
            text_html=markdown_to_html(record.body) if record.body else None,
            extracted=False,
            author=self._owner,
            subreddit=subreddit,
            significant_reddit_object=self._owner,
            download_session_id=export_import.download_session_id,
        )

    def _import_comments(self, session: Session, export_import: ExportImport) -> None:
        """
        Imports comments.csv, then links replies to their parent comments once all comments are stored.
        :param session: The database session.
        :type session: Session
        :param export_import: The import being run.
        :type export_import: ExportImport
        :return: None
        :rtype: None
        """
        parents: dict[str, str] = {}
        for chunk in chunked(self.reader.iter_comments(), self.options.chunk_size):
            if self._stopped():
                break
            existing = self._existing_ids(session, Comment.reddit_id, [record.reddit_id for record in chunk])
            new_comments = []
            for record in chunk:
                if record.reddit_id.lower() in existing:
                    self.stats.comments_skipped += 1
                    continue
                existing.add(record.reddit_id.lower())
                new_comments.append(self._make_comment(session, record, export_import))
                if record.parent_reddit_id:
                    parents[record.reddit_id.lower()] = record.parent_reddit_id.lower()
            session.add_all(new_comments)
            session.commit()
            self.stats.comments_added += len(new_comments)
            self._report('comments', len(chunk))
        self._link_parent_comments(session, parents)

    def _make_comment(self, session: Session, record: ExportComment, export_import: ExportImport) -> Comment:
        """
        Builds a Comment from an exported comment.
        :param session: The database session.
        :type session: Session
        :param record: The exported comment.
        :type record: ExportComment
        :param export_import: The import being run.
        :type export_import: ExportImport
        :return: The new, unsaved comment.
        :rtype: Comment
        """
        body = record.body
        if record.media and (not body or record.media not in body):
            body = f'{body}\n\n{record.media}' if body else record.media
        return Comment(
            body=body,
            body_html=markdown_to_html(body) if body else None,
            score=0,
            date_posted=record.date_posted,
            reddit_id=record.reddit_id,
            link_reddit_id=record.link_reddit_id,
            author=self._owner,
            subreddit=self._get_subreddit(session, record.subreddit),
            download_session_id=export_import.download_session_id,
        )

    @staticmethod
    def _link_parent_comments(session: Session, parents: dict[str, str]) -> None:
        """
        Sets parent_id on the imported replies whose parent comment is stored.
        :param session: The database session.
        :type session: Session
        :param parents: Imported comment reddit id mapped to its parent's reddit id, both lowercase.
        :type parents: dict[str, str]
        :return: None
        :rtype: None
        """
        if not parents:
            return
        ids: dict[str, int] = {}
        for id_chunk in chunked(set(parents) | set(parents.values()), _ID_QUERY_SIZE):
            for comment_id, reddit_id in session.query(Comment.id, Comment.reddit_id).filter(Comment.reddit_id.in_(id_chunk)):
                ids[reddit_id.lower()] = comment_id
        for child, parent in parents.items():
            if child in ids and parent in ids:
                session.query(Comment).filter(Comment.id == ids[child]).update({Comment.parent_id: ids[parent]},
                                                                                synchronize_session=False)
        session.commit()

    def _import_chat_messages(self, session: Session, export_import: ExportImport) -> None:
        """
        Imports chat_history.csv, grouping the messages into their channels.
        :param session: The database session.
        :type session: Session
        :param export_import: The import being run.
        :type export_import: ExportImport
        :return: None
        :rtype: None
        """
        for chunk in chunked(self.reader.iter_chat_messages(), self.options.chunk_size):
            if self._stopped():
                return
            existing = self._existing_ids(session, ChatMessage.message_id, [record.message_id for record in chunk])
            new_messages = []
            for record in chunk:
                if record.message_id.lower() in existing:
                    self.stats.chat_messages_skipped += 1
                    continue
                existing.add(record.message_id.lower())
                new_messages.append(self._make_chat_message(session, record, export_import))
            session.add_all(new_messages)
            session.commit()
            self.stats.chat_messages_added += len(new_messages)
            self._report('chat messages', len(chunk))

    def _get_channel(self, session: Session, record: ExportChatMessage) -> ChatChannel:
        """
        Returns the channel a chat message belongs to, creating it if needed.  Channels are matched by url, so exports
        of different accounts that took part in the same channel share it.
        :param session: The database session.
        :type session: Session
        :param record: The exported chat message.
        :type record: ExportChatMessage
        :return: The channel.
        :rtype: ChatChannel
        """
        channel = self._channels.get(record.channel_url)
        if channel is None:
            channel = session.query(ChatChannel).filter(ChatChannel.channel_url == record.channel_url).first()
            if channel is None:
                channel = ChatChannel(channel_url=record.channel_url, channel_name=record.channel_name,
                                      subreddit=self._get_subreddit(session, record.subreddit),
                                      conversation_type=record.conversation_type)
                session.add(channel)
                self.stats.chat_channels_added += 1
            self._channels[record.channel_url] = channel
        if channel.channel_name is None and record.channel_name:
            channel.channel_name = record.channel_name
        if channel.subreddit is None and record.subreddit:
            channel.subreddit = self._get_subreddit(session, record.subreddit)
        return channel

    def _make_chat_message(self, session: Session, record: ExportChatMessage, export_import: ExportImport) -> ChatMessage:
        """
        Builds a ChatMessage from an exported chat message.
        :param session: The database session.
        :type session: Session
        :param record: The exported chat message.
        :type record: ExportChatMessage
        :param export_import: The import being run.
        :type export_import: ExportImport
        :return: The new, unsaved message.
        :rtype: ChatMessage
        """
        return ChatMessage(
            message_id=record.message_id,
            channel=self._get_channel(session, record),
            author=self._get_person(session, record.author),
            body=record.body,
            date_posted=record.date_posted,
            date_updated=record.date_updated,
            thread_parent_message_id=record.thread_parent_message_id,
            export_import=export_import,
        )

    def _import_private_messages(self, session: Session, export_import: ExportImport) -> None:
        """
        Imports messages.csv and messages_archive.csv.
        :param session: The database session.
        :type session: Session
        :param export_import: The import being run.
        :type export_import: ExportImport
        :return: None
        :rtype: None
        """
        for chunk in chunked(self.reader.iter_private_messages(), self.options.chunk_size):
            if self._stopped():
                return
            existing = self._existing_ids(session, PrivateMessage.reddit_id, [record.reddit_id for record in chunk])
            new_messages = []
            for record in chunk:
                if record.reddit_id.lower() in existing:
                    self.stats.private_messages_skipped += 1
                    continue
                existing.add(record.reddit_id.lower())
                new_messages.append(self._make_private_message(session, record, export_import))
            session.add_all(new_messages)
            session.commit()
            self.stats.private_messages_added += len(new_messages)
            self._report('private messages', len(chunk))

    def _make_private_message(self, session: Session, record: ExportPrivateMessage,
                              export_import: ExportImport) -> PrivateMessage:
        """
        Builds a PrivateMessage from an exported message.
        :param session: The database session.
        :type session: Session
        :param record: The exported message.
        :type record: ExportPrivateMessage
        :param export_import: The import being run.
        :type export_import: ExportImport
        :return: The new, unsaved message.
        :rtype: PrivateMessage
        """
        return PrivateMessage(
            reddit_id=record.reddit_id,
            thread_id=record.thread_id,
            sender=self._get_person(session, record.sender),
            recipient=self._get_person(session, record.recipient),
            subject=record.subject,
            body=record.body,
            date_sent=record.date_sent,
            archived=record.archived,
            export_import=export_import,
        )
