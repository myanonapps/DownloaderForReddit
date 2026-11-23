"""
Downloader for Reddit takes a list of reddit users and subreddits and downloads content posted to reddit either by the
users or on the subreddits.


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


Unit tests for the RedditDataInterface base class and the PRAW and Arctic Shift adapters.
"""
import inspect
import unittest
from unittest.mock import MagicMock, Mock, patch

from PyQt6.QtCore import QUrl

from DownloaderForReddit.data_interface.adapters.arctic_shift_adapter import BASE_URL, ArcticShiftAdapter
from DownloaderForReddit.data_interface.adapters.praw_adapter import PRAWAdapter
from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.data_interface.reddit_data_interface import RedditDataInterface
from DownloaderForReddit.utils import injector


def install_mock_settings(test: unittest.TestCase) -> None:
    """
    Replaces the injector's settings manager with a mock for the duration of a test.

    :param test: The test case that restores the previous settings manager on cleanup.
    :type test: unittest.TestCase
    """
    previous = injector.settings_manager
    injector.settings_manager = MagicMock()
    test.addCleanup(setattr, injector, 'settings_manager', previous)


class TestRedditDataInterface(unittest.TestCase):
    """
    Tests for the abstract RedditDataInterface base class.
    """

    def test_abstract_base_class(self) -> None:
        """
        The base class is abstract, so it cannot be instantiated directly.
        """
        self.assertTrue(inspect.isabstract(RedditDataInterface))


class TestPRAWAdapter(unittest.TestCase):
    """
    Tests for the PRAWAdapter, with praw.Reddit patched out.
    """

    def setUp(self) -> None:
        """
        Creates an adapter with an empty token and a mocked settings manager.
        """
        install_mock_settings(self)
        self.token = RedditAdapterToken('reddit_access', 'reddit_access_token')
        self.adapter = PRAWAdapter(self.token)

    def test_initialization(self) -> None:
        """
        The adapter implements the interface and uses Reddit's OAuth endpoints.
        """
        self.assertIsInstance(self.adapter, RedditDataInterface)
        self.assertEqual(self.adapter.get_authorization_url(), QUrl('https://www.reddit.com/api/v1/authorize'))
        self.assertEqual(self.adapter.get_access_url(), QUrl('https://www.reddit.com/api/v1/access_token'))

    @patch('praw.Reddit')
    def test_submission(self, mock_reddit: MagicMock) -> None:
        """
        Submissions are looked up through PRAW.

        :param mock_reddit: The patched praw.Reddit class.
        :type mock_reddit: MagicMock
        """
        mock_submission = Mock()
        mock_reddit.return_value.submission.return_value = mock_submission
        self.assertEqual(self.adapter.submission('test_id'), mock_submission)
        mock_reddit.return_value.submission.assert_called_once_with(id='test_id')

    @patch('praw.Reddit')
    def test_redditor(self, mock_reddit: MagicMock) -> None:
        """
        Redditors are looked up through PRAW.

        :param mock_reddit: The patched praw.Reddit class.
        :type mock_reddit: MagicMock
        """
        mock_redditor = Mock()
        mock_reddit.return_value.redditor.return_value = mock_redditor
        self.assertEqual(self.adapter.redditor('test_user'), mock_redditor)

    @patch('praw.Reddit')
    def test_subreddit(self, mock_reddit: MagicMock) -> None:
        """
        Subreddits are looked up through PRAW.

        :param mock_reddit: The patched praw.Reddit class.
        :type mock_reddit: MagicMock
        """
        mock_subreddit = Mock()
        mock_reddit.return_value.subreddit.return_value = mock_subreddit
        self.assertEqual(self.adapter.subreddit('test_sub'), mock_subreddit)

    @patch('praw.Reddit')
    def test_unauthenticated_uses_redirect_uri(self, mock_reddit: MagicMock) -> None:
        """
        Without a decrypted token, PRAW is created for the authorization flow rather than with a refresh token.

        :param mock_reddit: The patched praw.Reddit class.
        :type mock_reddit: MagicMock
        """
        self.adapter.submission('test_id')
        kwargs = mock_reddit.call_args.kwargs
        self.assertEqual(kwargs['redirect_uri'], self.adapter.get_redirect_url())
        self.assertNotIn('refresh_token', kwargs)

    @patch('praw.Reddit')
    def test_authenticated_uses_refresh_token(self, mock_reddit: MagicMock) -> None:
        """
        With a decrypted token, PRAW is created with that token as the refresh token.

        :param mock_reddit: The patched praw.Reddit class.
        :type mock_reddit: MagicMock
        """
        self.token.set('refresh-token')
        self.adapter.submission('test_id')
        kwargs = mock_reddit.call_args.kwargs
        self.assertEqual(kwargs['refresh_token'], 'refresh-token')
        self.assertNotIn('redirect_uri', kwargs)

    @patch('praw.Reddit')
    def test_praw_instance_is_reused(self, mock_reddit: MagicMock) -> None:
        """
        The PRAW instance is created once and reused for later calls.

        :param mock_reddit: The patched praw.Reddit class.
        :type mock_reddit: MagicMock
        """
        self.adapter.submission('a')
        self.adapter.redditor('b')
        mock_reddit.assert_called_once()

    def test_get_user_agent(self) -> None:
        """
        The user agent is a non-empty string.
        """
        user_agent = self.adapter.get_user_agent()
        self.assertIsInstance(user_agent, str)
        self.assertTrue(user_agent)


class TestArcticShiftAdapter(unittest.TestCase):
    """
    Tests for the ArcticShiftAdapter, with the HTTP session patched out.
    """

    def setUp(self) -> None:
        """
        Creates an adapter with an empty token and a mocked settings manager.
        """
        install_mock_settings(self)
        self.adapter = ArcticShiftAdapter(RedditAdapterToken('arctic_shift_access', 'arctic_shift_access_token'))

    def test_initialization(self) -> None:
        """
        The adapter implements the interface.
        """
        self.assertIsInstance(self.adapter, RedditDataInterface)

    @patch('requests.Session')
    def test_make_http_request(self, mock_session: MagicMock) -> None:
        """
        A successful request returns the decoded JSON from the endpoint joined to the base URL.

        :param mock_session: The patched requests.Session class.
        :type mock_session: MagicMock
        """
        mock_response = Mock(ok=True)
        mock_response.json.return_value = {'test': 'data'}
        mock_session.return_value.get.return_value = mock_response

        result = self.adapter.make_http_request('api/posts/ids', params={'ids': 'abc'})

        self.assertEqual(result, {'test': 'data'})
        mock_session.return_value.get.assert_called_once_with(f'{BASE_URL}api/posts/ids', timeout=10, params={'ids': 'abc'})

    def test_get_user_agent(self) -> None:
        """
        The user agent is a non-empty string.
        """
        user_agent = self.adapter.get_user_agent()
        self.assertIsInstance(user_agent, str)
        self.assertTrue(user_agent)


# PullPushAdapter is covered by test_pull_push_adapter.py


if __name__ == '__main__':
    unittest.main()
