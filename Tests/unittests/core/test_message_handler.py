"""
Tests for extracting the media linked in imported chat and private messages, and for the rule that stored content is
tied to where it was found.


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
from queue import Queue
from threading import Event
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock, patch

from DownloaderForReddit.core.download.downloader import Downloader
from DownloaderForReddit.core.errors import Error
from DownloaderForReddit.core.message_handler import MessageHandler
from DownloaderForReddit.database import UnlinkedContentError
from DownloaderForReddit.database.database_handler import DatabaseHandler
from DownloaderForReddit.database.export_models import ChatChannel, ChatMessage, ChatReaction, ExportImport, PrivateMessage
from DownloaderForReddit.database.models import Content, Post, Subreddit, User
from DownloaderForReddit.utils import injector, system_util


OWNER = 'owner_account'
BASE_DIRECTORY = '/downloads/users'
MESSAGE_DATE = datetime(2024, 4, 1, 10, 0, 0)


class TestMessageHandler(TestCase):
    """Tests for MessageHandler, run against an in-memory database."""

    def setUp(self) -> None:
        """Gives each test a fresh in-memory database, settings that save under BASE_DIRECTORY, and an import."""
        injector.settings_manager = MagicMock(user_save_directory=BASE_DIRECTORY, short_title_char_length=0,
                                              download_reddit_hosted_videos=True, extractor_dict={},
                                              supported_videos_updated=0.0)
        self.db = DatabaseHandler(in_memory=True)
        injector.database_handler = self.db
        with self.db.get_scoped_session() as session:
            owner = User(name=OWNER, significant=True)
            self.export_import = ExportImport(owner=owner, file_name='export.zip')
            session.add_all([owner, User(name='friend'), self.export_import])
            session.commit()
        self.queue: Queue = Queue()

    def add_chat_message(self, body: str) -> int:
        """
        Stores a chat message from 'friend' in a channel named 'Pics', imported by the owner's export.
        :param body: The message text.
        :type body: str
        :return: The message's id.
        :rtype: int
        """
        with self.db.get_scoped_session() as session:
            message = ChatMessage(message_id='m1', body=body, date_posted=MESSAGE_DATE,
                                  channel=ChatChannel(channel_url='channel-1', channel_name='Pics'),
                                  author=session.query(User).filter(User.name == 'friend').one(),
                                  export_import=session.query(ExportImport).one())
            session.add(message)
            session.commit()
            return message.id

    def extract(self, model: type, message_id: int, extractor_dict: Optional[dict[str, bool]] = None) -> None:
        """
        Runs the message handler for a stored message.
        :param model: ChatMessage or PrivateMessage.
        :type model: type
        :param message_id: The message's id.
        :type message_id: int
        :param extractor_dict: The enabled extractors.  When not given, all are enabled but the generic video
                               extractor, which would look ordinary test links up on the network.
        :type extractor_dict: Optional[dict[str, bool]]
        """
        injector.settings_manager.extractor_dict = extractor_dict or {'GenericVideoExtractor': False}
        with self.db.get_scoped_session() as session:
            message = session.query(model).get(message_id)
            MessageHandler(message, self.queue, Event()).extract()

    def queued_ids(self) -> list[int]:
        """
        Returns the content ids put on the download queue.
        :return: The ids.
        :rtype: list[int]
        """
        ids = []
        while not self.queue.empty():
            ids.append(self.queue.get())
        return ids

    def test_reaction_is_not_extracted(self) -> None:
        """A chat reaction is recorded as extracted without content, since its image is stored once for every chat."""
        message_id = self.add_chat_message('https://i.redd.it/abc7081.gif')
        with self.db.get_scoped_session() as session:
            session.query(ChatMessage).get(message_id).reaction = ChatReaction(url='https://i.redd.it/abc7081.gif', enabled=True)
            session.commit()
        self.extract(ChatMessage, message_id)
        with self.db.get_scoped_session() as session:
            self.assertEqual(0, session.query(Content).count())
            self.assertTrue(session.query(ChatMessage).get(message_id).extracted)
        self.assertEqual([], self.queued_ids())

    def test_media_link_becomes_message_content(self) -> None:
        """A media link becomes content tied to the message, with no post, saved in its author's folder."""
        message_id = self.add_chat_message('look https://i.redd.it/abc.jpg and read https://example.com/page')
        self.extract(ChatMessage, message_id)
        with self.db.get_scoped_session() as session:
            content = session.query(Content).one()
            self.assertEqual(message_id, content.chat_message_id)
            self.assertIsNone(content.post)
            self.assertIsNone(content.private_message_id)
            self.assertEqual('https://i.redd.it/abc.jpg', content.url)
            self.assertEqual('jpg', content.extension)
            self.assertEqual('friend', content.user.name)
            expected_directory = system_util.join_path(BASE_DIRECTORY, system_util.clean_path('friend', ends_with_dir=True))
            self.assertEqual(expected_directory, content.directory_path)
            self.assertTrue(content.title.startswith('Pics 2024-04-01 10-00-00'))
            self.assertEqual('friend', content.significant_reddit_object.name)
            self.assertEqual(MESSAGE_DATE, content.source_date)
            self.assertEqual([content.id], self.queued_ids())
            message = session.query(ChatMessage).get(message_id)
            self.assertTrue(message.extracted)
            self.assertIsNone(message.extraction_error)

    def test_author_download_disabled(self) -> None:
        """Nothing is downloaded for an author whose download is disabled, and the message is left for later."""
        with self.db.get_scoped_session() as session:
            session.query(User).filter(User.name == 'friend').one().download_enabled = False
            session.commit()
        message_id = self.add_chat_message('https://i.redd.it/abc.jpg')
        self.extract(ChatMessage, message_id)
        with self.db.get_scoped_session() as session:
            self.assertEqual(0, session.query(Content).count())
            message = session.query(ChatMessage).get(message_id)
            self.assertFalse(message.extracted)
            self.assertIsNone(message.extraction_error)

    def test_authors_settings_decide_file_types(self) -> None:
        """The author's file type settings filter the message's media, not the importing account's."""
        with self.db.get_scoped_session() as session:
            session.query(User).filter(User.name == 'friend').one().download_images = False
            session.commit()
        message_id = self.add_chat_message('https://i.redd.it/abc.jpg')
        self.extract(ChatMessage, message_id)
        with self.db.get_scoped_session() as session:
            self.assertEqual(0, session.query(Content).count())

    def test_private_message_content(self) -> None:
        """Content found in a private message is tied to that private message."""
        with self.db.get_scoped_session() as session:
            message = PrivateMessage(reddit_id='pm1', subject='Photos', body='https://i.redd.it/x.png', date_sent=MESSAGE_DATE,
                                     sender=session.query(User).filter(User.name == 'friend').one(),
                                     export_import=session.query(ExportImport).one())
            session.add(message)
            session.commit()
            message_id = message.id
        self.extract(PrivateMessage, message_id)
        with self.db.get_scoped_session() as session:
            content = session.query(Content).one()
            self.assertEqual(message_id, content.private_message_id)
            self.assertIsNone(content.chat_message_id)
            self.assertTrue(content.title.startswith('Photos 2024-04-01 10-00-00'))

    def test_subreddit_author_content(self) -> None:
        """Media in a modmail message is saved in the sending subreddit's folder, with the subreddit and no user."""
        injector.settings_manager.subreddit_save_directory = '/downloads/subreddits'
        with self.db.get_scoped_session() as session:
            message = PrivateMessage(reddit_id='pm2', subject='Rules', body='https://i.redd.it/rules.png', date_sent=MESSAGE_DATE,
                                     sender=Subreddit(name='modsub'), export_import=session.query(ExportImport).one())
            session.add(message)
            session.commit()
            message_id = message.id
        self.extract(PrivateMessage, message_id)
        with self.db.get_scoped_session() as session:
            content = session.query(Content).one()
            self.assertIsNone(content.user)
            self.assertEqual('modsub', content.subreddit.name)
            self.assertEqual('modsub', content.owner_name)
            expected = system_util.join_path('/downloads/subreddits', system_util.clean_path('modsub', ends_with_dir=True))
            self.assertEqual(expected, content.directory_path)

    def test_link_needing_a_post_fails(self) -> None:
        """A reddit video link can only be extracted from its post, so the message records the failure."""
        message_id = self.add_chat_message('https://v.redd.it/abcdef')
        self.extract(ChatMessage, message_id)
        with self.db.get_scoped_session() as session:
            self.assertEqual(0, session.query(Content).count())
            message = session.query(ChatMessage).get(message_id)
            self.assertFalse(message.extracted)
            self.assertEqual(Error.TEXT_LINK_FAILURE, message.extraction_error)
            self.assertIn('v.redd.it', message.error_message)

    def test_ordinary_links_are_not_failures(self) -> None:
        """Links that no extractor handles are ordinary web links: the message is extracted without content."""
        message_id = self.add_chat_message('read https://example.com/article')
        self.extract(ChatMessage, message_id)
        with self.db.get_scoped_session() as session:
            self.assertEqual(0, session.query(Content).count())
            self.assertTrue(session.query(ChatMessage).get(message_id).extracted)

    def test_loose_extractor_miss_is_not_a_failure(self) -> None:
        """A loosely matching extractor that finds no media in a link leaves the message extracted, not failed."""
        extractor = MagicMock(failed_extraction=True, extraction_error=Error.FAILED_TO_LOCATE, extracted_content=[])
        extractor_class = MagicMock(return_value=extractor, needs_post=False, matches_loosely=True)
        extractor_class.__name__ = 'LooseExtractor'
        message_id = self.add_chat_message('https://example.com/le-page')
        with patch('DownloaderForReddit.core.message_handler.assign_extractor', return_value=extractor_class):
            self.extract(ChatMessage, message_id)
        with self.db.get_scoped_session() as session:
            self.assertTrue(session.query(ChatMessage).get(message_id).extracted)

    def test_strict_extractor_miss_is_a_failure(self) -> None:
        """An extractor made for the link's site that fails records the message as failed."""
        extractor = MagicMock(failed_extraction=True, extraction_error=Error.FAILED_TO_LOCATE, extracted_content=[],
                              failed_extraction_message='Failed to locate content')
        extractor_class = MagicMock(return_value=extractor, needs_post=False, matches_loosely=False)
        message_id = self.add_chat_message('https://imgur.com/gone')
        with patch('DownloaderForReddit.core.message_handler.assign_extractor', return_value=extractor_class):
            self.extract(ChatMessage, message_id)
        with self.db.get_scoped_session() as session:
            message = session.query(ChatMessage).get(message_id)
            self.assertFalse(message.extracted)
            self.assertIn('Failed to locate content', message.error_message)

    def test_disabled_extractor_not_used(self) -> None:
        """An extractor turned off in the settings is not used for message links."""
        message_id = self.add_chat_message('https://i.redd.it/abc.jpg')
        self.extract(ChatMessage, message_id, {'RedditUploadsExtractor': False, 'DirectExtractor': False})
        with self.db.get_scoped_session() as session:
            self.assertEqual(0, session.query(Content).count())

    def test_duplicate_url_filtered(self) -> None:
        """A url already downloaded is filtered as a duplicate, which is not a failure of the message."""
        with self.db.get_scoped_session() as session:
            session.add(Content(url='https://i.redd.it/abc.jpg', post=Post(title='earlier')))
            session.commit()
        message_id = self.add_chat_message('https://i.redd.it/abc.jpg')
        self.extract(ChatMessage, message_id)
        with self.db.get_scoped_session() as session:
            self.assertEqual(1, session.query(Content).count())
            self.assertTrue(session.query(ChatMessage).get(message_id).extracted)


