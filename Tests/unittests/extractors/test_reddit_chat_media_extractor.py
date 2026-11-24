"""
Tests for the extractor of media uploaded to Reddit chat.


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

import requests

from DownloaderForReddit.core.errors import Error
from DownloaderForReddit.core.submission_handler import assign_extractor
from DownloaderForReddit.extractors.reddit_chat_media_extractor import (RedditChatMediaExtractor, extension_for_type,
                                                                        media_id_from_url)
from DownloaderForReddit.utils import injector


MEDIA_URL = 'https://matrix.redditspace.com/_matrix/media/r0/download/reddit.com/abc123'


def response(content_type: str = '', ok: bool = True) -> MagicMock:
    """
    Makes a stand-in for a requests response.
    :param content_type: The Content-Type header; none when empty.
    :type content_type: str
    :param ok: Whether the response succeeded.
    :type ok: bool
    :return: The response.
    :rtype: MagicMock
    """
    mock = MagicMock(ok=ok, headers={'Content-Type': content_type} if content_type else {})
    mock.__enter__.return_value = mock
    return mock


class TestExtensionForType(TestCase):
    """Tests for extension_for_type and media_id_from_url."""

    def test_common_types(self) -> None:
        """Common media types give their usual extensions, ignoring header parameters and case."""
        self.assertEqual('jpg', extension_for_type('image/jpeg'))
        self.assertEqual('png', extension_for_type('Image/PNG; charset=binary'))
        self.assertEqual('gif', extension_for_type('image/gif'))
        self.assertEqual('mp4', extension_for_type('video/mp4'))

    def test_unknown_type(self) -> None:
        """A missing or unknown type gives no extension."""
        self.assertIsNone(extension_for_type(None))
        self.assertIsNone(extension_for_type(''))
        self.assertIsNone(extension_for_type('application/x-not-a-real-type'))

    def test_media_id(self) -> None:
        """The media id is the last part of the url's path."""
        self.assertEqual('abc123', media_id_from_url(MEDIA_URL))
        self.assertEqual('abc123', media_id_from_url(MEDIA_URL + '/?width=200'))


class TestRedditChatMediaExtractor(TestCase):
    """Tests for RedditChatMediaExtractor, with the network replaced."""

    def setUp(self) -> None:
        """Makes an extractor for a chat media link in a stand-in message, recording the content it makes."""
        injector.settings_manager = MagicMock(supported_videos_updated=0.0)
        message = MagicMock()
        message.significant_reddit_object = MagicMock()
        self.extractor = RedditChatMediaExtractor(None, message=message, url=MEDIA_URL)
        self.extractor.make_content = MagicMock()
        self.extractor.handle_failed_extract = MagicMock()

    def test_assigned_to_chat_media_urls(self) -> None:
        """Chat media links are assigned to this extractor."""
        self.assertIs(RedditChatMediaExtractor, assign_extractor(MEDIA_URL, {}))

    @patch('DownloaderForReddit.extractors.reddit_chat_media_extractor.requests')
    def test_extension_from_head(self, mock_requests: MagicMock) -> None:
        """The extension comes from the type the server reports to a HEAD request."""
        mock_requests.head.return_value = response('image/png')
        self.extractor.extract_content()
        self.extractor.make_content.assert_called_once_with(MEDIA_URL, 'png', media_id='abc123')
        mock_requests.get.assert_not_called()

    @patch('DownloaderForReddit.extractors.reddit_chat_media_extractor.requests')
    def test_extension_from_get_when_head_has_none(self, mock_requests: MagicMock) -> None:
        """When HEAD reports no type, the type of a streamed GET is used."""
        mock_requests.head.return_value = response(ok=False)
        mock_requests.get.return_value = response('video/mp4')
        self.extractor.extract_content()
        self.extractor.make_content.assert_called_once_with(MEDIA_URL, 'mp4', media_id='abc123')

    @patch('DownloaderForReddit.extractors.reddit_chat_media_extractor.requests')
    def test_unknown_type_fails(self, mock_requests: MagicMock) -> None:
        """A file of no known media type is reported as a failed extraction."""
        mock_requests.head.return_value = response('application/octet-stream-unknown')
        mock_requests.get.return_value = response('application/octet-stream-unknown')
        self.extractor.extract_content()
        self.extractor.make_content.assert_not_called()
        self.assertEqual(Error.UNRECOGNIZED_EXTENSION, self.extractor.handle_failed_extract.call_args.kwargs['error'])

    @patch('DownloaderForReddit.extractors.reddit_chat_media_extractor.requests.head',
           side_effect=requests.exceptions.ConnectionError())
    def test_unreachable_server_fails(self, _mock_head: MagicMock) -> None:
        """A server that cannot be reached is reported as a connection error."""
        self.extractor.extract_content()
        self.extractor.make_content.assert_not_called()
        self.assertEqual(Error.CONNECTION_ERROR, self.extractor.handle_failed_extract.call_args.kwargs['error'])

    def test_url_with_extension_used_directly(self) -> None:
        """A chat media url that already ends in an extension is not looked up."""
        self.extractor.url = 'https://matrix.redditspace.com/media/picture.jpg'
        self.extractor.extract_content()
        self.extractor.make_content.assert_called_once_with(self.extractor.url, 'jpg')
