"""
Dialog that sets up the import of a Reddit data export archive.

The user picks the zip file, checks the detected account name and the record counts, chooses what to import and
whether to fill in missing data from a download source, then accepts the dialog.  The import itself is run by the main
window on a background thread.


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
import os
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QWidget

from ..database.export_models import ExportImport
from ..database.model_enums import PostDownloadSource
from ..guiresources.import_reddit_export_dialog_auto import Ui_ImportRedditExportDialog
from ..utils import injector
from ..utils.importers.reddit_export import InvalidExportError
from ..utils.importers.reddit_export.export_importer import ExportImportOptions
from ..utils.importers.reddit_export.export_reader import RedditExportReader
from ..utils.importers.reddit_export.export_records import (ExportManifest, POSTS_FILE, COMMENTS_FILE, CHAT_HISTORY_FILE,
                                                            MESSAGES_FILE, MESSAGES_ARCHIVE_FILE)


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')


class ImportRedditExportDialog(QDialog, Ui_ImportRedditExportDialog):
    """Collects the file and options for a Reddit data export import."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Builds the dialog and restores the options used last time.
        :param parent: The parent widget.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        self.setupUi(self)
        self.settings_manager = injector.get_settings_manager()
        self.manifest: Optional[ExportManifest] = None
        self.zip_path: Optional[str] = None

        self.hydration_combo.addItem("Don't look anything up", None)
        for source in PostDownloadSource:
            self.hydration_combo.addItem(source.display_name, source)
        saved_source = self.settings_manager.export_import_hydration_source
        for index in range(self.hydration_combo.count()):
            source = self.hydration_combo.itemData(index)
            if source is not None and source.name == saved_source:
                self.hydration_combo.setCurrentIndex(index)
        self.download_media_check_box.setChecked(bool(self.settings_manager.export_import_queue_downloads))

        self.browse_button.clicked.connect(self.select_file)
        self.account_line_edit.textChanged.connect(self.update_ok_button)
        self.posts_check_box.toggled.connect(self.update_ok_button)
        self.button_box.accepted.connect(self.accept)
        self.update_ok_button()

    def select_file(self) -> None:
        """
        Asks the user for the export zip file and loads it.
        :return: None
        :rtype: None
        """
        path = QFileDialog.getOpenFileName(self, 'Select Reddit Data Export', self.settings_manager.last_export_import_directory,
                                           'Zip Files (*.zip)')[0]
        if path:
            self.settings_manager.last_export_import_directory = os.path.dirname(path)
            self.load_file(path)

    def load_file(self, path: str) -> None:
        """
        Reads the archive's manifest and shows what it holds.  An invalid file is reported in the dialog.
        :param path: The archive path.
        :type path: str
        :return: None
        :rtype: None
        """
        self.file_path_line_edit.setText(path)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with RedditExportReader(path) as reader:
                self.manifest = reader.read_manifest()
            self.zip_path = path
        except (InvalidExportError, OSError) as error:
            logger.warning('Could not read export %s: %s', path, error)
            self.manifest = None
            self.zip_path = None
            self.status_label.setText(f'This is not a Reddit data export: {error}')
            self.update_ok_button()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.show_manifest(self.manifest)

    def show_manifest(self, manifest: ExportManifest) -> None:
        """
        Fills the dialog in from an archive's manifest.
        :param manifest: The manifest.
        :type manifest: ExportManifest
        :return: None
        :rtype: None
        """
        if manifest.account_name and not self.account_line_edit.text():
            self.account_line_edit.setText(manifest.account_name)
        message_count = manifest.count(MESSAGES_FILE) + manifest.count(MESSAGES_ARCHIVE_FILE)
        self._set_count(self.posts_check_box, 'Posts', manifest.count(POSTS_FILE))
        self._set_count(self.comments_check_box, 'Comments', manifest.count(COMMENTS_FILE))
        self._set_count(self.chats_check_box, 'Chat messages', manifest.count(CHAT_HISTORY_FILE))
        self._set_count(self.private_messages_check_box, 'Private messages', message_count)
        self.status_label.setText(self._previous_import_text(manifest))
        self.update_ok_button()

    @staticmethod
    def _set_count(check_box: QCheckBox, label: str, count: int) -> None:
        """
        Shows a record count on a checkbox, and disables it when there is nothing to import.
        :param check_box: The checkbox.
        :type check_box: QCheckBox
        :param label: The record type's name.
        :type label: str
        :param count: The number of records.
        :type count: int
        :return: None
        :rtype: None
        """
        check_box.setText(f'{label} ({count:,})')
        check_box.setEnabled(count > 0)
        check_box.setChecked(count > 0)

    @staticmethod
    def _previous_import_text(manifest: ExportManifest) -> str:
        """
        Describes an earlier import of the same file, if there was one.
        :param manifest: The manifest of the chosen file.
        :type manifest: ExportManifest
        :return: The description, or an empty string when the file has not been imported before.
        :rtype: str
        """
        with injector.get_database_handler().get_scoped_session() as session:
            previous = session.query(ExportImport).filter(ExportImport.file_sha256 == manifest.file_sha256) \
                .order_by(ExportImport.import_date.desc()).first()
            if previous is None:
                return ''
            return (f'This file was already imported on {previous.import_date_display}. Importing it again only adds '
                    'records that are not stored yet.')

    def update_ok_button(self) -> None:
        """
        Enables the OK button once a valid archive is loaded, an account is named and something is selected.
        :return: None
        :rtype: None
        """
        anything_selected = any(box.isChecked() for box in (self.posts_check_box, self.comments_check_box,
                                                            self.chats_check_box, self.private_messages_check_box))
        ready = self.zip_path is not None and bool(self.account_line_edit.text().strip()) and anything_selected
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ready)
        self.download_media_check_box.setEnabled(self.posts_check_box.isChecked())

    @property
    def options(self) -> ExportImportOptions:
        """
        The import options chosen in the dialog.
        :return: The options.
        :rtype: ExportImportOptions
        """
        return ExportImportOptions(
            account_name=self.account_line_edit.text().strip(),
            import_posts=self.posts_check_box.isChecked(),
            import_comments=self.comments_check_box.isChecked(),
            import_chats=self.chats_check_box.isChecked(),
            import_private_messages=self.private_messages_check_box.isChecked(),
            chunk_size=int(self.settings_manager.export_import_chunk_size),
        )

    @property
    def hydration_source(self) -> Optional[PostDownloadSource]:
        """
        The download source chosen to fill in missing data.
        :return: The source, or None when nothing is to be looked up.
        :rtype: Optional[PostDownloadSource]
        """
        return self.hydration_combo.currentData()

    @property
    def download_media(self) -> bool:
        """
        Whether the imported posts' media is to be downloaded after the import.
        :return: True to download the media.
        :rtype: bool
        """
        return self.download_media_check_box.isEnabled() and self.download_media_check_box.isChecked()

    def accept(self) -> None:
        """
        Saves the chosen options for next time and closes the dialog.
        :return: None
        :rtype: None
        """
        source = self.hydration_source
        self.settings_manager.export_import_hydration_source = source.name if source is not None else ''
        self.settings_manager.export_import_queue_downloads = self.download_media_check_box.isChecked()
        super().accept()
