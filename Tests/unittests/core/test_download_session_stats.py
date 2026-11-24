"""
Tests for the statistics gathered at the end of a download run, including runs that only download the media found in
imported chat and private messages, which has no post.


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

from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock

from DownloaderForReddit.core import download_runner_stats
from DownloaderForReddit.core.download_runner import collect_session_tally
from DownloaderForReddit.database.database_handler import DatabaseHandler
from DownloaderForReddit.database.export_models import ChatChannel, ChatMessage, ExportImport
from DownloaderForReddit.database.models import Content, DownloadSession, Post, Subreddit, User
from DownloaderForReddit.utils import injector


class TestDownloadSessionStats(TestCase):
    """Tests for the download session counts and the run tally, run against an in-memory database."""

    def setUp(self) -> None:
        """Gives each test a fresh in-memory database holding one download session."""
        injector.settings_manager = MagicMock()
        self.db = DatabaseHandler(in_memory=True)
        injector.database_handler = self.db
        with self.db.get_scoped_session() as session:
            download_session = DownloadSession(start_time=datetime(2024, 4, 1, 10, 0, 0))
            session.add(download_session)
            session.commit()
            self.download_session_id = download_session.id

    def add_message_content(self, author_name: str) -> None:
        """
        Stores a chat message from a new user and content found in it, downloaded in the test's download session.
        :param author_name: The name of the message's author.
        :type author_name: str
        """
        with self.db.get_scoped_session() as session:
            author = User(name=author_name)
            owner = User(name=f'{author_name}_owner', significant=True)
            message = ChatMessage(message_id=f'{author_name}_m1', body='https://i.redd.it/abc.jpg',
                                  date_posted=datetime(2024, 4, 1, 9, 0, 0),
                                  channel=ChatChannel(channel_url=f'{author_name}_channel', channel_name='Pics'),
                                  author=author, export_import=ExportImport(owner=owner, file_name='export.zip'))
            session.add(message)
            session.flush()
            session.add(Content(url='https://i.redd.it/abc.jpg', user=author, chat_message_id=message.id,
                                download_session_id=self.download_session_id))
            session.commit()

    def test_message_content_counts_its_author(self) -> None:
        """A run that only downloads message media counts and names the message's author."""
        self.add_message_content('friend')
        with self.db.get_scoped_session() as session:
            download_session = session.query(DownloadSession).get(self.download_session_id)
            self.assertEqual(1, download_session.get_downloaded_user_count(session=session))
            self.assertEqual(1, download_session.get_downloaded_user_count(significant=False, session=session))
            self.assertEqual(0, download_session.get_downloaded_subreddit_count(session=session))
            tally = collect_session_tally(session, self.download_session_id)
            self.assertEqual({'friend'}, tally.user_names)
            self.assertEqual(set(), tally.subreddit_names)
            download_session.end_time = datetime(2024, 4, 1, 10, 5, 0)
            stats = download_runner_stats.from_session(download_session, user_names=tally.user_names,
                                                       subreddit_names=tally.subreddit_names)
            self.assertEqual(['friend'], stats.get_user_names())
            self.assertEqual(1, stats.get_user_significant_count())
            self.assertEqual(1, stats.get_content_downloaded_count())

    def test_total_counts_use_authors_and_subreddits(self) -> None:
        """The total user count counts post authors and the total subreddit count counts the posts' subreddits."""
        with self.db.get_scoped_session() as session:
            first_author = User(name='author_one', significant=True)
            second_author = User(name='author_two')
            subreddit = Subreddit(name='pics')
            for title, author in (('first', first_author), ('second', second_author)):
                session.add(Post(title=title, author=author, subreddit=subreddit, significant_reddit_object=first_author,
                                 download_session_id=self.download_session_id))
            session.commit()
            download_session = session.query(DownloadSession).get(self.download_session_id)
            self.assertEqual(2, download_session.get_downloaded_user_count(significant=False, session=session))
            self.assertEqual(1, download_session.get_downloaded_user_count(session=session))
            self.assertEqual(1, download_session.get_downloaded_subreddit_count(significant=False, session=session))
            self.assertEqual(0, download_session.get_downloaded_subreddit_count(session=session))
            self.assertEqual({'author_one', 'author_two'}, collect_session_tally(session, self.download_session_id).user_names)
