"""
Tests for importing a Reddit data export archive into the database.


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
import threading
from unittest import TestCase
from unittest.mock import MagicMock

from sqlalchemy import or_

from DownloaderForReddit.core.const import USER_OBJECT
from DownloaderForReddit.database.database_handler import DatabaseHandler
from DownloaderForReddit.database.export_models import ExportImport, ChatChannel, ChatMessage, PrivateMessage
from DownloaderForReddit.database.models import Post, Comment, User, RedditObjectList, Subreddit
from DownloaderForReddit.utils import injector
from DownloaderForReddit.utils.importers.reddit_export.export_importer import (ExportImportOptions, ExportImportStats,
                                                                               RedditExportImporter)
from DownloaderForReddit.utils.importers.reddit_export.export_reader import RedditExportReader
from Tests.unittests.utils.importers.export_fixture import ACCOUNT, CHAT_HISTORY, COMMENTS, POSTS, csv_text, write_export


class TestRedditExportImporter(TestCase):
    """Tests for RedditExportImporter."""

    def setUp(self) -> None:
        """Gives each test a fresh in-memory database and a temporary directory for its archive."""
        injector.settings_manager = MagicMock()
        self.db = DatabaseHandler(in_memory=True)
        injector.database_handler = self.db
        self.temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with  # cleaned up in tearDown
        self.export_path = write_export(self.temp_dir.name)

    def tearDown(self) -> None:
        """Removes the temporary directory."""
        self.temp_dir.cleanup()

    def run_import(self, path: str = '', **options: bool) -> ExportImportStats:
        """
        Imports an archive with the given options.
        :param path: The archive to import; the default synthetic export when empty.
        :type path: str
        :param options: ExportImportOptions flags to override.
        :type options: bool
        :return: The import stats.
        :rtype: ExportImportStats
        """
        with RedditExportReader(path or self.export_path) as reader:
            return RedditExportImporter(reader, ExportImportOptions(account_name=ACCOUNT, chunk_size=2, **options)).run()

    def test_import_counts(self) -> None:
        """Every record in the export is added, and the import is recorded."""
        stats = self.run_import()
        self.assertEqual(2, stats.posts_added)
        self.assertEqual(3, stats.comments_added)
        self.assertEqual(4, stats.chat_messages_added)
        self.assertEqual(3, stats.chat_channels_added)
        self.assertEqual(5, stats.private_messages_added)
        self.assertEqual(2, len(stats.new_post_ids))
        with self.db.get_scoped_session() as session:
            export_import = session.query(ExportImport).one()
            self.assertEqual(ACCOUNT, export_import.owner.name)
            self.assertEqual(3, export_import.comment_count)
            self.assertIsNotNone(export_import.download_session.end_time)

    def test_reimport_adds_nothing(self) -> None:
        """Importing the same export twice adds no duplicate rows."""
        self.run_import()
        stats = self.run_import()
        self.assertEqual(0, stats.total_added)
        self.assertEqual(2, stats.posts_skipped)
        self.assertEqual(3, stats.comments_skipped)
        self.assertEqual(4, stats.chat_messages_skipped)
        self.assertEqual(5, stats.private_messages_skipped)
        with self.db.get_scoped_session() as session:
            self.assertEqual(2, session.query(Post).count())
            self.assertEqual(3, session.query(ChatChannel).count())

    def test_newer_export_adds_only_new_rows(self) -> None:
        """A later export of the same account only adds its new records."""
        self.run_import()
        newer_posts = POSTS + [['p3', '', '2024-01-01 00:00:00 UTC', '', 'pics', '0', 'New one', 'https://i.redd.it/n.jpg', '']]
        newer = write_export(self.temp_dir.name, {'posts.csv': csv_text(newer_posts)}, name='newer.zip')
        stats = self.run_import(newer)
        self.assertEqual(1, stats.posts_added)
        self.assertEqual(2, stats.posts_skipped)

    def test_posts(self) -> None:
        """Posts belong to the owner, are left unextracted, and get a domain."""
        self.run_import()
        with self.db.get_scoped_session() as session:
            link_post = session.query(Post).filter(Post.reddit_id == 'p1').one()
            text_post = session.query(Post).filter(Post.reddit_id == 'p2').one()
            self.assertEqual(ACCOUNT, link_post.author.name)
            self.assertEqual(ACCOUNT, link_post.significant_reddit_object.name)
            self.assertTrue(link_post.significant_reddit_object.significant)
            self.assertFalse(link_post.extracted)
            self.assertEqual('i.redd.it', link_post.domain)
            self.assertEqual('pics', link_post.subreddit.name)
            self.assertTrue(text_post.is_self)
            self.assertEqual('self.test', text_post.domain)
            self.assertEqual('https://www.reddit.com/r/test/comments/p2/a_text_post/', text_post.url)
            self.assertIn('<strong>bold</strong>', text_post.text_html)

    def test_comment_relationships(self) -> None:
        """Comments link to imported posts and parents, and keep the post id when the post is not stored."""
        self.run_import()
        with self.db.get_scoped_session() as session:
            top = session.query(Comment).filter(Comment.reddit_id == 'c1').one()
            reply = session.query(Comment).filter(Comment.reddit_id == 'c2').one()
            orphan = session.query(Comment).filter(Comment.reddit_id == 'c3').one()
            self.assertEqual('p2', top.post.reddit_id)
            self.assertEqual(top.id, reply.parent_id)
            self.assertIsNone(orphan.post)
            self.assertIsNone(orphan.post_title)
            self.assertEqual('zz9', orphan.link_reddit_id)
            self.assertIn('https://i.redd.it/media1.png', orphan.body)

    def test_comments_imported_before_posts_are_attached(self) -> None:
        """Comments imported without their posts are attached once a later import adds the posts."""
        comments_only = write_export(self.temp_dir.name, {'comments.csv': csv_text(COMMENTS)}, name='comments.zip')
        self.run_import(comments_only)
        self.run_import()
        with self.db.get_scoped_session() as session:
            self.assertEqual('p2', session.query(Comment).filter(Comment.reddit_id == 'c1').one().post.reddit_id)

    def test_chats(self) -> None:
        """Chat messages are grouped into channels and mapped to users."""
        self.run_import()
        with self.db.get_scoped_session() as session:
            direct = session.query(ChatChannel).filter(ChatChannel.channel_url == 'sendbird_group_channel_1').one()
            self.assertEqual(2, len(direct.messages))
            self.assertIsNone(direct.channel_name)
            self.assertEqual('export_owner, friend_two', direct.display_name)
            named = session.query(ChatChannel).filter(ChatChannel.channel_url == 'sendbird_group_channel_2').one()
            self.assertEqual('Group chat', named.display_name)
            alone = session.query(ChatChannel).filter(ChatChannel.channel_url.like('%abcdefghij%')).one()
            self.assertEqual([ACCOUNT], [person.name for person in alone.participants])
            self.assertEqual(ACCOUNT, alone.display_name)
            message = session.query(ChatMessage).filter(ChatMessage.message_id == 'msg-2').one()
            self.assertEqual('friend_two', message.author.name)

    def test_private_messages(self) -> None:
        """
        Private messages keep their thread, and every sender and recipient is a reddit object: users by name,
        subreddit senders as subreddits, and deleted accounts as the shared placeholder user.
        """
        self.run_import()
        with self.db.get_scoped_session() as session:
            first = session.query(PrivateMessage).filter(PrivateMessage.reddit_id == 'm1').one()
            self.assertEqual('m1', first.thread_id)
            self.assertEqual(ACCOUNT, first.sender.name)
            self.assertEqual('friend_one', first.recipient.name)
            archived = session.query(PrivateMessage).filter(PrivateMessage.reddit_id == 'm0').one()
            self.assertTrue(archived.archived)
            self.assertEqual('deleted', archived.sender.name)
            self.assertIsInstance(archived.sender, User)
            # Every person gets a reddit object: subreddit senders become subreddits, odd names become users, and
            # deleted accounts share one placeholder.
            modmail = session.query(PrivateMessage).filter(PrivateMessage.reddit_id == 'm8').one()
            self.assertIsInstance(modmail.sender, Subreddit)
            self.assertEqual('modsub', modmail.sender.name)
            self.assertFalse(modmail.sender.significant)
            gone = session.query(PrivateMessage).filter(PrivateMessage.reddit_id == 'm7').one()
            old = session.query(PrivateMessage).filter(PrivateMessage.reddit_id == 'm0').one()
            self.assertEqual(old.sender_id, gone.sender_id)
            self.assertIsInstance(gone.recipient, User)
            self.assertEqual('ab', gone.recipient.name)
            self.assertFalse(gone.recipient.significant)
            self.assertEqual(0, session.query(PrivateMessage).filter(or_(PrivateMessage.sender_id.is_(None),
                                                                          PrivateMessage.recipient_id.is_(None))).count())

    def test_users_are_not_duplicated(self) -> None:
        """Each person gets a single User row, however often they appear."""
        self.run_import()
        with self.db.get_scoped_session() as session:
            names = sorted(user.name for user in session.query(User))
        self.assertEqual(sorted([ACCOUNT, 'ab', 'deleted', 'friend_one', 'friend_two', 'friend_three']), names)

    def significance(self) -> dict[str, bool]:
        """
        Returns every stored user's significant flag.
        :return: User names mapped to their flag.
        :rtype: dict[str, bool]
        """
        with self.db.get_scoped_session() as session:
            return {user.name: user.significant for user in session.query(User)}

    def add_existing_owner(self, significant: bool) -> None:
        """
        Stores the export's account before the import, as if it was already known.
        :param significant: The existing user's significant flag.
        :type significant: bool
        """
        with self.db.get_scoped_session() as session:
            session.add(User(name=ACCOUNT, significant=significant))
            session.commit()

    def test_new_owner_is_significant(self) -> None:
        """An owner that is not stored yet is created significant; the people they talk to are not."""
        self.run_import()
        flags = self.significance()
        self.assertTrue(flags[ACCOUNT])
        self.assertFalse(flags['friend_one'])
        self.assertFalse(flags['friend_two'])

    def test_existing_insignificant_owner_is_left_alone(self) -> None:
        """An owner that already exists keeps its flag, and is not duplicated."""
        self.add_existing_owner(significant=False)
        self.run_import()
        self.assertFalse(self.significance()[ACCOUNT])
        with self.db.get_scoped_session() as session:
            self.assertEqual(1, session.query(User).filter(User.name == ACCOUNT).count())

    def test_existing_significant_owner_stays_significant(self) -> None:
        """An owner that is already significant stays significant."""
        self.add_existing_owner(significant=True)
        self.run_import()
        self.assertTrue(self.significance()[ACCOUNT])

    def test_invalid_account_name_raises(self) -> None:
        """An account name that is not a valid reddit user name is rejected before anything is imported."""
        with RedditExportReader(self.export_path) as reader, self.assertRaises(ValueError):
            RedditExportImporter(reader, ExportImportOptions(account_name='not a name!')).run()
        with self.db.get_scoped_session() as session:
            self.assertEqual(0, session.query(Post).count())
            self.assertEqual(0, session.query(ExportImport).count())

    def test_disabled_types_are_skipped(self) -> None:
        """Record types that are switched off are not imported."""
        stats = self.run_import(import_chats=False, import_private_messages=False)
        self.assertEqual(0, stats.chat_messages_added)
        self.assertEqual(0, stats.private_messages_added)
        self.assertEqual(2, stats.posts_added)

    def test_stop_event_cancels(self) -> None:
        """A set stop event stops the import before any records are written."""
        stop = threading.Event()
        stop.set()
        with RedditExportReader(self.export_path) as reader:
            stats = RedditExportImporter(reader, ExportImportOptions(account_name=ACCOUNT), stop_event=stop).run()
        self.assertTrue(stats.cancelled)
        self.assertEqual(0, stats.total_added)


class TestRedditExportImporterAccountList(TestCase):
    """Tests for adding the export's account to a user list."""

    def setUp(self) -> None:
        """Gives each test a fresh in-memory database and a temporary directory for its archive."""
        injector.settings_manager = MagicMock()
        self.db = DatabaseHandler(in_memory=True)
        injector.database_handler = self.db
        self.temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with  # cleaned up in tearDown
        self.export_path = write_export(self.temp_dir.name)

    def tearDown(self) -> None:
        """Removes the temporary directory."""
        self.temp_dir.cleanup()

    def make_user_list(self, name: str = 'Imported', post_limit: int = 77) -> int:
        """
        Creates a user list.
        :param name: The list name.
        :type name: str
        :param post_limit: The list's default post limit, to check that a new member takes the list's defaults.
        :type post_limit: int
        :return: The new list's id.
        :rtype: int
        """
        with self.db.get_scoped_session() as session:
            user_list = RedditObjectList(name=name, list_type=USER_OBJECT, post_limit=post_limit)
            session.add(user_list)
            session.commit()
            return user_list.id

    def import_into_list(self, list_id: int) -> None:
        """
        Imports the default export, asking for the account to be added to a list.
        :param list_id: The list id.
        :type list_id: int
        :return: None
        :rtype: None
        """
        with RedditExportReader(self.export_path) as reader:
            RedditExportImporter(reader, ExportImportOptions(account_name=ACCOUNT, account_list_id=list_id)).run()

    def test_new_account_added_to_list(self) -> None:
        """A newly created account is added to the chosen list and takes its download defaults."""
        list_id = self.make_user_list()
        self.import_into_list(list_id)
        with self.db.get_scoped_session() as session:
            user_list = session.query(RedditObjectList).get(list_id)
            members = user_list.reddit_objects.all()
            self.assertEqual([ACCOUNT], [member.name for member in members])
            self.assertEqual(77, members[0].post_limit)
            self.assertTrue(members[0].significant)

    def test_existing_account_not_added_to_list(self) -> None:
        """An account already in the database is not added to a list, and its settings are left as they were."""
        with self.db.get_scoped_session() as session:
            session.add(User(name=ACCOUNT, post_limit=5))
            session.commit()
        list_id = self.make_user_list()
        self.import_into_list(list_id)
        with self.db.get_scoped_session() as session:
            self.assertEqual(0, session.query(RedditObjectList).get(list_id).reddit_objects.count())
            self.assertEqual(5, session.query(User).filter(User.name == ACCOUNT).one().post_limit)

    def test_unknown_list_raises(self) -> None:
        """A list id that names no user list is refused."""
        with self.assertRaises(ValueError):
            self.import_into_list(12345)


