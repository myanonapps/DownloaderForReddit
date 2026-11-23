"""
Tests for writing backup archives.


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

import json
import os
import sqlite3
import tarfile
import tempfile
import threading
from contextlib import closing
from typing import Optional
from unittest import TestCase
from unittest.mock import patch

from DownloaderForReddit.utils.backup.backup_creator import (BackupCreator, BackupOptions, BackupStats, CONFIG_ARCNAME,
                                                             DATABASE_ARCNAME, MANIFEST_ARCNAME, SHARED_ARCROOT,
                                                             SUBREDDITS_ARCROOT, USERS_ARCROOT)


def write_file(path: str, text: str = 'data') -> str:
    """
    Writes a small text file, creating its directory.
    :param path: The file to write.
    :type path: str
    :param text: The file's contents.
    :type text: str
    :return: The path written.
    :rtype: str
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file:
        file.write(text)
    return path


class TestBackupCreator(TestCase):
    """Tests for BackupCreator."""

    def setUp(self) -> None:
        """Creates a temporary data directory with a database and settings file, and two download directories."""
        self.temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with  # cleaned up in tearDown
        root = self.temp_dir.name
        self.database_path = os.path.join(root, 'data', 'dfr.db')
        os.makedirs(os.path.dirname(self.database_path))
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute('CREATE TABLE post (id INTEGER PRIMARY KEY, title TEXT)')
            connection.executemany('INSERT INTO post (title) VALUES (?)', [('one',), ('two',)])
            connection.commit()
        self.config_path = write_file(os.path.join(root, 'data', 'config.toml'), '[core]\n')
        self.user_directory = os.path.join(root, 'users')
        self.subreddit_directory = os.path.join(root, 'subreddits')
        write_file(os.path.join(self.user_directory, 'alice', 'a.jpg'))
        write_file(os.path.join(self.user_directory, 'bob', 'b.mp4'))
        write_file(os.path.join(self.subreddit_directory, 'pics', 'c.png'))
        self.destination = os.path.join(root, 'backups')

    def tearDown(self) -> None:
        """Removes the temporary directory."""
        self.temp_dir.cleanup()

    def make_options(self, **overrides: Optional[str]) -> BackupOptions:
        """
        Builds options that back up the database only, with the given fields overridden.
        :param overrides: BackupOptions fields to set.
        :type overrides: Optional[str]
        :return: The options.
        :rtype: BackupOptions
        """
        options = BackupOptions(destination_directory=self.destination, database_path=self.database_path, config_path=None)
        for key, value in overrides.items():
            setattr(options, key, value)
        return options

    @staticmethod
    def archive_names(stats: BackupStats) -> set[str]:
        """
        Lists the member names of a finished archive.
        :param stats: The results of the backup.
        :type stats: BackupStats
        :return: The member names.
        :rtype: set[str]
        """
        with tarfile.open(stats.archive_path, 'r:gz') as archive:
            return set(archive.getnames())

    @staticmethod
    def read_manifest(stats: BackupStats) -> dict:
        """
        Reads the manifest of a finished archive.
        :param stats: The results of the backup.
        :type stats: BackupStats
        :return: The manifest.
        :rtype: dict
        """
        with tarfile.open(stats.archive_path, 'r:gz') as archive:
            return json.load(archive.extractfile(MANIFEST_ARCNAME))

    def test_database_only_by_default(self) -> None:
        """Only the database and the manifest are archived, and the archived database holds the rows."""
        stats = BackupCreator(self.make_options()).run()
        self.assertFalse(stats.cancelled)
        self.assertTrue(stats.archive_path.endswith('.tar.gz'))
        self.assertEqual({DATABASE_ARCNAME, MANIFEST_ARCNAME}, self.archive_names(stats))
        self.assertEqual([os.path.basename(stats.archive_path)], os.listdir(self.destination))
        extract_dir = os.path.join(self.temp_dir.name, 'extract')
        with tarfile.open(stats.archive_path, 'r:gz') as archive:
            archive.extract(DATABASE_ARCNAME, extract_dir, filter='data')
        with closing(sqlite3.connect(os.path.join(extract_dir, DATABASE_ARCNAME))) as connection:
            self.assertEqual(2, connection.execute('SELECT COUNT(*) FROM post').fetchone()[0])
        manifest = self.read_manifest(stats)
        self.assertIsNone(manifest['config'])
        self.assertIsNone(manifest['user_directory'])

    def test_snapshot_excludes_uncommitted_writes(self) -> None:
        """A write transaction open on another connection does not block the backup and is not included in it."""
        with closing(sqlite3.connect(self.database_path)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("INSERT INTO post (title) VALUES ('uncommitted')")
            snapshot = os.path.join(self.temp_dir.name, 'snapshot.db')
            BackupCreator.snapshot_database(self.database_path, snapshot)
            writer.rollback()
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(2, connection.execute('SELECT COUNT(*) FROM post').fetchone()[0])

    def test_missing_database_raises(self) -> None:
        """A missing database is an error, and no archive is left behind."""
        with self.assertRaises(FileNotFoundError):
            BackupCreator(self.make_options(database_path=os.path.join(self.temp_dir.name, 'nope.db'))).run()
        self.assertFalse(os.path.exists(self.destination))

    def test_config_included_when_chosen(self) -> None:
        """The settings file is archived when it is chosen."""
        stats = BackupCreator(self.make_options(config_path=self.config_path)).run()
        self.assertIn(CONFIG_ARCNAME, self.archive_names(stats))
        self.assertEqual(CONFIG_ARCNAME, self.read_manifest(stats)['config']['archive_path'])

    def test_download_directories(self) -> None:
        """Separate user and subreddit directories are archived under their own roots."""
        stats = BackupCreator(self.make_options(user_directory=self.user_directory, subreddit_directory=self.subreddit_directory)).run()
        names = self.archive_names(stats)
        self.assertIn(f'{USERS_ARCROOT}/alice/a.jpg', names)
        self.assertIn(f'{USERS_ARCROOT}/bob/b.mp4', names)
        self.assertIn(f'{SUBREDDITS_ARCROOT}/pics/c.png', names)
        self.assertEqual(4, stats.files_added)
        manifest = self.read_manifest(stats)
        self.assertEqual(USERS_ARCROOT, manifest['user_directory']['archive_path'])
        self.assertEqual(SUBREDDITS_ARCROOT, manifest['subreddit_directory']['archive_path'])

    def test_same_directory_archived_once(self) -> None:
        """When both directories are the same, its files are archived once."""
        stats = BackupCreator(self.make_options(user_directory=self.user_directory, subreddit_directory=self.user_directory)).run()
        files = [name for name in self.archive_names(stats) if name.startswith('downloads/')]
        self.assertEqual(sorted([f'{SHARED_ARCROOT}/alice/a.jpg', f'{SHARED_ARCROOT}/bob/b.mp4']), sorted(files))

    def test_nested_directory_archived_once(self) -> None:
        """When one directory is inside the other, only the outer one is archived, and the manifest says where each went."""
        inner = os.path.join(self.user_directory, 'alice')
        stats = BackupCreator(self.make_options(user_directory=self.user_directory, subreddit_directory=inner)).run()
        files = [name for name in self.archive_names(stats) if name.startswith('downloads/')]
        self.assertEqual(2, len(files))
        manifest = self.read_manifest(stats)
        self.assertEqual(SHARED_ARCROOT, manifest['user_directory']['archive_path'])
        self.assertEqual(f'{SHARED_ARCROOT}/alice', manifest['subreddit_directory']['archive_path'])

    def test_destination_inside_backed_up_directory(self) -> None:
        """A destination inside a backed up directory, and the archives already in it, are left out."""
        destination = os.path.join(self.user_directory, 'backups')
        write_file(os.path.join(destination, 'old_backup.tar.gz'))
        stats = BackupCreator(self.make_options(destination_directory=destination, user_directory=self.user_directory)).run()
        self.assertFalse(any('backups' in name for name in self.archive_names(stats)))

    def test_cancel_removes_partial_archive(self) -> None:
        """A cancelled backup keeps no archive."""
        stop_event = threading.Event()
        stop_event.set()
        stats = BackupCreator(self.make_options(user_directory=self.user_directory), stop_event).run()
        self.assertTrue(stats.cancelled)
        self.assertIsNone(stats.archive_path)
        self.assertEqual([], os.listdir(self.destination))

    def test_failure_removes_partial_archive(self) -> None:
        """An error while writing removes the partial archive and is raised."""
        with patch.object(BackupCreator, '_add_manifest', side_effect=tarfile.TarError('boom')):
            with self.assertRaises(tarfile.TarError):
                BackupCreator(self.make_options()).run()
        self.assertEqual([], os.listdir(self.destination))

    def test_unreadable_file_skipped(self) -> None:
        """A file that cannot be read is skipped and recorded, and the rest are archived."""
        unreadable = os.path.join(self.user_directory, 'alice', 'a.jpg')
        original_add = tarfile.TarFile.add

        def add(archive: tarfile.TarFile, name: str, *args: object, **kwargs: object) -> None:
            """
            Fails for the unreadable file and adds every other file.
            :param archive: The archive being written.
            :type archive: tarfile.TarFile
            :param name: The file to add.
            :type name: str
            :param args: Other positional arguments for TarFile.add.
            :type args: object
            :param kwargs: Other keyword arguments for TarFile.add.
            :type kwargs: object
            :return: None
            :rtype: None
            :raises PermissionError: For the unreadable file.
            """
            if name == unreadable:
                raise PermissionError('denied')
            original_add(archive, name, *args, **kwargs)

        with patch.object(tarfile.TarFile, 'add', add):
            stats = BackupCreator(self.make_options(user_directory=self.user_directory)).run()
        self.assertEqual([unreadable], stats.skipped_files)
        self.assertIn(f'{USERS_ARCROOT}/bob/b.mp4', self.archive_names(stats))
        self.assertNotIn(f'{USERS_ARCROOT}/alice/a.jpg', self.archive_names(stats))

    def test_missing_directory_recorded(self) -> None:
        """A download directory that does not exist is recorded, and the backup still succeeds."""
        missing = os.path.join(self.temp_dir.name, 'missing')
        stats = BackupCreator(self.make_options(user_directory=missing)).run()
        self.assertEqual([os.path.realpath(missing)], stats.missing_directories)
        self.assertEqual({DATABASE_ARCNAME, MANIFEST_ARCNAME}, self.archive_names(stats))
        self.assertIsNone(self.read_manifest(stats)['user_directory'])

    def test_progress_reported(self) -> None:
        """The progress callback is called as files are added."""
        progress = []
        with patch('DownloaderForReddit.utils.backup.backup_creator.PROGRESS_INTERVAL', 1):
            BackupCreator(self.make_options(user_directory=self.user_directory), progress_callback=progress.append).run()
        self.assertEqual([1, 2, 3], progress)
