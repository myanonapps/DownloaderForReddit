"""
Tests for looking several submissions or comments up by id at once, in each download source adapter.


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

from unittest import TestCase
from unittest.mock import MagicMock, patch

from DownloaderForReddit.data_interface.adapters.arctic_shift_adapter import ArcticShiftAdapter
from DownloaderForReddit.data_interface.adapters.praw_adapter import PRAWAdapter
from DownloaderForReddit.data_interface.adapters.pull_push_adapter import PullPushAdapter
from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.data_interface.reddit_data_interface import bare_reddit_id
from DownloaderForReddit.utils import injector


class TestBareRedditId(TestCase):
    """Tests for bare_reddit_id."""

    def test_prefixes_are_removed(self) -> None:
        """Type prefixes are removed and bare ids are kept."""
        self.assertEqual('abc', bare_reddit_id('t3_abc'))
        self.assertEqual('abc', bare_reddit_id('t1_abc'))
        self.assertEqual('abc', bare_reddit_id('abc'))
        self.assertEqual('to_abc', bare_reddit_id('to_abc'))


class TestArcticShiftBatchLookups(TestCase):
    """Tests for ArcticShiftAdapter's batch lookups."""

    def setUp(self) -> None:
        """Creates an adapter whose HTTP layer is mocked."""
        injector.settings_manager = MagicMock()
        self.adapter = ArcticShiftAdapter(RedditAdapterToken('arctic', 'arctic_token'))
        patcher = patch.object(self.adapter, 'make_http_request')
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def test_submissions_are_requested_in_batches_of_500(self) -> None:
        """More than 500 ids are split over several requests, with their prefixes removed."""
        self.request.return_value = {'data': [{'id': 'a', 'title': 'A', 'author': 'x', 'subreddit': 'y'}]}
        ids = ['t3_a'] + [f'id{number}' for number in range(600)]
        found = self.adapter.submissions_by_ids(ids)
        self.assertEqual(2, self.request.call_count)
        endpoint, params = self.request.call_args_list[0].args
        self.assertEqual('api/posts/ids', endpoint)
        self.assertEqual(500, len(params['ids'].split(',')))
        self.assertTrue(params['ids'].startswith('a,'))
        self.assertEqual(['a', 'a'], [item.id for item in found])

    def test_comments(self) -> None:
        """Comments are requested from the comments endpoint and wrapped."""
        self.request.return_value = {'data': [{'id': 'c1', 'score': 3, 'body': 'hi'}]}
        found = self.adapter.comments_by_ids(['t1_c1'])
        self.assertEqual('api/comments/ids', self.request.call_args.args[0])
        self.assertEqual(3, found[0].score)

    def test_bad_response_gives_nothing(self) -> None:
        """A response without a data list gives no items."""
        self.request.return_value = {'error': 'oops'}
        self.assertEqual([], self.adapter.submissions_by_ids(['a']))


class TestPullPushBatchLookups(TestCase):
    """Tests for PullPushAdapter's batch lookups."""

    def setUp(self) -> None:
        """Creates an adapter whose HTTP layer is mocked."""
        injector.settings_manager = MagicMock()
        self.adapter = PullPushAdapter(RedditAdapterToken('pull_push', 'pull_push_token'))
        patcher = patch.object(self.adapter, 'make_http_request')
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def test_submissions_are_requested_in_pages_of_100(self) -> None:
        """Ids are sent 100 at a time to the topic endpoint, with a matching page size."""
        self.request.return_value = {'data': [], 'error': None}
        self.adapter.submissions_by_ids([f't3_id{number}' for number in range(150)])
        self.assertEqual(2, self.request.call_count)
        endpoint, params = self.request.call_args_list[1].args
        self.assertEqual('topic', endpoint)
        self.assertEqual(50, params['size'])
        self.assertFalse(params['ids'].startswith('t3_'))

    def test_comments(self) -> None:
        """Comments are requested from the comment endpoint."""
        self.request.return_value = {'data': [{'id': 'c1', 'score': 2}], 'error': None}
        found = self.adapter.comments_by_ids(['c1'])
        self.assertEqual('comment', self.request.call_args.args[0])
        self.assertEqual('c1', found[0].id)


class TestPrawBatchLookups(TestCase):
    """Tests for PRAWAdapter's batch lookups."""

    def setUp(self) -> None:
        """Creates an adapter whose PRAW instance is mocked."""
        injector.settings_manager = MagicMock()
        self.adapter = PRAWAdapter(None)
        self.praw = MagicMock()
        patcher = patch.object(self.adapter, '_get_praw_instance', return_value=self.praw)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_submissions_use_info_with_fullnames(self) -> None:
        """Submission ids are sent to info() as t3_ fullnames."""
        self.praw.info.return_value = iter(['found'])
        self.assertEqual(['found'], self.adapter.submissions_by_ids(['abc', 't3_def']))
        self.praw.info.assert_called_once_with(fullnames=['t3_abc', 't3_def'])

    def test_comments_use_info_with_fullnames(self) -> None:
        """Comment ids are sent to info() as t1_ fullnames."""
        self.praw.info.return_value = iter([])
        self.adapter.comments_by_ids(['c1'])
        self.praw.info.assert_called_once_with(fullnames=['t1_c1'])

    def test_no_ids_makes_no_request(self) -> None:
        """An empty id list makes no request."""
        self.assertEqual([], self.adapter.submissions_by_ids([]))
        self.praw.info.assert_not_called()
