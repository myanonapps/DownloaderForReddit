"""
Fills in the data a Reddit export leaves out, by looking the imported posts and comments up through a data source.

The export only holds what the account wrote: no scores, no nsfw flags, no media metadata, and nothing about the
posts the account commented on.  The hydrator fetches those ids in batches from one of the download sources, updates
the imported rows, and stores the posts that imported comments belong to.  Ids the source does not hold (deleted or
never archived) are counted and left as imported.


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
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ....data_interface.reddit_data_interface import RedditDataInterface
from ....database.models import Post, Comment, User, Subreddit
from ...html_formatting import markdown_to_html
from ... import injector
from .export_importer import ExportImportStats, ProgressCallback, attach_orphan_comments, chunked


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

DEFAULT_BATCH_SIZE = 100


def _name(item: Any, attribute: str, name_attribute: str) -> Optional[str]:
    """
    Reads a nested name, such as ``submission.author.name``, from a PRAW or adapter object.
    :param item: The submission or comment.
    :type item: Any
    :param attribute: The attribute holding the nested object, for example 'author'.
    :type attribute: str
    :param name_attribute: The name attribute of the nested object, for example 'name'.
    :type name_attribute: str
    :return: The name, or None when it is missing (as it is for deleted accounts).
    :rtype: Optional[str]
    """
    nested = getattr(item, attribute, None)
    name = getattr(nested, name_attribute, None) if nested is not None else None
    return name or None


def _created(item: Any) -> Optional[datetime]:
    """
    Reads a submission's creation time as a naive UTC datetime.
    :param item: The submission.
    :type item: Any
    :return: The creation time, or None when the source does not give one.
    :rtype: Optional[datetime]
    """
    epoch = getattr(item, 'created_utc', None) or getattr(item, 'created', None)
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).replace(tzinfo=None)


class ExportHydrator:  # pylint: disable=too-few-public-methods  # hydrate() is the single entry point
    """Updates the rows from one export import with data from a download source."""

    def __init__(self, adapter: RedditDataInterface, stop_event: Optional[threading.Event] = None,
                 batch_size: int = DEFAULT_BATCH_SIZE, progress_callback: Optional[ProgressCallback] = None) -> None:
        """
        :param adapter: The data source to look the ids up in.
        :type adapter: RedditDataInterface
        :param stop_event: When set, hydration stops after the current batch.
        :type stop_event: Optional[threading.Event]
        :param batch_size: The number of ids requested at a time.
        :type batch_size: int
        :param progress_callback: Called after each batch with a record type name and the number of ids handled.
        :type progress_callback: Optional[ProgressCallback]
        """
        self.adapter = adapter
        self.stop_event = stop_event or threading.Event()
        self.batch_size = batch_size
        self.progress_callback = progress_callback

    def hydrate(self, stats: ExportImportStats) -> ExportImportStats:
        """
        Hydrates the posts and comments of the import that produced the stats, and adds the counts to them.
        :param stats: The stats of a finished import.
        :type stats: ExportImportStats
        :return: The same stats, updated.
        :rtype: ExportImportStats
        """
        if stats.download_session_id is None:
            return stats
        with injector.get_database_handler().get_scoped_session() as session:
            self._hydrate_posts(session, stats)
            self._hydrate_comments(session, stats)
            self._add_commented_posts(session, stats)
            attach_orphan_comments(session)
            session.commit()
        stats.cancelled = stats.cancelled or self.stop_event.is_set()
        logger.info('Export hydration finished: %d posts, %d comments, %d not found',
                    stats.posts_hydrated, stats.comments_hydrated, stats.not_found)
        return stats

    def _report(self, record_type: str, count: int) -> None:
        """
        Passes batch progress to the progress callback, if there is one.
        :param record_type: The kind of record handled.
        :type record_type: str
        :param count: The number of ids in the batch.
        :type count: int
        :return: None
        :rtype: None
        """
        if self.progress_callback is not None:
            self.progress_callback(record_type, count)

    def _hydrate_posts(self, session: Session, stats: ExportImportStats) -> None:
        """
        Updates the imported posts with their score, nsfw flag, domain, url and html.
        :param session: The database session.
        :type session: Session
        :param stats: The import stats to add to.
        :type stats: ExportImportStats
        :return: None
        :rtype: None
        """
        posts = session.query(Post).filter(Post.download_session_id == stats.download_session_id).all()
        for batch in chunked(posts, self.batch_size):
            if self.stop_event.is_set():
                return
            found = {str(item.id).lower(): item for item in self.adapter.submissions_by_ids([post.reddit_id for post in batch])}
            for post in batch:
                item = found.get(post.reddit_id.lower())
                if item is None:
                    stats.not_found += 1
                    continue
                self._update_post(post, item)
                stats.posts_hydrated += 1
            session.commit()
            self._report('posts', len(batch))

    @staticmethod
    def _update_post(post: Post, item: Any) -> None:
        """
        Copies the fields the export lacks from a fetched submission onto a post.
        :param post: The imported post.
        :type post: Post
        :param item: The fetched submission.
        :type item: Any
        :return: None
        :rtype: None
        """
        post.score = getattr(item, 'score', None) or 0
        post.nsfw = bool(getattr(item, 'over_18', False))
        post.is_self = bool(getattr(item, 'is_self', post.is_self))
        post.domain = getattr(item, 'domain', None) or post.domain
        post.url = getattr(item, 'url', None) or post.url
        selftext_html = getattr(item, 'selftext_html', None)
        if selftext_html:
            post.text_html = selftext_html

    def _hydrate_comments(self, session: Session, stats: ExportImportStats) -> None:
        """
        Updates the imported comments with their score.
        :param session: The database session.
        :type session: Session
        :param stats: The import stats to add to.
        :type stats: ExportImportStats
        :return: None
        :rtype: None
        """
        comments = session.query(Comment).filter(Comment.download_session_id == stats.download_session_id).all()
        for batch in chunked(comments, self.batch_size):
            if self.stop_event.is_set():
                return
            found = {str(item.id).lower(): item for item in self.adapter.comments_by_ids([comment.reddit_id for comment in batch])}
            for comment in batch:
                item = found.get(comment.reddit_id.lower())
                if item is None:
                    stats.not_found += 1
                    continue
                comment.score = getattr(item, 'score', None) or 0
                stats.comments_hydrated += 1
            session.commit()
            self._report('comments', len(batch))

    def _add_commented_posts(self, session: Session, stats: ExportImportStats) -> None:
        """
        Stores the posts that imported comments were made on but that are not in the database.  These posts belong to
        other people, so they are stored as already extracted and are never downloaded by the import.
        :param session: The database session.
        :type session: Session
        :param stats: The import stats to add to.
        :type stats: ExportImportStats
        :return: None
        :rtype: None
        """
        rows = session.query(Comment.link_reddit_id).filter(Comment.download_session_id == stats.download_session_id,
                                                            Comment.post_id.is_(None), Comment.link_reddit_id.isnot(None)).distinct()
        link_ids = sorted({row[0].lower() for row in rows})
        for batch in chunked(link_ids, self.batch_size):
            if self.stop_event.is_set():
                return
            existing = {row[0].lower() for row in session.query(Post.reddit_id).filter(Post.reddit_id.in_(batch))}
            missing = [link_id for link_id in batch if link_id not in existing]
            if not missing:
                continue
            for item in self.adapter.submissions_by_ids(missing):
                session.add(self._make_post(session, item, stats.download_session_id))
            session.commit()
            self._report('commented posts', len(batch))

    @staticmethod
    def _make_post(session: Session, item: Any, download_session_id: int) -> Post:
        """
        Builds a post from a fetched submission.
        :param session: The database session.
        :type session: Session
        :param item: The fetched submission.
        :type item: Any
        :param download_session_id: The import's download session.
        :type download_session_id: int
        :return: The new, unsaved post.
        :rtype: Post
        """
        db = injector.get_database_handler()
        author_name = _name(item, 'author', 'name')
        subreddit_name = _name(item, 'subreddit', 'display_name')
        selftext = getattr(item, 'selftext', None) or None
        return Post(
            title=getattr(item, 'title', None),
            date_posted=_created(item),
            domain=getattr(item, 'domain', None),
            score=getattr(item, 'score', None) or 0,
            nsfw=bool(getattr(item, 'over_18', False)),
            reddit_id=str(item.id),
            url=getattr(item, 'url', None),
            permalink=getattr(item, 'permalink', None),
            is_self=bool(getattr(item, 'is_self', False)),
            text=selftext,
            text_html=getattr(item, 'selftext_html', None) or (markdown_to_html(selftext) if selftext else None),
            extracted=True,
            extraction_date=datetime.now(),
            author=db.get_or_create(User, name=author_name, session=session)[0] if author_name else None,
            subreddit=db.get_or_create(Subreddit, name=subreddit_name, session=session)[0] if subreddit_name else None,
            download_session_id=download_session_id,
        )
