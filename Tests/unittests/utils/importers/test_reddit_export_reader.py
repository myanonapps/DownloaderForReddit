"""
Tests for reading Reddit data export archives.


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

import os
import tempfile
from datetime import datetime
from unittest import TestCase

from DownloaderForReddit.core.const import DELETED_REDDIT_OBJECT_NAME, SUBREDDIT_OBJECT, USER_OBJECT
from DownloaderForReddit.utils.importers.reddit_export import InvalidExportError
from DownloaderForReddit.utils.importers.reddit_export.export_reader import (RedditExportReader, absolute_reddit_url,
                                                                             parse_export_date, person_reference,
                                                                             post_id_from_permalink, strip_fullname,
                                                                             strip_user_prefix)
from Tests.unittests.utils.importers.export_fixture import ACCOUNT, POSTS, csv_text, write_export


class TestExportParsingHelpers(TestCase):
    """Tests for the reader's value parsing helpers."""

    def test_parse_export_date_utc_suffix(self) -> None:
        """The export's 'UTC' suffixed format is parsed to a naive datetime."""
        self.assertEqual(datetime(2023, 1, 15, 12, 34, 56), parse_export_date('2023-01-15 12:34:56 UTC'))

    def test_parse_export_date_iso_with_offset(self) -> None:
        """An ISO date with an offset is converted to UTC."""
        self.assertEqual(datetime(2023, 1, 15, 10, 0, 0), parse_export_date('2023-01-15T12:00:00+02:00'))

    def test_parse_export_date_epoch(self) -> None:
        """Epoch seconds are accepted."""
        self.assertEqual(datetime(1970, 1, 2), parse_export_date('86400'))

    def test_parse_export_date_invalid(self) -> None:
        """Empty or unparseable dates give None."""
        self.assertIsNone(parse_export_date(''))
        self.assertIsNone(parse_export_date('not a date'))

    def test_absolute_reddit_url(self) -> None:
        """Site-relative links get reddit's origin, and absolute or empty links are kept."""
        self.assertEqual('https://www.reddit.com/r/a/comments/b/', absolute_reddit_url('/r/a/comments/b/'))
        self.assertEqual('https://i.redd.it/x.jpg', absolute_reddit_url('https://i.redd.it/x.jpg'))
        self.assertEqual('//cdn.example.com/x', absolute_reddit_url('//cdn.example.com/x'))
        self.assertIsNone(absolute_reddit_url(''))

    def test_strip_fullname(self) -> None:
        """Type prefixes are removed and empty values give None."""
        self.assertEqual('abc', strip_fullname('t1_abc'))
        self.assertEqual('abc', strip_fullname('abc'))
        self.assertIsNone(strip_fullname('  '))

    def test_strip_user_prefix(self) -> None:
        """The u/ prefix is removed in either form, and an empty name gives None."""
        self.assertEqual('someone', strip_user_prefix('/u/someone'))
        self.assertEqual('someone', strip_user_prefix('u/someone'))
        self.assertEqual('someone', strip_user_prefix(' someone '))
        self.assertIsNone(strip_user_prefix('/u/'))

    def test_person_reference(self) -> None:
        """Names map to users, r/ names to subreddits, and deleted or missing names to the deleted placeholder."""
        self.assertEqual((USER_OBJECT, 'someone'), person_reference('/u/someone'))
        self.assertEqual((USER_OBJECT, 'ab'), person_reference('ab'))
        self.assertEqual((SUBREDDIT_OBJECT, 'modsub'), person_reference('/r/modsub'))
        self.assertEqual((SUBREDDIT_OBJECT, 'modsub'), person_reference('r/modsub'))
        for deleted in ('[deleted]', 'deleted', '', None, '/u/'):
            self.assertEqual((USER_OBJECT, DELETED_REDDIT_OBJECT_NAME), person_reference(deleted))

    def test_post_id_from_permalink(self) -> None:
        """The submission id is taken from a permalink."""
        self.assertEqual('p2', post_id_from_permalink('https://www.reddit.com/r/test/comments/p2/title/c1/'))
        self.assertIsNone(post_id_from_permalink('https://www.reddit.com/message/messages/m1'))


