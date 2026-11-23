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


Unit tests for RedditAdapterManager: adapter selection and saving, loading and deleting the per-source tokens.
"""
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock

from DownloaderForReddit.data_interface.adapter_manager import RedditAdapterManager
from DownloaderForReddit.data_interface.adapters.arctic_shift_adapter import ArcticShiftAdapter
from DownloaderForReddit.data_interface.adapters.praw_adapter import PRAWAdapter
from DownloaderForReddit.data_interface.adapters.pull_push_adapter import PullPushAdapter
from DownloaderForReddit.database.model_enums import PostDownloadSource
from DownloaderForReddit.utils import injector


class TestRedditAdapterManager(TestCase):
    """
    Tests for RedditAdapterManager, using a mocked settings manager backed by a plain dictionary.
    """

    def setUp(self) -> None:
        """
        Installs a mocked settings manager and arranges for the manager's shared tokens to be reset afterwards.
        """
        self.config: dict[str, dict[str, Any]] = {'core': {}}
        settings_manager = MagicMock()
        settings_manager.config = self.config
        settings_manager.get.side_effect = self._settings_get
        previous_settings = injector.settings_manager
        injector.settings_manager = settings_manager
        self.addCleanup(setattr, injector, 'settings_manager', previous_settings)
        self.manager = RedditAdapterManager()
        self.addCleanup(self._reset_tokens)

    def _settings_get(self, section: str, key: str, default: Any = None) -> Any:
        """
        Reads a value from the dictionary standing in for the config file.

        :param section: The config section.
        :type section: str
        :param key: The key within the section.
        :type key: str
        :param default: The value returned when the key is missing.
        :type default: Any
        :return: The stored value, or the default.
        :rtype: Any
        """
        return self.config.get(section, {}).get(key, default)

    def _reset_tokens(self) -> None:
        """
        Clears the class-level tokens so that no test leaks a token into another.
        """
        for source in PostDownloadSource:
            token = self.manager.get_adapter_token(source)
            if token is not None:
                token.reset()

    def test_is_singleton(self) -> None:
        """
        Every construction returns the same instance.
        """
        self.assertIs(self.manager, RedditAdapterManager())

    def test_get_adapter_returns_class_for_source(self) -> None:
        """
        Each download source maps to its adapter class.
        """
        expected = {
            PostDownloadSource.REDDIT: PRAWAdapter,
            PostDownloadSource.ARCTIC_SHIFT: ArcticShiftAdapter,
            PostDownloadSource.PULL_PUSH: PullPushAdapter,
        }
        for source, adapter_class in expected.items():
            with self.subTest(source=source):
                self.assertIsInstance(self.manager.get_adapter(source), adapter_class)

    def test_save_adapter_token_writes_config(self) -> None:
        """
        Saving a token stores its key and encrypted form in the config and on the settings manager.
        """
        self.manager.save_adapter_token(PostDownloadSource.REDDIT, 'refresh-token')

        key = self.config['core']['reddit_access']
        encrypted = self.config['core']['reddit_access_token']
        self.assertIsInstance(key, str)
        self.assertIsInstance(encrypted, str)
        self.assertNotEqual(encrypted, 'refresh-token')
        self.assertEqual(injector.settings_manager.reddit_access, key)
        self.assertEqual(injector.settings_manager.reddit_access_token, encrypted)

    def test_saved_token_round_trips_through_get_adapter(self) -> None:
        """
        A token saved to the config is decrypted again when an adapter is created from a cleared token.
        """
        self.manager.save_adapter_token(PostDownloadSource.REDDIT, 'refresh-token')
        self._reset_tokens()

        self.manager.get_adapter(PostDownloadSource.REDDIT)

        token = self.manager.get_adapter_token(PostDownloadSource.REDDIT)
        self.assertEqual(token.get_decrypted(), 'refresh-token')

    def test_delete_adapter_token_clears_config(self) -> None:
        """
        Deleting a token clears both config entries and the decrypted value.
        """
        self.manager.save_adapter_token(PostDownloadSource.REDDIT, 'refresh-token')

        self.manager.delete_adapter_token(PostDownloadSource.REDDIT)

        self.assertIsNone(self.config['core']['reddit_access'])
        self.assertIsNone(self.config['core']['reddit_access_token'])
        self.assertIsNone(self.manager.get_adapter_token(PostDownloadSource.REDDIT).get_decrypted())
