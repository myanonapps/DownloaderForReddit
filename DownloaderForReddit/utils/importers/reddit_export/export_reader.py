"""
Reads a Reddit data export archive (the zip of csv files Reddit provides on request).

The archive is read in place: members are streamed straight out of the zip and nothing is extracted to disk.  Columns
are matched by name, not position, so reordered or extra columns are tolerated.  Columns that hold personal data the
application has no use for (ip addresses, payment details) are never read.


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

import csv
import hashlib
import io
import logging
import os
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from types import TracebackType
from typing import Iterator, Optional

from . import InvalidExportError
from .export_records import (ExportPost, ExportComment, ExportPrivateMessage, ExportChatMessage, ExportManifest,
                             POSTS_FILE, COMMENTS_FILE, MESSAGES_FILE, MESSAGES_ARCHIVE_FILE, CHAT_HISTORY_FILE,
                             STATISTICS_FILE, KNOWN_FILES, CONTENT_FILES)


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

_PERMALINK_POST_ID = re.compile(r'/comments/([a-z0-9]+)', re.IGNORECASE)
_FULLNAME_PREFIX = re.compile(r'^t\d_', re.IGNORECASE)
_ACCOUNT_NAME_STATISTICS = ('account name', 'account_name', 'username', 'user name')
_HASH_CHUNK_SIZE = 1024 * 1024
_REDDIT_ORIGIN = 'https://www.reddit.com'


def _raise_csv_field_limit() -> None:
    """
    Raises the csv module's field size limit so that very long post and message bodies can be read.
    :return: None
    :rtype: None
    """
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


_raise_csv_field_limit()


def parse_export_date(value: Optional[str]) -> Optional[datetime]:
    """
    Parses a date from the export into a naive UTC datetime, which is how dates are stored elsewhere in the database.
    The export normally uses 'YYYY-MM-DD HH:MM:SS UTC', but ISO 8601 strings and epoch seconds are accepted too.
    :param value: The raw date text.
    :type value: Optional[str]
    :return: The parsed datetime, or None when the value is empty or cannot be parsed.
    :rtype: Optional[datetime]
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromtimestamp(float(text), tz=timezone.utc).replace(tzinfo=None)
    except ValueError:
        pass
    if text.upper().endswith(' UTC'):
        text = text[:-4]
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        logger.debug('Unparseable export date: %s', value)
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def strip_fullname(value: Optional[str]) -> Optional[str]:
    """
    Removes a reddit type prefix ('t1_', 't3_', ...) from an id.
    :param value: An id or fullname.
    :type value: Optional[str]
    :return: The bare id, or None when the value is empty.
    :rtype: Optional[str]
    """
    if not value or not value.strip():
        return None
    return _FULLNAME_PREFIX.sub('', value.strip())


def post_id_from_permalink(permalink: Optional[str]) -> Optional[str]:
    """
    Extracts the submission id from a reddit permalink such as 'https://www.reddit.com/r/sub/comments/abc123/title/'.
    :param permalink: The permalink.
    :type permalink: Optional[str]
    :return: The submission id, or None when the permalink does not contain one.
    :rtype: Optional[str]
    """
    if not permalink:
        return None
    match = _PERMALINK_POST_ID.search(permalink)
    return match.group(1) if match else None


def absolute_reddit_url(value: Optional[str]) -> Optional[str]:
    """
    Makes a site-relative reddit link absolute.  The export gives text posts' urls as paths such as
    '/r/sub/comments/abc123/title/'.
    :param value: The link.
    :type value: Optional[str]
    :return: The absolute link, the value unchanged when it is already absolute, or None when it is empty.
    :rtype: Optional[str]
    """
    if not value:
        return None
    if value.startswith('/') and not value.startswith('//'):
        return f'{_REDDIT_ORIGIN}{value}'
    return value


def _first(row: dict[str, str], *keys: str) -> Optional[str]:
    """
    Returns the first non-empty value among several possible column names, since column names have varied between
    export versions.
    :param row: A csv row with lowercase keys.
    :type row: dict[str, str]
    :param keys: Candidate column names, most likely first.
    :type keys: str
    :return: The stripped value, or None when none of the columns hold a value.
    :rtype: Optional[str]
    """
    for key in keys:
        value = row.get(key)
        if value is not None and value.strip():
            return value.strip()
    return None


def _text(row: dict[str, str], *keys: str) -> Optional[str]:
    """
    Like _first, but keeps the value's inner whitespace and line breaks, for body text.
    :param row: A csv row with lowercase keys.
    :type row: dict[str, str]
    :param keys: Candidate column names, most likely first.
    :type keys: str
    :return: The value, or None when none of the columns hold a value.
    :rtype: Optional[str]
    """
    for key in keys:
        value = row.get(key)
        if value is not None and value.strip():
            return value
    return None


