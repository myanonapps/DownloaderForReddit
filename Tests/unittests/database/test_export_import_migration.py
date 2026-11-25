"""
Tests for the migration that adds the Reddit data export import tables, comment.link_reddit_id, reddit object
nicknames, message link extraction state and the content columns tying content to a message, on top of revision
7b1f4c8a9d2e.


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

from typing import Optional

import sqlalchemy as sa

from DownloaderForReddit.database.models import BaseModel
from Tests.unittests.database.migration_test_case import MigrationTestCase, revision_scripts


_REVISION = 'c4f7a2e9d1b3'
_BASE_REVISION = '7b1f4c8a9d2e'
_NEW_TABLES = ('export_import', 'chat_channel', 'chat_reaction', 'chat_message', 'private_message')
HEART = 'https://i.redd.it/8r21ukpfa7081.gif'
# Foreign keys the upgrade must create: (table, column) -> referenced table.
_FOREIGN_KEYS = {
    ('export_import', 'owner_id'): 'user',
    ('export_import', 'download_session_id'): 'download_session',
    ('chat_channel', 'subreddit_id'): 'subreddit',
    ('chat_message', 'channel_id'): 'chat_channel',
    ('chat_message', 'author_id'): 'reddit_object',
    ('chat_message', 'export_import_id'): 'export_import',
    ('chat_message', 'reaction_id'): 'chat_reaction',
    ('private_message', 'sender_id'): 'reddit_object',
    ('private_message', 'recipient_id'): 'reddit_object',
    ('private_message', 'export_import_id'): 'export_import',
}
_INDEXES = {
    'export_import': {'ix_export_import_file_sha256'},
    'chat_message': {'ix_chat_message_date_posted', 'ix_chat_message_reaction_id'},
    'private_message': {'ix_private_message_thread_id', 'ix_private_message_date_sent'},
    'comment': {'ix_comment_link_reddit_id'},
    'content': {'ix_content_chat_message_id', 'ix_content_private_message_id'},
}
_EXTRACTION_COLUMNS = {'extracted', 'extraction_date', 'extraction_error', 'error_message'}
# What an earlier form of the revision did not make: the message extraction columns, chat_message.reaction_id and
# the chat_reaction table.
_EARLIER_FORM_COLUMNS = _EXTRACTION_COLUMNS | {'reaction_id'}
_EARLIER_FORM_TABLES = tuple(table for table in _NEW_TABLES if table != 'chat_reaction')
# The content columns tying content to a message, and the tables they reference.
_CONTENT_MESSAGE_KEYS = {'chat_message_id': 'chat_message', 'private_message_id': 'private_message'}


class TestExportImportMigration(MigrationTestCase):
    """Runs the migration against databases at the base revision and at the current models."""

    MIGRATION_FILE = f'{_REVISION}_add_export_import_and_nicknames.py'

    def reduce_to_base_revision(self) -> None:
        """Takes the database back to the shape of revision 7b1f4c8a9d2e by removing what the migration adds."""
        self.run_migration('downgrade')

    def assert_final_schema(self) -> None:
        """Checks that the database has the tables, columns, indexes and foreign keys of the current models."""
        inspector = sa.inspect(self.engine)
        schema = self.schema()
        for table in _NEW_TABLES:
            self.assertEqual({column.name for column in BaseModel.metadata.tables[table].columns}, schema[table])
        self.assertIn('link_reddit_id', schema['comment'])
        self.assertIn('nickname', schema['reddit_object'])
        for table, indexes in _INDEXES.items():
            self.assertLessEqual(indexes, {index['name'] for index in inspector.get_indexes(table)})
        references = {(table, key['constrained_columns'][0]): key['referred_table']
                      for table in _NEW_TABLES for key in inspector.get_foreign_keys(table)}
        self.assertEqual(_FOREIGN_KEYS, references)
        content_references = {key['constrained_columns'][0]: key['referred_table'] for key in inspector.get_foreign_keys('content')}
        for column, table in _CONTENT_MESSAGE_KEYS.items():
            self.assertEqual(table, content_references.get(column))

    def make_earlier_form(self) -> None:
        """
        Takes the database to the shape an earlier form of the revision left: the export import tables exist, but the
        message tables lack their extraction columns, chat messages lack their reaction, there is no chat_reaction
        table, and content lacks its message columns.  The downgrade removes everything the revision adds; the export
        import tables are then made again without the newer columns.
        """
        self.reduce_to_base_revision()
        metadata = sa.MetaData()
        metadata.reflect(bind=self.engine)
        for name in _EARLIER_FORM_TABLES:
            columns = [sa.Column(column.name, column.type, *[sa.ForeignKey(key.target_fullname) for key in column.foreign_keys],
                                 primary_key=column.primary_key, nullable=column.nullable, unique=column.unique)
                       for column in BaseModel.metadata.tables[name].columns if column.name not in _EARLIER_FORM_COLUMNS]
            sa.Table(name, metadata, *columns)
        metadata.create_all(self.engine)

    def test_upgrade_completes_earlier_form(self) -> None:
        """On a database where an earlier form of the revision ran, upgrade adds the message, reaction and content columns."""
        self.make_earlier_form()
        with self.engine.begin() as connection:
            connection.execute(sa.text("INSERT INTO content (title, url) VALUES ('kept', 'https://i.redd.it/a.jpg')"))
        schema = self.schema()
        self.assertFalse(_EARLIER_FORM_COLUMNS & schema['chat_message'])
        self.assertNotIn('chat_reaction', schema)
        self.assertNotIn('chat_message_id', schema['content'])
        self.run_migration('upgrade')
        self.assert_final_schema()
        with self.engine.connect() as connection:
            self.assertEqual([('kept',)], [tuple(row) for row in connection.execute(sa.text('SELECT title FROM content'))])

    def add_message(self, message_id: str, body: str, parent: Optional[str] = None) -> None:
        """
        Stores a chat message with raw SQL, as an earlier form of the revision holds it.
        :param message_id: The message's id.
        :type message_id: str
        :param body: The message text.
        :type body: str
        :param parent: The id of the message it replies to, if any.
        :type parent: Optional[str]
        """
        with self.engine.begin() as connection:
            connection.execute(sa.text('INSERT INTO chat_message (message_id, body, thread_parent_message_id) VALUES (:message_id, :body, :parent)'),
                               {'message_id': message_id, 'body': body, 'parent': parent})

    def reaction_links(self) -> dict[str, tuple[Optional[str], bool]]:
        """
        Reads each chat message's reaction url and whether it is extracted.
        :return: The message ids mapped to their reaction url (or None) and extracted flag.
        :rtype: dict[str, tuple[Optional[str], bool]]
        """
        with self.engine.connect() as connection:
            rows = connection.execute(sa.text('SELECT m.message_id, r.url, m.extracted FROM chat_message m '
                                              'LEFT JOIN chat_reaction r ON r.id = m.reaction_id'))
            return {message_id: (url, bool(extracted)) for message_id, url, extracted in rows}

    def test_upgrade_links_existing_reactions(self) -> None:
        """Upgrade links the stored replies whose whole text is a reaction GIF or PNG, one reaction per url, and marks them extracted."""
        self.make_earlier_form()
        self.add_message('root', 'hello')
        self.add_message('like-1', f' {HEART} ', 'root')
        self.add_message('like-2', HEART.upper(), 'root')
        self.add_message('top', HEART)
        self.add_message('png', 'https://i.redd.it/abc.png', 'root')
        self.add_message('jpg', 'https://i.redd.it/abc.jpg', 'root')
        self.add_message('text', f'look {HEART}', 'root')
        self.run_migration('upgrade')
        links = self.reaction_links()
        self.assertEqual((HEART, True), links['like-1'])
        self.assertEqual((HEART, True), links['like-2'])
        self.assertEqual(('https://i.redd.it/abc.png', True), links['png'])
        for message_id in ('root', 'top', 'jpg', 'text'):
            self.assertIsNone(links[message_id][0])
            self.assertFalse(links[message_id][1])
        with self.engine.connect() as connection:
            self.assertEqual(2, connection.execute(sa.text('SELECT count(*) FROM chat_reaction')).scalar())

    def test_upgrade_creates_final_schema(self) -> None:
        """From the base revision, upgrade builds the schema of the current models."""
        self.reduce_to_base_revision()
        self.run_migration('upgrade')
        self.assert_final_schema()

    def test_upgrade_skips_existing(self) -> None:
        """On a database already created from the current models, as at startup, upgrade changes nothing."""
        before = self.schema()
        self.run_migration('upgrade')
        self.assertEqual(before, self.schema())
        self.assert_final_schema()

    def test_downgrade_returns_to_base(self) -> None:
        """Downgrade removes the new tables and columns and leaves existing data alone."""
        with self.engine.begin() as connection:
            connection.execute(sa.text("INSERT INTO reddit_object (name, nickname, object_type) VALUES ('someone', 'Nick', 'USER')"))
        self.run_migration('downgrade')
        schema = self.schema()
        for table in _NEW_TABLES:
            self.assertNotIn(table, schema)
        self.assertNotIn('link_reddit_id', schema['comment'])
        self.assertNotIn('nickname', schema['reddit_object'])
        self.assertFalse(set(_CONTENT_MESSAGE_KEYS) & schema['content'])
        self.assertNotIn('ix_comment_link_reddit_id', {index['name'] for index in sa.inspect(self.engine).get_indexes('comment')})
        with self.engine.connect() as connection:
            self.assertEqual([('someone',)], [tuple(row) for row in connection.execute(sa.text('SELECT name FROM reddit_object'))])

    def test_revision_follows_base(self) -> None:
        """The migration is the only head, directly on top of revision 7b1f4c8a9d2e."""
        scripts = revision_scripts()
        self.assertEqual([_REVISION], scripts.get_heads())
        self.assertEqual(_BASE_REVISION, scripts.get_revision(_REVISION).down_revision)