class TestSharedChatChannels(TestCase):
    """Tests for naming chat channels, which belong to no account."""

    def setUp(self) -> None:
        """Gives each test a fresh in-memory database and a temporary directory for its archives."""
        injector.settings_manager = MagicMock()
        self.db = DatabaseHandler(in_memory=True)
        injector.database_handler = self.db
        self.temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with  # cleaned up in tearDown

    def tearDown(self) -> None:
        """Removes the temporary directory."""
        self.temp_dir.cleanup()

    def test_channel_without_messages_is_named_after_room(self) -> None:
        """A channel nobody is known to have written in is named after its room id."""
        with self.db.get_scoped_session() as session:
            channel = ChatChannel(channel_url='https://chat.reddit.com/room/!qrstuvwxyz0123:reddit.com')
            session.add(channel)
            session.commit()
            self.assertEqual('Chat qrstuvwxyz', channel.display_name)

    def test_shared_channel_has_no_owner(self) -> None:
        """
        Exports of two accounts that chatted with each other share one channel, whose participants are both accounts
        whichever export was imported first.
        """
        for first, second in (('export_owner', 'friend_two'), ('friend_two', 'export_owner')):
            with self.subTest(first=first):
                self.db = DatabaseHandler(in_memory=True)
                injector.database_handler = self.db
                for account in (first, second):
                    history = csv_text(CHAT_HISTORY[:3] + [['msg-9', '2024-04-01 10:02:00 UTC', '', '/u/friend_two', 'bye', '',
                                                            'sendbird_group_channel_1', '', '', 'direct']])
                    statistics = csv_text([['statistic', 'value'], ['account name', account]])
                    path = write_export(self.temp_dir.name, {'chat_history.csv': history, 'statistics.csv': statistics},
                                        name=f'{account}.zip')
                    with RedditExportReader(path) as reader:
                        RedditExportImporter(reader, ExportImportOptions(account_name=account)).run()
                with self.db.get_scoped_session() as session:
                    channel = session.query(ChatChannel).one()
                    self.assertEqual(['export_owner', 'friend_two'], [person.name for person in channel.participants])
                    self.assertEqual('export_owner, friend_two', channel.display_name)
                    self.assertEqual(3, len(channel.messages))
