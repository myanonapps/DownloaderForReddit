"""
Dialog that sets up a manual backup.

The user picks the directory the archive is written to and what to include besides the database, then accepts the
dialog.  The backup itself is run by the main window on a background thread.


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

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QWidget

from ..guiresources.backup_dialog_auto import Ui_BackupDialog
from ..utils import injector
from ..utils.backup.backup_creator import BackupCreator, BackupOptions, SHARED_ARCROOT


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')


class BackupDialog(QDialog, Ui_BackupDialog):
    """Collects the destination and contents of a backup."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Builds the dialog and restores the choices made last time.
        :param parent: The parent widget.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        self.setupUi(self)
        self.settings_manager = injector.get_settings_manager()
        self.user_directory = str(self.settings_manager.user_save_directory)
        self.subreddit_directory = str(self.settings_manager.subreddit_save_directory)

        self.destination_line_edit.setText(str(self.settings_manager.last_backup_directory))
        self.config_check_box.setChecked(bool(self.settings_manager.backup_include_config))
        self.user_directory_check_box.setText(f'User download directory ({self.user_directory})')
        self.user_directory_check_box.setToolTip(self.user_directory)
        self.user_directory_check_box.setChecked(bool(self.settings_manager.backup_include_user_directory))
        self.subreddit_directory_check_box.setText(f'Subreddit download directory ({self.subreddit_directory})')
        self.subreddit_directory_check_box.setToolTip(self.subreddit_directory)
        self.subreddit_directory_check_box.setChecked(bool(self.settings_manager.backup_include_subreddit_directory))

        self.browse_button.clicked.connect(self.select_destination)
        self.destination_line_edit.textChanged.connect(self.update_state)
        self.user_directory_check_box.toggled.connect(self.update_state)
        self.subreddit_directory_check_box.toggled.connect(self.update_state)
        self.button_box.accepted.connect(self.accept)
        self.update_state()

    def select_destination(self) -> None:
        """
        Asks the user for the directory to write the archive to.
        :return: None
        :rtype: None
        """
        start = self.destination_line_edit.text().strip()
        path = QFileDialog.getExistingDirectory(self, 'Select Backup Directory', start if os.path.isdir(start) else os.path.expanduser('~'))
        if path:
            self.destination_line_edit.setText(path)

    @property
    def destination_directory(self) -> str:
        """
        The directory the archive is to be written to, as typed.
        :return: The directory.
        :rtype: str
        """
        return self.destination_line_edit.text().strip()

    def update_state(self) -> None:
        """
        Enables OK only for a usable destination, and explains how overlapping directories are handled.
        :return: None
        :rtype: None
        """
        notes = []
        destination = self.destination_directory
        valid = bool(destination) and (os.path.isdir(destination) or not os.path.exists(destination))
        if destination and not valid:
            notes.append('The destination exists and is not a directory.')
        directories = BackupCreator.plan_directories(
            self.user_directory if self.user_directory_check_box.isChecked() else None,
            self.subreddit_directory if self.subreddit_directory_check_box.isChecked() else None)
        if SHARED_ARCROOT in directories:
            notes.append('The user and subreddit directories overlap, so they are backed up once.')
        if valid and any(BackupCreator.is_within(os.path.realpath(destination), directory) for directory in directories.values()):
            notes.append('The destination is inside a directory being backed up; the destination itself is left out.')
        self.status_label.setText(' '.join(notes))
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    @property
    def options(self) -> BackupOptions:
        """
        The backup options chosen in the dialog.
        :return: The options.
        :rtype: BackupOptions
        """
        return BackupOptions(
            destination_directory=self.destination_directory,
            database_path=injector.get_database_handler().database_path,
            config_path=self.settings_manager.config_file_path if self.config_check_box.isChecked() else None,
            user_directory=self.user_directory if self.user_directory_check_box.isChecked() else None,
            subreddit_directory=self.subreddit_directory if self.subreddit_directory_check_box.isChecked() else None,
            compression_level=self._compression_level(),
        )

    def _compression_level(self) -> int:
        """
        The gzip compression level from the settings, kept within gzip's range of 1 to 9.
        :return: The compression level.
        :rtype: int
        """
        try:
            level = int(self.settings_manager.backup_compression_level)
        except (TypeError, ValueError):
            logger.warning('Invalid backup_compression_level %r; using 6', self.settings_manager.backup_compression_level)
            return 6
        return min(max(level, 1), 9)

    def accept(self) -> None:
        """
        Saves the chosen options for next time and closes the dialog.
        :return: None
        :rtype: None
        """
        self.settings_manager.last_backup_directory = self.destination_directory
        self.settings_manager.backup_include_config = self.config_check_box.isChecked()
        self.settings_manager.backup_include_user_directory = self.user_directory_check_box.isChecked()
        self.settings_manager.backup_include_subreddit_directory = self.subreddit_directory_check_box.isChecked()
        super().accept()
