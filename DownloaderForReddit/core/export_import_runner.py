"""
Runs the import of a Reddit data export archive on a background thread.

The runner is moved onto a QThread by the main window.  It imports the archive, optionally fills in the missing data
from a download source, reports progress through the message queue, and emits the results when it is done.


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
import threading
import zipfile
from typing import Optional

import requests
from PyQt6.QtCore import QObject, pyqtSignal
from sqlalchemy.exc import SQLAlchemyError

from ..data_interface.adapter_manager import RedditAdapterManager
from ..database.model_enums import PostDownloadSource
from ..messaging.message import Message, MessageType
from ..utils.importers.reddit_export import InvalidExportError
from ..utils.importers.reddit_export.export_hydrator import ExportHydrator
from ..utils.importers.reddit_export.export_importer import ExportImportOptions, ExportImportStats, RedditExportImporter
from ..utils.importers.reddit_export.export_reader import RedditExportReader


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')


class ExportImportRunner(QObject):
    """Imports one export archive, then optionally hydrates it, off the GUI thread."""

    finished = pyqtSignal(object)  # ExportImportStats

    def __init__(self, zip_path: str, options: ExportImportOptions, hydration_source: Optional[PostDownloadSource] = None) -> None:
        """
        :param zip_path: The export archive to import.
        :type zip_path: str
        :param options: What to import.
        :type options: ExportImportOptions
        :param hydration_source: The download source to fill in missing data from, or None to skip that step.
        :type hydration_source: Optional[PostDownloadSource]
        """
        super().__init__()
        self.zip_path = zip_path
        self.options = options
        self.hydration_source = hydration_source
        self.stop_event = threading.Event()
        self._importer: Optional[RedditExportImporter] = None
        self._progressed = 0

    def stop(self, hard_stop: bool = False) -> None:
        """
        Asks the import to stop after its current chunk.  Connected to the main window's stop signal; a soft and a hard
        stop are treated the same, since the current chunk is always finished so that nothing is half written.
        :param hard_stop: Whether the user asked to terminate rather than stop.
        :type hard_stop: bool
        :return: None
        :rtype: None
        """
        logger.debug('Export import stop requested (hard stop: %s)', hard_stop)
        self.stop_event.set()

    def run(self) -> None:
        """
        Runs the import and emits finished with the results, even when it fails.
        :return: None
        :rtype: None
        """
        stats = ExportImportStats()
        try:
            stats = self._import()
            if self.hydration_source is not None and not self.stop_event.is_set() and stats.download_session_id is not None:
                stats = self._hydrate(stats)
        except InvalidExportError as error:
            Message.send_error(f'Reddit export import failed: {error}')
        except (OSError, ValueError, zipfile.BadZipFile, SQLAlchemyError, requests.exceptions.RequestException):
            logger.exception('Reddit export import failed')
            Message.send_error('Reddit export import failed; see the log for details')
        finally:
            self.finished.emit(stats)

    def _import(self) -> ExportImportStats:
        """
        Imports the archive.
        :return: The import results.
        :rtype: ExportImportStats
        """
        Message.send_info(f'Importing Reddit data export {self.zip_path} for {self.options.account_name}')
        with RedditExportReader(self.zip_path) as reader:
            self._importer = RedditExportImporter(reader, self.options, self.stop_event, self._import_progress)
            stats = self._importer.run()
        Message.send_info(f'Imported {stats.posts_added:,} posts, {stats.comments_added:,} comments, '
                          f'{stats.chat_messages_added:,} chat messages in {stats.chat_channels_added:,} new channels and '
                          f'{stats.private_messages_added:,} private messages '
                          f'({stats.posts_skipped + stats.comments_skipped + stats.chat_messages_skipped + stats.private_messages_skipped:,} '
                          f'already stored)')
        if stats.cancelled:
            Message.send_warning('Reddit export import was stopped before it finished')
        return stats

    def _import_progress(self, record_type: str, count: int) -> None:
        """
        Advances the main window's progress bar.  Each stored post and comment extends the bar through the database
        listeners, but imported rows are never marked extracted, so the matching steps are sent here.
        :param record_type: The kind of record in the chunk.
        :type record_type: str
        :param count: The number of records in the chunk.
        :type count: int
        :return: None
        :rtype: None
        """
        logger.debug('Imported a chunk of %d %s', count, record_type)
        if self._importer is None:
            return
        stored = self._importer.stats.posts_added + self._importer.stats.comments_added
        for _ in range(stored - self._progressed):
            Message.send(MessageType.ACTUAL_PROGRESS)
        self._progressed = stored

    def _hydrate(self, stats: ExportImportStats) -> ExportImportStats:
        """
        Fills in the imported posts and comments from the chosen download source.  Network failures are reported, and
        the import is kept as it is.
        :param stats: The import results.
        :type stats: ExportImportStats
        :return: The results with the hydration counts added.
        :rtype: ExportImportStats
        """
        Message.send_info(f'Looking up imported posts and comments through {self.hydration_source.display_name}')
        adapter = RedditAdapterManager().get_adapter(self.hydration_source)
        hydrator = ExportHydrator(adapter, self.stop_event,
                                  progress_callback=lambda record_type, count: logger.debug('Hydrated %d %s', count, record_type))
        try:
            stats = hydrator.hydrate(stats)
        except requests.exceptions.RequestException as error:
            logger.warning('Hydration failed', exc_info=True)
            Message.send_warning(f'Could not look up the imported data through {self.hydration_source.display_name}: {error}')
            return stats
        Message.send_info(f'Updated {stats.posts_hydrated:,} posts and {stats.comments_hydrated:,} comments; '
                          f'{stats.not_found:,} were not found')
        return stats
