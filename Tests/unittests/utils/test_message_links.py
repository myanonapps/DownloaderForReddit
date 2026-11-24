"""
Tests for finding the links in the text of imported messages.


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

from DownloaderForReddit.utils.message_links import find_links, has_links


class TestFindLinks(TestCase):
    """Tests for find_links and has_links."""

    def test_no_text(self) -> None:
        """A message without text, or without links, has no links."""
        self.assertEqual([], find_links(None))
        self.assertEqual([], find_links(''))
        self.assertEqual([], find_links('just words, no links'))
        self.assertFalse(has_links('nothing here'))

    def test_bare_urls_in_order(self) -> None:
        """Bare urls are found in the order they appear."""
        body = 'look https://i.redd.it/abc.jpg and http://example.com/page'
        self.assertEqual(['https://i.redd.it/abc.jpg', 'http://example.com/page'], find_links(body))
        self.assertTrue(has_links(body))

    def test_duplicates_listed_once(self) -> None:
        """A url repeated in a message is listed once."""
        self.assertEqual(['https://i.redd.it/a.png'], find_links('https://i.redd.it/a.png https://i.redd.it/a.png'))

    def test_trailing_punctuation_removed(self) -> None:
        """Punctuation that ends a sentence is not part of the url."""
        self.assertEqual(['https://i.redd.it/a.png'], find_links('Did you see https://i.redd.it/a.png?'))
        self.assertEqual(['https://example.com/x'], find_links('it is at https://example.com/x.'))

    def test_markdown_links(self) -> None:
        """Markdown links and angle bracketed urls give their url without the surrounding syntax."""
        self.assertEqual(['https://i.redd.it/a.png'], find_links('[my picture](https://i.redd.it/a.png)'))
        self.assertEqual(['https://example.com/b'], find_links('<https://example.com/b>'))

    def test_balanced_brackets_kept(self) -> None:
        """A closing bracket that the url opened belongs to the url."""
        url = 'https://en.wikipedia.org/wiki/Python_(programming_language)'
        self.assertEqual([url], find_links(f'see {url}'))

    def test_chat_media_url(self) -> None:
        """A Reddit chat media url, which has no file extension, is found whole."""
        url = 'https://matrix.redditspace.com/_matrix/media/r0/download/reddit.com/abcdef123'
        self.assertEqual([url], find_links(url))