class RedditExportReader:
    """
    Streams records out of a Reddit data export archive.  Use it as a context manager, or call close() when done.
    """

    def __init__(self, zip_path: str) -> None:
        """
        Opens the archive and indexes the csv files it contains.
        :param zip_path: The path to the export zip file.
        :type zip_path: str
        :raises InvalidExportError: When the file is not a zip archive or holds none of the known export files.
        """
        self.zip_path = zip_path
        try:
            self._zip = zipfile.ZipFile(zip_path)  # pylint: disable=consider-using-with  # kept open for the reader's lifetime, closed in close()
        except (zipfile.BadZipFile, OSError) as error:
            raise InvalidExportError(f'Not a readable zip archive: {zip_path}') from error
        self._members: dict[str, str] = {}
        for info in self._zip.infolist():
            if info.is_dir():
                continue
            base_name = os.path.basename(info.filename).lower()
            # Exports sometimes nest the files in a folder; the first match for each name wins.
            self._members.setdefault(base_name, info.filename)
        if not any(name in self._members for name in CONTENT_FILES):
            self._zip.close()
            raise InvalidExportError(f'No Reddit export files found in: {zip_path}')

    def __enter__(self) -> 'RedditExportReader':
        """
        Enters the context manager.
        :return: This reader.
        :rtype: RedditExportReader
        """
        return self

    def __exit__(self, exc_type: Optional[type[BaseException]], exc_value: Optional[BaseException],
                 traceback: Optional[TracebackType]) -> None:
        """
        Closes the archive on leaving the context manager.
        :param exc_type: The exception type, if one was raised.
        :type exc_type: Optional[type[BaseException]]
        :param exc_value: The exception, if one was raised.
        :type exc_value: Optional[BaseException]
        :param traceback: The traceback, if an exception was raised.
        :type traceback: Optional[TracebackType]
        :return: None
        :rtype: None
        """
        self.close()

    def close(self) -> None:
        """
        Closes the archive.
        :return: None
        :rtype: None
        """
        self._zip.close()

    def has_file(self, file_name: str) -> bool:
        """
        Returns whether the archive contains a csv file.
        :param file_name: The csv file name, for example 'posts.csv'.
        :type file_name: str
        :return: True when the file is present.
        :rtype: bool
        """
        return file_name.lower() in self._members

    def iter_rows(self, file_name: str) -> Iterator[dict[str, str]]:
        """
        Yields the rows of one csv file as dicts with lowercase, stripped column names.  Rows the csv module cannot
        parse are logged and skipped.
        :param file_name: The csv file name, for example 'posts.csv'.
        :type file_name: str
        :return: An iterator of rows; empty when the file is not present.
        :rtype: Iterator[dict[str, str]]
        """
        member = self._members.get(file_name.lower())
        if member is None:
            return
        with self._zip.open(member) as raw, io.TextIOWrapper(raw, encoding='utf-8-sig', errors='replace', newline='') as text:
            reader = csv.reader(text)
            try:
                header = [column.strip().lower() for column in next(reader)]
            except StopIteration:
                return
            except csv.Error as error:
                logger.warning('Could not read the header of %s: %s', file_name, error)
                return
            while True:
                try:
                    values = next(reader)
                except StopIteration:
                    return
                except csv.Error as error:
                    logger.warning('Skipping malformed row in %s at line %s: %s', file_name, reader.line_num, error)
                    continue
                if not any(value.strip() for value in values):
                    continue
                yield dict(zip(header, values))

    def count_rows(self, file_name: str) -> int:
        """
        Counts the data rows in one csv file.
        :param file_name: The csv file name.
        :type file_name: str
        :return: The number of rows; 0 when the file is not present.
        :rtype: int
        """
        return sum(1 for _ in self.iter_rows(file_name))

    def file_sha256(self) -> str:
        """
        Computes the SHA-256 of the archive file, used to recognise an archive that has already been imported.
        :return: The hex digest.
        :rtype: str
        """
        digest = hashlib.sha256()
        with open(self.zip_path, 'rb') as file:
            for chunk in iter(lambda: file.read(_HASH_CHUNK_SIZE), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def read_manifest(self) -> ExportManifest:
        """
        Builds a summary of the archive: which known files it holds, how many rows each has, and whose account it is.
        :return: The manifest.
        :rtype: ExportManifest
        """
        present = [name for name in KNOWN_FILES if self.has_file(name)]
        counts = {name: self.count_rows(name) for name in present if name != STATISTICS_FILE}
        return ExportManifest(file_name=os.path.basename(self.zip_path), file_sha256=self.file_sha256(),
                              account_name=self.detect_account_name(), files_present=present, row_counts=counts)

    def detect_account_name(self) -> Optional[str]:
        """
        Works out which account the export belongs to.  statistics.csv names it directly; otherwise the name that
        appears most often as a message sender, recipient or chat author is used, since the owner takes part in every
        conversation.
        :return: The account name, or None when it cannot be determined.
        :rtype: Optional[str]
        """
        for row in self.iter_rows(STATISTICS_FILE):
            statistic = (_first(row, 'statistic', 'name', 'key') or '').lower()
            if statistic in _ACCOUNT_NAME_STATISTICS:
                value = _first(row, 'value')
                if value:
                    return value
        names: Counter[str] = Counter()
        for file_name in (MESSAGES_FILE, MESSAGES_ARCHIVE_FILE):
            for row in self.iter_rows(file_name):
                for name in (_first(row, 'from'), _first(row, 'to')):
                    if name:
                        names[name] += 1
        for row in self.iter_rows(CHAT_HISTORY_FILE):
            name = _first(row, 'username', 'user', 'author')
            if name:
                names[name] += 1
        if not names:
            return None
        return names.most_common(1)[0][0]

    def iter_posts(self) -> Iterator[ExportPost]:
        """
        Yields the account's own submissions from posts.csv.
        :return: An iterator of posts.
        :rtype: Iterator[ExportPost]
        """
        for row in self.iter_rows(POSTS_FILE):
            reddit_id = strip_fullname(_first(row, 'id'))
            if reddit_id is None:
                logger.debug('Skipping post row without an id')
                continue
            yield ExportPost(
                reddit_id=reddit_id,
                permalink=absolute_reddit_url(_first(row, 'permalink')),
                date_posted=parse_export_date(_first(row, 'date', 'created_utc', 'created')),
                subreddit=_first(row, 'subreddit'),
                title=_text(row, 'title'),
                url=absolute_reddit_url(_first(row, 'url')),
                body=_text(row, 'body', 'selftext'),
            )

    def iter_comments(self) -> Iterator[ExportComment]:
        """
        Yields the account's own comments from comments.csv.
        :return: An iterator of comments.
        :rtype: Iterator[ExportComment]
        """
        for row in self.iter_rows(COMMENTS_FILE):
            reddit_id = strip_fullname(_first(row, 'id'))
            if reddit_id is None:
                logger.debug('Skipping comment row without an id')
                continue
            permalink = absolute_reddit_url(_first(row, 'permalink'))
            link = _first(row, 'link', 'link_id')
            link_reddit_id = post_id_from_permalink(link) or post_id_from_permalink(permalink)
            if link_reddit_id is None and link and '/' not in link:
                link_reddit_id = strip_fullname(link)
            parent = _first(row, 'parent', 'parent_id')
            parent_reddit_id = strip_fullname(parent) if parent and '/' not in parent else None
            if parent_reddit_id == link_reddit_id:
                parent_reddit_id = None  # top level comments name the post as their parent
            yield ExportComment(
                reddit_id=reddit_id,
                permalink=permalink,
                date_posted=parse_export_date(_first(row, 'date', 'created_utc', 'created')),
                subreddit=_first(row, 'subreddit'),
                link_reddit_id=link_reddit_id,
                parent_reddit_id=parent_reddit_id,
                body=_text(row, 'body'),
                media=_first(row, 'media'),
            )

    def iter_private_messages(self) -> Iterator[ExportPrivateMessage]:
        """
        Yields legacy private messages from messages.csv and messages_archive.csv.
        :return: An iterator of private messages.
        :rtype: Iterator[ExportPrivateMessage]
        """
        for file_name, archived in ((MESSAGES_FILE, False), (MESSAGES_ARCHIVE_FILE, True)):
            for row in self.iter_rows(file_name):
                reddit_id = strip_fullname(_first(row, 'id'))
                if reddit_id is None:
                    logger.debug('Skipping message row without an id in %s', file_name)
                    continue
                yield ExportPrivateMessage(
                    reddit_id=reddit_id,
                    permalink=absolute_reddit_url(_first(row, 'permalink')),
                    thread_id=strip_fullname(_first(row, 'thread_id')),
                    date_sent=parse_export_date(_first(row, 'date', 'created_utc', 'created')),
                    sender=_first(row, 'from', 'author'),
                    recipient=_first(row, 'to', 'dest'),
                    subject=_text(row, 'subject'),
                    body=_text(row, 'body'),
                    archived=archived,
                )

    def iter_chat_messages(self) -> Iterator[ExportChatMessage]:
        """
        Yields chat messages from chat_history.csv.
        :return: An iterator of chat messages.
        :rtype: Iterator[ExportChatMessage]
        """
        for row in self.iter_rows(CHAT_HISTORY_FILE):
            message_id = _first(row, 'message_id', 'id')
            channel_url = _first(row, 'channel_url', 'channel_id')
            if message_id is None or channel_url is None:
                logger.debug('Skipping chat row without a message id or channel')
                continue
            yield ExportChatMessage(
                message_id=message_id,
                channel_url=channel_url,
                date_posted=parse_export_date(_first(row, 'created_at', 'date')),
                date_updated=parse_export_date(_first(row, 'updated_at')),
                author=_first(row, 'username', 'user', 'author'),
                body=_text(row, 'message', 'body'),
                thread_parent_message_id=_first(row, 'thread_parent_message_id'),
                subreddit=_first(row, 'subreddit'),
                channel_name=_first(row, 'channel_name'),
                conversation_type=_first(row, 'conversation_type'),
            )
