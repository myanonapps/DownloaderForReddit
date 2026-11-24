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

import importlib.util
import os
import tempfile
from types import ModuleType
from unittest import TestCase

import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from DownloaderForReddit.database.models import BaseModel


_REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
_REVISION = 'c4f7a2e9d1b3'
_BASE_REVISION = '7b1f4c8a9d2e'
_MIGRATION_PATH = os.path.join(_REPOSITORY_ROOT, 'alembic', 'versions', f'{_REVISION}_add_export_import_and_nicknames.py')
_NEW_TABLES = ('export_import', 'chat_channel', 'chat_message', 'private_message')
# Foreign keys the upgrade must create: (table, column) -> referenced table.
_FOREIGN_KEYS = {
    ('export_import', 'owner_id'): 'user',
    ('export_import', 'download_session_id'): 'download_session',
    ('chat_channel', 'subreddit_id'): 'subreddit',
    ('chat_message', 'channel_id'): 'chat_channel',
    ('chat_message', 'author_id'): 'reddit_object',
    ('chat_message', 'export_import_id'): 'export_import',
    ('private_message', 'sender_id'): 'reddit_object',
    ('private_message', 'recipient_id'): 'reddit_object',
    ('private_message', 'export_import_id'): 'export_import',
}
_INDEXES = {
    'export_import': {'ix_export_import_file_sha256'},
    'chat_message': {'ix_chat_message_date_posted'},
    'private_message': {'ix_private_message_thread_id', 'ix_private_message_date_sent'},
    'comment': {'ix_comment_link_reddit_id'},
    'content': {'ix_content_chat_message_id', 'ix_content_private_message_id'},
}
_EXTRACTION_COLUMNS = {'extracted', 'extraction_date', 'extraction_error', 'error_message'}
# The content columns tying content to a message, and the tables they reference.
_CONTENT_MESSAGE_KEYS = {'chat_message_id': 'chat_message', 'private_message_id': 'private_message'}


def _load_migration() -> ModuleType:
    """
    Loads the migration module, whose file name is not a valid module name.
    :return: The module.
    :rtype: ModuleType
    """
    spec = importlib.util.spec_from_file_location('export_import_migration', _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestExportImportMigration(TestCase):
    """Runs the migration against databases at the base revision and at the current models."""

    def setUp(self) -> None:
        """Creates a database with every table of the current models."""
        self.temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with  # cleaned up in tearDown
        self.engine = sa.create_engine(f'sqlite:///{os.path.join(self.temp_dir.name, "test.db")}')
        BaseModel.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        """Removes the temporary database."""
        self.engine.dispose()
        self.temp_dir.cleanup()

    def run_migration(self, step: str) -> None:
        """
        Runs upgrade() or downgrade() of the migration against the test database.
        :param step: 'upgrade' or 'downgrade'.
        :type step: str
        """
        migration = _load_migration()
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                getattr(migration, step)()

    def reduce_to_base_revision(self) -> None:
        """Takes the database back to the shape of revision 7b1f4c8a9d2e by removing what the migration adds."""
        self.run_migration('downgrade')

    def schema(self) -> dict[str, set[str]]:
        """
        Lists every table's columns.
        :return: Table names mapped to their column names.
        :rtype: dict[str, set[str]]
        """
        inspector = sa.inspect(self.engine)
        return {table: {column['name'] for column in inspector.get_columns(table)} for table in inspector.get_table_names()}

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
        message tables lack their extraction columns and content lacks its message columns.  The downgrade removes
        everything the revision adds; the export import tables are then made again without the newer columns.
        """
        self.reduce_to_base_revision()
        metadata = sa.MetaData()
        metadata.reflect(bind=self.engine)
        for name in _NEW_TABLES:
            columns = [sa.Column(column.name, column.type, *[sa.ForeignKey(key.target_fullname) for key in column.foreign_keys],
                                 primary_key=column.primary_key, nullable=column.nullable, unique=column.unique)
                       for column in BaseModel.metadata.tables[name].columns if column.name not in _EXTRACTION_COLUMNS]
            sa.Table(name, metadata, *columns)
        metadata.create_all(self.engine)

    def test_upgrade_completes_earlier_form(self) -> None:
        """On a database where an earlier form of the revision ran, upgrade adds the message extraction and content columns."""
        self.make_earlier_form()
        with self.engine.begin() as connection:
            connection.execute(sa.text("INSERT INTO content (title, url) VALUES ('kept', 'https://i.redd.it/a.jpg')"))
        schema = self.schema()
        self.assertFalse(_EXTRACTION_COLUMNS & schema['chat_message'])
        self.assertNotIn('chat_message_id', schema['content'])
        self.run_migration('upgrade')
        self.assert_final_schema()
        with self.engine.connect() as connection:
            self.assertEqual([('kept',)], [tuple(row) for row in connection.execute(sa.text('SELECT title FROM content'))])

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

    def test_head_is_single(self) -> None:
        """The migration is the only head, directly on top of revision 7b1f4c8a9d2e."""
        config = Config()
        config.set_main_option('script_location', os.path.join(_REPOSITORY_ROOT, 'alembic'))
        scripts = ScriptDirectory.from_config(config)
        self.assertEqual([_REVISION], scripts.get_heads())
        self.assertEqual(_BASE_REVISION, scripts.get_revision(_REVISION).down_revision)