class TestDownloaderMessageContent(TestCase):
    """Tests that the downloader handles content tied to a message, which has no post."""

    def setUp(self) -> None:
        """Stores content found in a chat message whose author hashes duplicates."""
        injector.settings_manager = MagicMock(match_file_modified_to_post_date=True)
        self.db = DatabaseHandler(in_memory=True)
        injector.database_handler = self.db
        self.session = self.db.get_session()
        author = User(name='friend', hash_duplicates=True)
        message = ChatMessage(message_id='m1', date_posted=MESSAGE_DATE, author=author,
                              export_import=ExportImport(owner=User(name=OWNER)))
        self.content = Content(url='https://i.redd.it/a.jpg', title='a', extension='jpg', directory_path='/d',
                               download_title='a', chat_message=message)
        self.session.add(self.content)
        self.session.commit()
        self.downloader = Downloader(download_queue=Queue(), download_session_id=1, stop_run=Event())

    def tearDown(self) -> None:
        """Closes the session."""
        self.session.close()

    def test_hash_setting_from_author(self) -> None:
        """Whether to hash the file comes from the message's author."""
        self.assertTrue(self.downloader.should_use_hash(self.content))

    @patch('DownloaderForReddit.core.download.downloader.system_util.set_file_modify_time')
    def test_file_date_from_message(self, mock_set_time: MagicMock) -> None:
        """The file's modified date is set to the date the message was sent."""
        self.downloader.handle_date_modified(self.content)
        mock_set_time.assert_called_once_with(self.content.get_full_file_path(), MESSAGE_DATE.timestamp())

    def test_error_output_names_message(self) -> None:
        """Download errors describe the message the content came from."""
        with patch('DownloaderForReddit.core.download.downloader.Message.send_download_error') as mock_send:
            self.downloader.output_error(self.content, 'Failed')
        self.assertIn('Message: ', mock_send.call_args.args[0])


class TestContentSource(TestCase):
    """Tests for the rule that content is stored only when tied to a post, comment or message."""

    def setUp(self) -> None:
        """Gives each test a fresh in-memory database."""
        injector.settings_manager = MagicMock()
        self.db = DatabaseHandler(in_memory=True)
        injector.database_handler = self.db

    def test_content_without_source_refused(self) -> None:
        """Content with no post, comment or message cannot be stored."""
        with self.db.get_scoped_session() as session:
            session.add(Content(url='https://i.redd.it/lost.jpg'))
            with self.assertRaises(UnlinkedContentError):
                session.commit()

    def test_message_content_stored(self) -> None:
        """Content tied only to a message is stored."""
        with self.db.get_scoped_session() as session:
            message = ChatMessage(message_id='m9', body='https://i.redd.it/a.jpg')
            session.add(Content(url='https://i.redd.it/a.jpg', chat_message=message))
            session.commit()
            self.assertEqual(message.id, session.query(Content).one().chat_message_id)
