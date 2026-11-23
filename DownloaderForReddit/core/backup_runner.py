"""
Runs a manual backup on a background thread.

The runner is moved onto a QThread by the main window.  It writes the backup archive, reports progress and the result
through the message queue, and emits the results when it is done.


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

import logging
import sqlite3
import tarfile
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from ..messaging.message import Message
from ..utils.backup.backup_creator import BackupCreator, BackupOptions, BackupStats


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')


class BackupRunner(QObject):
    """Writes one backup archive off the GUI thread."""

    finished = pyqtSignal(object)  # BackupStats

    def __init__(self, options: BackupOptions) -> None:
        """
        :param options: What to back up and where.
        :type options: BackupOptions
        """
        super().__init__()
        self.options = options
        self.stop_event = threading.Event()

    def stop(self, hard_stop: bool = False) -> None:
        """
        Asks the backup to stop.  Connected to the main window's stop signal; a soft and a hard stop are treated the
        same, and the partial archive is removed either way.
        :param hard_stop: Whether the user asked to terminate rather than stop.
        :type hard_stop: bool
        :return: None
        :rtype: None
        """
        logger.debug('Backup stop requested (hard stop: %s)', hard_stop)
        self.stop_event.set()

    def run(self) -> None:
        """
        Writes the backup and emits finished with the results, even when it fails.
        :return: None
        :rtype: None
        """
        stats = BackupStats()
        Message.send_info(f'Backing up to {self.options.destination_directory}')
        try:
            stats = BackupCreator(self.options, self.stop_event, self._progress).run()
            self._report(stats)
        except (OSError, sqlite3.Error, tarfile.TarError) as error:
            logger.exception('Backup failed')
            Message.send_error(f'Backup failed: {error}')
        finally:
            self.finished.emit(stats)

    @staticmethod
    def _progress(files_added: int) -> None:
        """
        Reports how far the backup has got.
        :param files_added: The number of files added so far.
        :type files_added: int
        :return: None
        :rtype: None
        """
        Message.send_info(f'Backed up {files_added:,} files so far')

    @staticmethod
    def _report(stats: BackupStats) -> None:
        """
        Reports the outcome of a backup that did not fail.
        :param stats: The backup results.
        :type stats: BackupStats
        :return: None
        :rtype: None
        """
        if stats.cancelled:
            Message.send_warning('Backup was stopped before it finished; no archive was kept')
            return
        size_mb = stats.bytes_added / (1024 * 1024)
        Message.send_info(f'Backup written to {stats.archive_path} ({stats.files_added:,} files, {size_mb:,.1f} MB before compression)')
        for directory in stats.missing_directories:
            Message.send_warning(f'Backup: directory not found and left out: {directory}')
        if stats.skipped_files:
            Message.send_warning(f'Backup: {len(stats.skipped_files):,} files could not be read and were left out; see the log for details')
