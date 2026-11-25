"""
Tests for fetching the images of chat reactions into the application's reactions folder.


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
from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests

from DownloaderForReddit.core.reaction_fetcher import fetch_missing_reaction_images, reaction_file_name
from DownloaderForReddit.database.database_handler import DatabaseHandler
from DownloaderForReddit.database.export_models import REACTIONS_FOLDER_NAME, ChatChannel, ChatMessage, ChatReaction
from DownloaderForReddit.database.models import Content
from DownloaderForReddit.utils import injector


HEART = 'https://i.redd.it/8r21ukpfa7081.gif'
GIF_BYTES = b'GIF89a-test'


class TestReactionFetcher(TestCase):
    """Tests for fetch_missing_reaction_images, with the data directory in a temporary folder."""

    def setUp(self) -> None:
        """Points the data directory at a temporary folder and stores one reaction in a fresh in-memory database."""
        self.temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with  # cleaned up in tearDown
        data_patch = patch('DownloaderForReddit.utils.system_util.get_data_directory', return_value=self.temp_dir.name)
        data_patch.start()
        self.addCleanup(data_patch.stop)
        injector.settings_manager = MagicMock()
        self.db = DatabaseHandler(in_memory=True)
        injector.database_handler = self.db
        with self.db.get_scoped_session() as session:
            session.add(ChatReaction(url=HEART, enabled=True))
            session.commit()
        self.folder = os.path.join(self.temp_dir.name, REACTIONS_FOLDER_NAME)

    def tearDown(self) -> None:
        """Removes the temporary folder."""
        self.temp_dir.cleanup()

    def fetch(self) -> tuple[int, int]:
        """
        Runs the fetch.
        :return: The number of images fetched and the number that failed.
        :rtype: tuple[int, int]
        """
        with self.db.get_scoped_session() as session:
            return fetch_missing_reaction_images(session)

    def reaction(self) -> tuple[bool, str, str]:
        """
        Reads the stored reaction back.
        :return: Whether its image is on disk, its file name, and its fetch error.
        :rtype: tuple[bool, str, str]
        """
        with self.db.get_scoped_session() as session:
            reaction = session.query(ChatReaction).one()
            return reaction.has_image, reaction.file_name, reaction.fetch_error

    def test_file_name(self) -> None:
        """An image is stored under its image id and the extension of its url."""
        self.assertEqual('8r21ukpfa7081.gif', reaction_file_name(ChatReaction(url=HEART)))
        self.assertEqual('abc.gif', reaction_file_name(ChatReaction(url='https://i.redd.it/abc')))

    @patch('DownloaderForReddit.core.reaction_fetcher.requests.get')
    def test_downloads_missing_image(self, get: MagicMock) -> None:
        """A reaction without an image has it downloaded into the reactions folder, once."""
        get.return_value = MagicMock(content=GIF_BYTES)
        self.assertEqual((1, 0), self.fetch())
        get.assert_called_once()
        self.assertEqual((True, '8r21ukpfa7081.gif', None), self.reaction())
        with open(os.path.join(self.folder, '8r21ukpfa7081.gif'), 'rb') as file:
            self.assertEqual(GIF_BYTES, file.read())
        self.assertEqual((0, 0), self.fetch())
        get.assert_called_once()

    @patch('DownloaderForReddit.core.reaction_fetcher.requests.get')
    def test_copies_an_image_already_downloaded(self, get: MagicMock) -> None:
        """An image already downloaded as a message's media is copied instead of downloaded again."""
        directory = os.path.join(self.temp_dir.name, 'downloads')
        os.makedirs(directory)
        with open(os.path.join(directory, 'old.gif'), 'wb') as file:
            file.write(GIF_BYTES)
        with self.db.get_scoped_session() as session:
            message = ChatMessage(message_id='m1', body=HEART, channel=ChatChannel(channel_url='chat'))
            session.add(Content(url=HEART, chat_message=message, directory_path=directory, download_title='old',
                                extension='gif', downloaded=True))
            session.commit()
        self.assertEqual((1, 0), self.fetch())
        get.assert_not_called()
        self.assertTrue(self.reaction()[0])

    @patch('DownloaderForReddit.core.reaction_fetcher.requests.get', side_effect=requests.exceptions.ConnectionError('offline'))
    def test_failure_is_recorded(self, _get: MagicMock) -> None:
        """A failed download records the error and leaves no file."""
        self.assertEqual((0, 1), self.fetch())
        has_image, file_name, error = self.reaction()
        self.assertFalse(has_image)
        self.assertIsNone(file_name)
        self.assertIn('offline', error)
        self.assertEqual([], os.listdir(self.folder))

    @patch('DownloaderForReddit.core.reaction_fetcher.requests.get')
    def test_disabled_reactions_are_skipped(self, get: MagicMock) -> None:
        """A reaction marked as not one has no image fetched."""
        with self.db.get_scoped_session() as session:
            session.query(ChatReaction).one().enabled = False
            session.commit()
        self.assertEqual((0, 0), self.fetch())
        get.assert_not_called()
