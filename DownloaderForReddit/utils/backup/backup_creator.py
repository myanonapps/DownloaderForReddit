"""
Writes a backup of the application's data to a single gzip-compressed tar archive.

The archive always holds a consistent snapshot of the database, taken with SQLite's online backup API so that it is
safe even while the application is writing to it.  The settings file and the base user and subreddit download
directories can be added.  A manifest describing the contents is written last.  The archive is written under a
temporary ``.part`` name and only renamed once it is complete, so a cancelled or failed backup never leaves a file
that looks finished.

Archive layout::

    database/dfr.db
    config/config.toml
    downloads/users/...
    downloads/subreddits/...
    downloads/shared/...        (when the user and subreddit directories are the same, or one holds the other)
    manifest.json


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

import io
import json
import logging
import os
import pathlib
import sqlite3
import tarfile
import tempfile
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from ...version import __version__


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

ARCHIVE_PREFIX = 'dfr_backup_'
ARCHIVE_SUFFIX = '.tar.gz'
PART_SUFFIX = '.part'
DATABASE_ARCNAME = 'database/dfr.db'
CONFIG_ARCNAME = 'config/config.toml'
MANIFEST_ARCNAME = 'manifest.json'
USERS_ARCROOT = 'downloads/users'
SUBREDDITS_ARCROOT = 'downloads/subreddits'
SHARED_ARCROOT = 'downloads/shared'
PROGRESS_INTERVAL = 250


@dataclass
class BackupOptions:
    """
    What to back up and where to put the archive.  A source set to None is left out of the backup.
    """

    destination_directory: str
    database_path: str
    config_path: Optional[str] = None
    user_directory: Optional[str] = None
    subreddit_directory: Optional[str] = None
    compression_level: int = 6


@dataclass
class BackupStats:
    """The results of a backup."""

    archive_path: Optional[str] = None
    files_added: int = 0
    bytes_added: int = 0
    skipped_files: list[str] = field(default_factory=list)
    missing_directories: list[str] = field(default_factory=list)
    cancelled: bool = False


class BackupCancelled(Exception):
    """Raised inside the creator when the stop event is set, to unwind out of the archive being written."""


class BackupCreator:
    """Writes one backup archive from a set of options."""

    def __init__(self, options: BackupOptions, stop_event: Optional[threading.Event] = None,
                 progress_callback: Optional[Callable[[int], None]] = None) -> None:
        """
        :param options: What to back up and where.
        :type options: BackupOptions
        :param stop_event: Set to cancel the backup; the partial archive is then removed.
        :type stop_event: Optional[threading.Event]
        :param progress_callback: Called with the number of files added so far, every few hundred files.
        :type progress_callback: Optional[Callable[[int], None]]
        """
        self.options = options
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.progress_callback = progress_callback
        self.stats = BackupStats()
        self._part_path = ''
        self._excluded_directory = ''

    def run(self) -> BackupStats:
        """
        Writes the archive.  When cancelled, the partial archive is deleted and the returned stats are marked cancelled.
        :return: The results, with ``archive_path`` set to the finished archive, or None when cancelled.
        :rtype: BackupStats
        :raises FileNotFoundError: When the database file does not exist.
        :raises OSError: When the archive cannot be written.
        :raises sqlite3.Error: When the database snapshot fails.
        :raises tarfile.TarError: When the archive cannot be written.
        """
        if not os.path.isfile(self.options.database_path):
            raise FileNotFoundError(f'Database not found: {self.options.database_path}')
        os.makedirs(self.options.destination_directory, exist_ok=True)
        self._excluded_directory = os.path.realpath(self.options.destination_directory)
        final_path = self._new_archive_path()
        self._part_path = final_path + PART_SUFFIX
        try:
            with tempfile.TemporaryDirectory(prefix='dfr_backup_') as temp_dir:
                snapshot_path = os.path.join(temp_dir, 'dfr.db')
                self.snapshot_database(self.options.database_path, snapshot_path)
                with tarfile.open(self._part_path, 'w:gz', compresslevel=self.options.compression_level) as archive:
                    self._add_file(archive, snapshot_path, DATABASE_ARCNAME)
                    if self.options.config_path is not None:
                        self._add_config(archive)
                    directories = self.plan_directories(self.options.user_directory, self.options.subreddit_directory)
                    for arc_root, directory in directories.items():
                        self._add_directory(archive, directory, arc_root)
                    self._add_manifest(archive, directories)
        except BackupCancelled:
            logger.info('Backup cancelled; removing %s', self._part_path)
            self.stats.cancelled = True
            self._remove_part()
            return self.stats
        except BaseException:
            self._remove_part()
            raise
        os.replace(self._part_path, final_path)
        self.stats.archive_path = final_path
        logger.info('Backup written to %s (%d files)', final_path, self.stats.files_added)
        return self.stats

    @staticmethod
    def snapshot_database(source_path: str, destination_path: str) -> None:
        """
        Copies a SQLite database with the online backup API, which gives a consistent copy even while other
        connections are writing.  The source is opened read only.
        :param source_path: The database to copy.
        :type source_path: str
        :param destination_path: Where to write the copy.
        :type destination_path: str
        :return: None
        :rtype: None
        :raises sqlite3.Error: When the copy fails.
        """
        source_uri = pathlib.Path(source_path).resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(source_uri, uri=True)) as source, closing(sqlite3.connect(destination_path)) as destination:
            source.backup(destination)

    @staticmethod
    def plan_directories(user_directory: Optional[str], subreddit_directory: Optional[str]) -> dict[str, str]:
        """
        Decides which download directories go into the archive and under which archive root.  When both are chosen
        and they are the same directory, or one is inside the other, only the outer one is archived, once, so that no
        file is stored twice.
        :param user_directory: The base user download directory, or None to leave it out.
        :type user_directory: Optional[str]
        :param subreddit_directory: The base subreddit download directory, or None to leave it out.
        :type subreddit_directory: Optional[str]
        :return: The directories to archive, keyed by archive root.
        :rtype: dict[str, str]
        """
        user = os.path.realpath(user_directory) if user_directory else None
        subreddit = os.path.realpath(subreddit_directory) if subreddit_directory else None
        if user is not None and subreddit is not None:
            if BackupCreator.is_within(subreddit, user):
                return {SHARED_ARCROOT: user}
            if BackupCreator.is_within(user, subreddit):
                return {SHARED_ARCROOT: subreddit}
        directories = {}
        if user is not None:
            directories[USERS_ARCROOT] = user
        if subreddit is not None:
            directories[SUBREDDITS_ARCROOT] = subreddit
        return directories

    @staticmethod
    def is_within(path: str, directory: str) -> bool:
        """
        Tells whether a path is a directory or inside it.  Both paths are expected to be absolute and normalised.
        :param path: The path to test.
        :type path: str
        :param directory: The directory.
        :type directory: str
        :return: True when ``path`` is ``directory`` or below it.
        :rtype: bool
        """
        try:
            return os.path.commonpath([os.path.normcase(path), os.path.normcase(directory)]) == os.path.normcase(directory)
        except ValueError:  # different drives on Windows
            return False

    def _new_archive_path(self) -> str:
        """
        Picks a timestamped archive name in the destination directory that is not already taken.
        :return: The archive path.
        :rtype: str
        """
        stamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        base = os.path.join(self.options.destination_directory, f'{ARCHIVE_PREFIX}{stamp}')
        path = base + ARCHIVE_SUFFIX
        counter = 1
        while os.path.exists(path) or os.path.exists(path + PART_SUFFIX):
            path = f'{base}_{counter}{ARCHIVE_SUFFIX}'
            counter += 1
        return path

    def _check_stop(self) -> None:
        """
        Unwinds the backup if it has been asked to stop.
        :return: None
        :rtype: None
        :raises BackupCancelled: When the stop event is set.
        """
        if self.stop_event.is_set():
            raise BackupCancelled()

    def _add_file(self, archive: tarfile.TarFile, path: str, arcname: str) -> None:
        """
        Adds one file to the archive and counts it.
        :param archive: The archive being written.
        :type archive: tarfile.TarFile
        :param path: The file to add.
        :type path: str
        :param arcname: Its name inside the archive.
        :type arcname: str
        :return: None
        :rtype: None
        :raises OSError: When the file cannot be read.
        """
        archive.add(path, arcname=arcname, recursive=False)
        self.stats.files_added += 1
        if os.path.isfile(path) and not os.path.islink(path):
            self.stats.bytes_added += os.path.getsize(path)
        if self.progress_callback is not None and self.stats.files_added % PROGRESS_INTERVAL == 0:
            self.progress_callback(self.stats.files_added)

    def _add_config(self, archive: tarfile.TarFile) -> None:
        """
        Adds the settings file, or notes that it is missing.
        :param archive: The archive being written.
        :type archive: tarfile.TarFile
        :return: None
        :rtype: None
        """
        config_path = self.options.config_path
        if config_path is not None and os.path.isfile(config_path):
            self._add_file(archive, config_path, CONFIG_ARCNAME)
        else:
            logger.warning('Settings file %s not found; it is left out of the backup', config_path)
            self.stats.skipped_files.append(str(config_path))

    def _add_directory(self, archive: tarfile.TarFile, directory: str, arc_root: str) -> None:
        """
        Adds every file below a directory, checking for a stop request between files.  Unreadable files are skipped
        and recorded, and the backup destination is never archived into itself.
        :param archive: The archive being written.
        :type archive: tarfile.TarFile
        :param directory: The directory to archive.
        :type directory: str
        :param arc_root: The directory's name inside the archive.
        :type arc_root: str
        :return: None
        :rtype: None
        :raises BackupCancelled: When the stop event is set.
        """
        if not os.path.isdir(directory):
            logger.warning('Download directory %s not found; it is left out of the backup', directory)
            self.stats.missing_directories.append(directory)
            return
        for dir_path, dir_names, file_names in os.walk(directory):
            dir_names[:] = sorted(name for name in dir_names
                                  if not self.is_within(os.path.realpath(os.path.join(dir_path, name)), self._excluded_directory))
            relative_dir = os.path.relpath(dir_path, directory)
            for name in sorted(file_names):
                self._check_stop()
                path = os.path.join(dir_path, name)
                if self.is_within(os.path.realpath(path), self._excluded_directory):
                    continue
                arcname = '/'.join(part for part in (arc_root, relative_dir.replace(os.sep, '/'), name) if part and part != '.')
                try:
                    self._add_file(archive, path, arcname)
                except OSError as error:
                    logger.warning('Could not back up %s: %s', path, error)
                    self.stats.skipped_files.append(path)

    def _add_manifest(self, archive: tarfile.TarFile, directories: dict[str, str]) -> None:
        """
        Writes the manifest that describes the archive, for a person reading it or a later restore.
        :param archive: The archive being written.
        :type archive: tarfile.TarFile
        :param directories: The download directories that were archived, keyed by archive root.
        :type directories: dict[str, str]
        :return: None
        :rtype: None
        """
        manifest = {
            'application': 'Downloader for Reddit',
            'version': __version__,
            'created': datetime.now().astimezone().isoformat(timespec='seconds'),
            'database': {'archive_path': DATABASE_ARCNAME, 'source_path': self.options.database_path},
            'config': ({'archive_path': CONFIG_ARCNAME, 'source_path': self.options.config_path}
                       if self.options.config_path is not None and self.options.config_path not in self.stats.skipped_files else None),
            'user_directory': self._directory_entry(self.options.user_directory, directories),
            'subreddit_directory': self._directory_entry(self.options.subreddit_directory, directories),
            'files': self.stats.files_added,
            'bytes': self.stats.bytes_added,
            'skipped_files': self.stats.skipped_files,
            'missing_directories': self.stats.missing_directories,
        }
        data = json.dumps(manifest, indent=2).encode('utf-8')
        info = tarfile.TarInfo(MANIFEST_ARCNAME)
        info.size = len(data)
        info.mtime = int(time.time())
        archive.addfile(info, io.BytesIO(data))

    def _directory_entry(self, source: Optional[str], directories: dict[str, str]) -> Optional[dict[str, str]]:
        """
        Describes where a chosen download directory went in the archive.
        :param source: The directory as chosen, or None when it was not chosen.
        :type source: Optional[str]
        :param directories: The download directories that were archived, keyed by archive root.
        :type directories: dict[str, str]
        :return: The source path and the archive root it is under, or None when it was not chosen or not found.
        :rtype: Optional[dict[str, str]]
        """
        if not source:
            return None
        real = os.path.realpath(source)
        for arc_root, directory in directories.items():
            if directory not in self.stats.missing_directories and self.is_within(real, directory):
                relative = os.path.relpath(real, directory)
                archive_path = arc_root if relative == '.' else f'{arc_root}/{relative.replace(os.sep, "/")}'
                return {'archive_path': archive_path, 'source_path': source}
        return None

    def _remove_part(self) -> None:
        """
        Deletes the partial archive, if it was created.
        :return: None
        :rtype: None
        """
        try:
            if self._part_path and os.path.exists(self._part_path):
                os.remove(self._part_path)
        except OSError:
            logger.warning('Could not remove the partial backup %s', self._part_path, exc_info=True)
