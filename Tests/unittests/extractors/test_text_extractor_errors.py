"""
Tests that the self post and comment text extractors report write failures instead of crashing while reporting them.


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
from unittest.mock import MagicMock, create_autospec

from DownloaderForReddit.core.errors import Error
from DownloaderForReddit.database.models import Content
from DownloaderForReddit.extractors.comment_extractor import CommentExtractor
from DownloaderForReddit.extractors.self_post_extractor import SelfPostExtractor
from DownloaderForReddit.utils import injector


class TestTextExtractorErrors(TestCase):
    """Tests for the error paths of SelfPostExtractor and CommentExtractor."""

    def setUp(self) -> None:
        """Uses stand-in settings and a temporary directory whose missing subfolder makes writes fail."""
        injector.settings_manager = MagicMock()
        injector.database_handler = MagicMock()
        self.temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with  # cleaned up in tearDown
        self.unwritable_path = os.path.join(self.temp_dir.name, 'missing', 'file.txt')

    def tearDown(self) -> None:
        """Removes the temporary directory."""
        self.temp_dir.cleanup()

    def test_self_post_write_failure_recorded(self) -> None:
        """A self post that cannot be written records a text failure on its content rather than raising."""
        extractor = SelfPostExtractor(MagicMock(text='some text'), download_session_id=1)
        content = create_autospec(Content, instance=True, extension='txt')  # checks set_download_error's signature
        content.get_full_file_path.return_value = self.unwritable_path
        extractor.download_text_post(content)
        content.set_download_error.assert_called_once()
        error, message = content.set_download_error.call_args.args
        self.assertEqual(Error.TEXT_FAILURE, error)
        self.assertIn('Failed to save text post', message)
        content.set_downloaded.assert_not_called()

    def test_comment_failure_logged(self) -> None:
        """A comment whose text cannot be saved is marked failed, and logging the failure does not raise."""
        comment = MagicMock(spec=['author', 'subreddit', 'id', 'reddit_id', 'date_posted', 'body', 'body_html'])
        extractor = CommentExtractor(MagicMock(), comment=comment)
        extractor.make_title = MagicMock(side_effect=ValueError('bad title'))
        extractor.extract_content()
        self.assertTrue(extractor.failed_extraction)
        self.assertEqual(Error.TEXT_LINK_FAILURE, extractor.extraction_error)
        self.assertIn('bad title', extractor.failed_extraction_message)
