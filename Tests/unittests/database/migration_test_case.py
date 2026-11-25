"""
A base for tests that run one alembic revision's upgrade and downgrade against a temporary SQLite database.


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


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def load_migration(file_name: str) -> ModuleType:
    """
    Loads a migration module from alembic/versions; its file name is not a valid module name.
    :param file_name: The migration's file name.
    :type file_name: str
    :return: The module.
    :rtype: ModuleType
    """
    spec = importlib.util.spec_from_file_location(os.path.splitext(file_name)[0], os.path.join(REPOSITORY_ROOT, 'alembic', 'versions', file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def revision_scripts() -> ScriptDirectory:
    """
    Returns the repository's alembic revisions.
    :return: The script directory.
    :rtype: ScriptDirectory
    """
    config = Config()
    config.set_main_option('script_location', os.path.join(REPOSITORY_ROOT, 'alembic'))
    return ScriptDirectory.from_config(config)


class MigrationTestCase(TestCase):
    """
    Runs the revision in MIGRATION_FILE against a temporary database that starts with every table of the current
    models, as at startup.  Subclasses set MIGRATION_FILE.
    """

    MIGRATION_FILE = ''

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
        migration = load_migration(self.MIGRATION_FILE)
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                getattr(migration, step)()

    def schema(self) -> dict[str, set[str]]:
        """
        Lists every table's columns.
        :return: Table names mapped to their column names.
        :rtype: dict[str, set[str]]
        """
        inspector = sa.inspect(self.engine)
        return {table: {column['name'] for column in inspector.get_columns(table)} for table in inspector.get_table_names()}