class TestRedditExportReader(TestCase):
    """Tests for RedditExportReader."""

    def setUp(self) -> None:
        """Creates a temporary directory for the archives."""
        self.temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with  # cleaned up in tearDown
        self.directory = self.temp_dir.name

    def tearDown(self) -> None:
        """Removes the temporary directory."""
        self.temp_dir.cleanup()

    def test_not_a_zip_raises(self) -> None:
        """A file that is not a zip archive is rejected."""
        path = os.path.join(self.directory, 'not_a_zip.zip')
        with open(path, 'w', encoding='utf-8') as file:
            file.write('plain text')
        with self.assertRaises(InvalidExportError):
            RedditExportReader(path)

    def test_zip_without_export_files_raises(self) -> None:
        """A zip archive that holds none of the export files is rejected."""
        path = write_export(self.directory, {'readme.txt': 'nothing here'})
        with self.assertRaises(InvalidExportError):
            RedditExportReader(path)

    def test_manifest(self) -> None:
        """The manifest lists the known files, counts their rows and names the account."""
        with RedditExportReader(write_export(self.directory)) as reader:
            manifest = reader.read_manifest()
        self.assertEqual(ACCOUNT, manifest.account_name)
        self.assertEqual(2, manifest.count('posts.csv'))
        self.assertEqual(3, manifest.count('comments.csv'))
        self.assertEqual(2, manifest.count('messages.csv'))
        self.assertEqual(3, manifest.count('messages_archive.csv'))
        self.assertEqual(4, manifest.count('chat_history.csv'))
        self.assertNotIn('ip_logs.csv', manifest.files_present)
        self.assertEqual(64, len(manifest.file_sha256))

    def test_account_name_without_statistics(self) -> None:
        """Without statistics.csv the most frequent conversation participant is taken to be the owner."""
        files = {
            'messages.csv': csv_text([['id', 'from', 'to'], ['m1', ACCOUNT, 'a_friend'], ['m2', 'other_friend', ACCOUNT]]),
        }
        with RedditExportReader(write_export(self.directory, files)) as reader:
            self.assertEqual(ACCOUNT, reader.detect_account_name())

    def test_files_in_subfolder(self) -> None:
        """Files nested in a folder inside the archive are found."""
        files = {'export_owner_data/posts.csv': csv_text(POSTS)}
        with RedditExportReader(write_export(self.directory, files)) as reader:
            self.assertEqual(['p1', 'p2'], [post.reddit_id for post in reader.iter_posts()])

    def test_column_order_and_missing_bom(self) -> None:
        """Columns are matched by name, so reordered columns and a file without a byte order mark still read."""
        rows = [['title', 'id', 'url'], ['Reordered', 'p9', 'https://example.com/image.png']]
        files = {'posts.csv': csv_text(rows, bom=False)}
        with RedditExportReader(write_export(self.directory, files)) as reader:
            posts = list(reader.iter_posts())
        self.assertEqual(1, len(posts))
        self.assertEqual('p9', posts[0].reddit_id)
        self.assertEqual('Reordered', posts[0].title)
        self.assertFalse(posts[0].is_self)

    def test_rows_without_id_are_skipped(self) -> None:
        """Rows missing their id, and blank rows, are skipped."""
        rows = [['id', 'title'], ['', 'No id'], ['', ''], ['p3', 'Has id']]
        with RedditExportReader(write_export(self.directory, {'posts.csv': csv_text(rows)})) as reader:
            self.assertEqual(['p3'], [post.reddit_id for post in reader.iter_posts()])

    def test_posts(self) -> None:
        """Posts are read with their dates, bodies and type."""
        with RedditExportReader(write_export(self.directory)) as reader:
            link_post, text_post = list(reader.iter_posts())
        self.assertFalse(link_post.is_self)
        self.assertIsNone(link_post.body)
        self.assertEqual(datetime(2023, 1, 15, 12, 34, 56), link_post.date_posted)
        self.assertTrue(text_post.is_self)
        self.assertEqual('https://www.reddit.com/r/test/comments/p2/a_text_post/', text_post.url)
        self.assertEqual('Some **bold** text,\nwith a line break', text_post.body)

    def test_comments(self) -> None:
        """Comments resolve their post id and parent, and top level comments have no parent."""
        with RedditExportReader(write_export(self.directory)) as reader:
            top, reply, other = list(reader.iter_comments())
        self.assertEqual('p2', top.link_reddit_id)
        self.assertIsNone(top.parent_reddit_id)
        self.assertEqual('c1', reply.parent_reddit_id)
        self.assertEqual('zz9', other.link_reddit_id)
        self.assertEqual('https://i.redd.it/media1.png', other.media)

    def test_private_messages(self) -> None:
        """Messages from both message files are read, and archived ones are flagged."""
        with RedditExportReader(write_export(self.directory)) as reader:
            messages = list(reader.iter_private_messages())
        self.assertEqual(['m1', 'm2', 'm0', 'm8', 'm7'], [message.reddit_id for message in messages])
        self.assertEqual('m1', messages[0].thread_id)
        self.assertEqual([False, False, True, True, True], [message.archived for message in messages])
        self.assertEqual('r/modsub', messages[3].sender)

    def test_chat_messages(self) -> None:
        """Chat messages are read with their channel."""
        with RedditExportReader(write_export(self.directory)) as reader:
            messages = list(reader.iter_chat_messages())
        self.assertEqual(4, len(messages))
        self.assertEqual('sendbird_group_channel_1', messages[0].channel_url)
        self.assertIsNone(messages[0].channel_name)
        self.assertEqual('friend_two', messages[1].author)
        self.assertEqual('group', messages[2].conversation_type)
