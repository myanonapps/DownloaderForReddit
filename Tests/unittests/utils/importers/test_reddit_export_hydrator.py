"""
Tests for filling in imported Reddit export data from a download source.


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

import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from DownloaderForReddit.database.models import Post, Comment
from DownloaderForReddit.utils.importers.reddit_export.export_hydrator import ExportHydrator
from DownloaderForReddit.utils.importers.reddit_export.export_importer import ExportImportStats
from Tests.unittests.utils.importers.export_fixture import import_into_memory_database


def fake_submission(reddit_id: str, **fields: object) -> SimpleNamespace:
    """
    Builds an object shaped like the submissions the adapters return.
    :param reddit_id: The submission id.
    :type reddit_id: str
    :param fields: Attributes to set or override.
    :type fields: object
    :return: The fake submission.
    :rtype: SimpleNamespace
    """
    values = {'id': reddit_id, 'score': 42, 'over_18': False, 'is_self': False, 'domain': 'i.redd.it',
              'url': f'https://i.redd.it/{reddit_id}.jpg', 'selftext': '', 'selftext_html': None, 'title': f'Post {reddit_id}',
              'created_utc': 1700000000, 'author': SimpleNamespace(name='someone_else'),
              'subreddit': SimpleNamespace(display_name='other'), 'permalink': f'/r/other/comments/{reddit_id}/'}
    values.update(fields)
    return SimpleNamespace(**values)


class TestExportHydrator(TestCase):
    """Tests for ExportHydrator."""

    def setUp(self) -> None:
        """Imports the synthetic export into a fresh in-memory database."""
        with tempfile.TemporaryDirectory() as directory:
            self.db, self.stats = import_into_memory_database(directory)

    def make_adapter(self) -> MagicMock:
        """
        Builds a fake adapter that holds post p1 (marked nsfw), the commented post zz9 and comment c1, but not p2.
        :return: The fake adapter.
        :rtype: MagicMock
        """
        submissions = {'p1': fake_submission('p1', over_18=True, score=7), 'zz9': fake_submission('zz9')}
        adapter = MagicMock()
        adapter.submissions_by_ids.side_effect = lambda ids: [submissions[i] for i in ids if i in submissions]
        adapter.comments_by_ids.side_effect = lambda ids: [SimpleNamespace(id=i, score=5) for i in ids if i == 'c1']
        return adapter

    def test_posts_are_updated(self) -> None:
        """Found posts get the source's score and nsfw flag; missing ones are counted and kept."""
        stats = ExportHydrator(self.make_adapter()).hydrate(self.stats)
        self.assertEqual(1, stats.posts_hydrated)
        with self.db.get_scoped_session() as session:
            found = session.query(Post).filter(Post.reddit_id == 'p1').one()
            self.assertEqual(7, found.score)
            self.assertTrue(found.nsfw)
            missing = session.query(Post).filter(Post.reddit_id == 'p2').one()
            self.assertEqual(0, missing.score)

    def test_comments_are_updated(self) -> None:
        """Found comments get the source's score."""
        stats = ExportHydrator(self.make_adapter()).hydrate(self.stats)
        self.assertEqual(1, stats.comments_hydrated)
        self.assertEqual(1 + 2, stats.not_found)  # p2, plus comments c2 and c3
        with self.db.get_scoped_session() as session:
            self.assertEqual(5, session.query(Comment).filter(Comment.reddit_id == 'c1').one().score)

    def test_commented_posts_are_added_and_linked(self) -> None:
        """The post a comment was made on is stored as extracted, and the comment is attached to it."""
        ExportHydrator(self.make_adapter()).hydrate(self.stats)
        with self.db.get_scoped_session() as session:
            post = session.query(Post).filter(Post.reddit_id == 'zz9').one()
            self.assertTrue(post.extracted)
            self.assertEqual('someone_else', post.author.name)
            self.assertIsNone(post.significant_reddit_object)
            self.assertEqual(post.id, session.query(Comment).filter(Comment.reddit_id == 'c3').one().post_id)

    def test_import_without_session_is_ignored(self) -> None:
        """Stats without a download session are returned unchanged."""
        adapter = self.make_adapter()
        stats = ExportHydrator(adapter).hydrate(ExportImportStats())
        self.assertEqual(0, stats.posts_hydrated)
        adapter.submissions_by_ids.assert_not_called()
