"""
Plain data records read from a Reddit data export archive.

The reader yields these records without touching the database, so they can be previewed, tested and imported
independently of how they are parsed.


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

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


POSTS_FILE = 'posts.csv'
COMMENTS_FILE = 'comments.csv'
MESSAGES_FILE = 'messages.csv'
MESSAGES_ARCHIVE_FILE = 'messages_archive.csv'
CHAT_HISTORY_FILE = 'chat_history.csv'
STATISTICS_FILE = 'statistics.csv'

KNOWN_FILES = (POSTS_FILE, COMMENTS_FILE, MESSAGES_FILE, MESSAGES_ARCHIVE_FILE, CHAT_HISTORY_FILE, STATISTICS_FILE)
CONTENT_FILES = (POSTS_FILE, COMMENTS_FILE, MESSAGES_FILE, MESSAGES_ARCHIVE_FILE, CHAT_HISTORY_FILE)


@dataclass
class ExportPost:
    """A submission made by the exporting account."""

    reddit_id: str
    permalink: Optional[str] = None
    date_posted: Optional[datetime] = None
    subreddit: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    body: Optional[str] = None

    @property
    def is_self(self) -> bool:
        """
        Whether the post is a text post.  The export does not say so directly; a text post has no url, or a url that
        points back at the post itself.
        :return: True when the post is a text post.
        :rtype: bool
        """
        if not self.url:
            return True
        return self.reddit_id in self.url and '/comments/' in self.url


@dataclass
class ExportComment:
    """A comment made by the exporting account."""

    reddit_id: str
    date_posted: Optional[datetime] = None
    subreddit: Optional[str] = None
    link_reddit_id: Optional[str] = None
    parent_reddit_id: Optional[str] = None
    body: Optional[str] = None
    media: Optional[str] = None


@dataclass
class ExportPrivateMessage:  # pylint: disable=too-many-instance-attributes  # mirrors the export's csv columns
    """A legacy private (inbox) message sent or received by the exporting account."""

    reddit_id: str
    thread_id: Optional[str] = None
    date_sent: Optional[datetime] = None
    sender: Optional[str] = None
    recipient: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    archived: bool = False


@dataclass
class ExportChatMessage:  # pylint: disable=too-many-instance-attributes  # mirrors the export's csv columns
    """A message from a chat channel the exporting account took part in."""

    message_id: str
    channel_url: str
    date_posted: Optional[datetime] = None
    date_updated: Optional[datetime] = None
    author: Optional[str] = None
    body: Optional[str] = None
    thread_parent_message_id: Optional[str] = None
    subreddit: Optional[str] = None
    channel_name: Optional[str] = None
    conversation_type: Optional[str] = None


@dataclass
class ExportManifest:
    """A summary of an export archive, used to preview it before importing."""

    file_name: str
    file_sha256: str
    account_name: Optional[str] = None
    files_present: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)

    def count(self, file_name: str) -> int:
        """
        Returns the number of data rows in one of the archive's csv files.
        :param file_name: The csv file name, for example 'posts.csv'.
        :type file_name: str
        :return: The row count, or 0 when the file is not in the archive.
        :rtype: int
        """
        return self.row_counts.get(file_name, 0)
