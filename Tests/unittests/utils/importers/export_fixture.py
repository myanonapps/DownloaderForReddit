"""
Builds small synthetic Reddit data export archives for the export import tests.


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
import io
import os
import zipfile
from typing import Optional
from unittest.mock import MagicMock

from DownloaderForReddit.database.database_handler import DatabaseHandler
from DownloaderForReddit.utils import injector
from DownloaderForReddit.utils.importers.reddit_export.export_importer import (ExportImportOptions, ExportImportStats,
                                                                               RedditExportImporter)
from DownloaderForReddit.utils.importers.reddit_export.export_reader import RedditExportReader


ACCOUNT = 'export_owner'

POSTS = [
    ['id', 'permalink', 'date', 'ip', 'subreddit', 'gildings', 'title', 'url', 'body'],
    ['p1', 'https://www.reddit.com/r/pics/comments/p1/a_link_post/', '2023-01-15 12:34:56 UTC', '1.2.3.4', 'pics', '0',
     'A link post', 'https://i.redd.it/abc123.jpg', ''],
    ['p2', 'https://www.reddit.com/r/test/comments/p2/a_text_post/', '2023-02-01 08:00:00 UTC', '1.2.3.4', 'test', '0',
     'A text post', '/r/test/comments/p2/a_text_post/', 'Some **bold** text,\nwith a line break'],
]

COMMENTS = [
    ['id', 'permalink', 'date', 'ip', 'subreddit', 'gildings', 'link', 'parent', 'body', 'media'],
    ['c1', 'https://www.reddit.com/r/test/comments/p2/a_text_post/c1/', '2023-02-01 09:00:00 UTC', '', 'test', '0',
     'https://www.reddit.com/r/test/comments/p2/a_text_post/', '', 'Top level comment', ''],
    ['c2', 'https://www.reddit.com/r/test/comments/p2/a_text_post/c2/', '2023-02-01 09:05:00 UTC', '', 'test', '0',
     'https://www.reddit.com/r/test/comments/p2/a_text_post/', 'c1', 'A reply', ''],
    ['c3', 'https://www.reddit.com/r/other/comments/zz9/someone_elses_post/c3/', '2023-03-01 10:00:00 UTC', '', 'other',
     '0', 'https://www.reddit.com/r/other/comments/zz9/someone_elses_post/', '', 'On a post not in the export',
     'https://i.redd.it/media1.png'],
]

MESSAGES = [
    ['id', 'permalink', 'thread_id', 'date', 'ip', 'from', 'to', 'subject', 'body'],
    ['m1', 'https://www.reddit.com/message/messages/m1', 't4_m1', '2022-05-05 05:05:05 UTC', '', ACCOUNT, 'friend_one',
     'Hello', 'First message'],
    ['m2', 'https://www.reddit.com/message/messages/m2', 't4_m1', '2022-05-06 05:05:05 UTC', '', 'friend_one', ACCOUNT,
     're: Hello', 'Reply'],
]

MESSAGES_ARCHIVE = [
    ['id', 'permalink', 'thread_id', 'date', 'ip', 'from', 'to', 'subject', 'body'],
    ['m0', 'https://www.reddit.com/message/messages/m0', 't4_m0', '2020-01-01 00:00:00 UTC', '', '[deleted]', ACCOUNT,
     'Old', 'Archived message'],
    ['m8', 'https://www.reddit.com/message/messages/m8', 't4_m8', '2019-06-01 00:00:00 UTC', '', 'r/modsub', ACCOUNT,
     'Mod notice', 'Please read the rules'],
    ['m7', 'https://www.reddit.com/message/messages/m7', 't4_m7', '2018-06-01 00:00:00 UTC', '', '[deleted]', 'ab',
     'Gone', 'From a deleted account to a short name'],
]

CHAT_HISTORY = [
    ['message_id', 'created_at', 'updated_at', 'username', 'message', 'thread_parent_message_id', 'channel_url',
     'subreddit', 'channel_name', 'conversation_type'],
    ['msg-1', '2024-04-01 10:00:00 UTC', '', f'/u/{ACCOUNT}', 'hi there', '', 'sendbird_group_channel_1', '', '', 'direct'],
    ['msg-2', '2024-04-01 10:01:00 UTC', '', '/u/friend_two', 'hello!', '', 'sendbird_group_channel_1', '', '', 'direct'],
    ['msg-3', '2024-04-02 11:00:00 UTC', '', 'friend_three', 'group message', '', 'sendbird_group_channel_2', '',
     'Group chat', 'group'],
    ['$msg-4', '2024-04-03 12:00:00 UTC', '', ACCOUNT, 'anyone there?', '',
     'https://chat.reddit.com/room/!abcdefghijklmnop:reddit.com', '', '', 'direct'],
]

STATISTICS = [
    ['statistic', 'value'],
    ['account name', ACCOUNT],
    ['export time', '2024-05-01 00:00:00 UTC'],
]


def csv_text(rows: list[list[str]], *, bom: bool = True) -> str:
    """
    Renders rows as csv text, optionally with a UTF-8 byte order mark as Reddit's export files have.
    :param rows: The rows, header first.
    :type rows: list[list[str]]
    :param bom: Whether to start the text with a byte order mark.
    :type bom: bool
    :return: The csv text.
    :rtype: str
    """
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return ('﻿' if bom else '') + buffer.getvalue()


def default_files() -> dict[str, str]:
    """
    Returns the contents of a complete synthetic export.
    :return: Archive member names mapped to their csv text.
    :rtype: dict[str, str]
    """
    return {
        'posts.csv': csv_text(POSTS),
        'comments.csv': csv_text(COMMENTS),
        'messages.csv': csv_text(MESSAGES),
        'messages_archive.csv': csv_text(MESSAGES_ARCHIVE),
        'chat_history.csv': csv_text(CHAT_HISTORY),
        'statistics.csv': csv_text(STATISTICS),
        'ip_logs.csv': csv_text([['date', 'ip'], ['2024-01-01', '9.9.9.9']]),
    }


def write_export(directory: str, files: Optional[dict[str, str]] = None, name: str = 'export.zip') -> str:
    """
    Writes a synthetic export archive.
    :param directory: The directory to write the archive into.
    :type directory: str
    :param files: Member names mapped to their text; the complete default export when not given.
    :type files: Optional[dict[str, str]]
    :param name: The archive file name.
    :type name: str
    :return: The archive path.
    :rtype: str
    """
    path = os.path.join(directory, name)
    with zipfile.ZipFile(path, 'w') as archive:
        for member, text in (files if files is not None else default_files()).items():
            archive.writestr(member, text.encode('utf-8'))
    return path


def import_into_memory_database(directory: str) -> tuple[DatabaseHandler, ExportImportStats]:
    """
    Points the injector at a fresh in-memory database and mocked settings, then imports the complete synthetic export.
    :param directory: The directory to write the archive into.
    :type directory: str
    :return: The database handler and the import's stats.
    :rtype: tuple[DatabaseHandler, ExportImportStats]
    """
    injector.settings_manager = MagicMock()
    db = DatabaseHandler(in_memory=True)
    injector.database_handler = db
    with RedditExportReader(write_export(directory)) as reader:
        stats = RedditExportImporter(reader, ExportImportOptions(account_name=ACCOUNT)).run()
    return db, stats
