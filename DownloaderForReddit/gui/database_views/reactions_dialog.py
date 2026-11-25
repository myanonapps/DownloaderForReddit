"""
A dialog for managing the chat reactions shared by every imported chat.

Each reaction is listed with its image, a name the user can change, whether it is treated as a reaction, how many
times and in how many chats it was used, when it was last used, and its url.  Clearing "Reaction" makes its messages
show as ordinary messages in every chat.  Missing images can be fetched, and the folder they are stored in opened.


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

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtWidgets import QDialog, QHeaderView, QTableWidgetItem, QWidget

from ...core.const import RESOURCES
from ...core.reaction_fetcher import ReactionFetcher, start_fetch_thread
from ...database.export_models import reactions_folder
from ...guiresources.database_views.reactions_dialog_auto import Ui_ReactionsDialog
from ...utils import injector, system_util
from ...utils.chat_reactions import ReactionUsage, rename_reaction, reaction_usage, set_reaction_enabled


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

_PLACEHOLDER_PATH = os.path.join(RESOURCES, 'images', 'image_placeholder.png')
_DATE_FORMAT = '%Y-%m-%d %H:%M'
IMAGE_COLUMN, NAME_COLUMN, ENABLED_COLUMN, USES_COLUMN, CHATS_COLUMN, LAST_USED_COLUMN, URL_COLUMN = range(7)


def _read_only(text: str) -> QTableWidgetItem:
    """
    Creates a table cell that cannot be edited.
    :param text: The cell's text.
    :type text: str
    :return: The cell.
    :rtype: QTableWidgetItem
    """
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class ReactionsDialog(QDialog, Ui_ReactionsDialog):
    """Lists the chat reactions and lets the user rename them, switch them off, and fetch their images."""

    # Emitted after reactions were renamed, marked or had images fetched, so open chats can show the change.
    reactions_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Builds the dialog and lists the reactions.
        :param parent: The parent widget.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        self.setupUi(self)
        self.db = injector.get_database_handler()
        self.reaction_thread: Optional[QThread] = None
        self.reaction_fetcher: Optional[ReactionFetcher] = None
        self.usage: list[ReactionUsage] = []
        header = self.reactions_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(URL_COLUMN, QHeaderView.ResizeMode.Stretch)
        self.reactions_table.itemChanged.connect(self.item_changed)
        self.download_button.clicked.connect(self.download_missing)
        self.open_folder_button.clicked.connect(self.open_folder)
        self.button_box.rejected.connect(self.close)
        self.load()

    def load(self) -> None:
        """
        Lists every reaction, the most used first.
        :return: None
        :rtype: None
        """
        with self.db.get_scoped_session() as session:
            self.usage = reaction_usage(session)
        self.reactions_table.blockSignals(True)
        self.reactions_table.setRowCount(len(self.usage))
        for row, record in enumerate(self.usage):
            self._fill_row(row, record)
        self.reactions_table.blockSignals(False)
        self.reactions_table.resizeRowsToContents()
        missing = sum(1 for record in self.usage if record.enabled and record.image_path is None)
        self.download_button.setEnabled(missing > 0 and self.reaction_thread is None)
        self.status_label.setText(f'{len(self.usage):,} reactions' + (f', {missing:,} without an image' if missing else ''))

    def _fill_row(self, row: int, record: ReactionUsage) -> None:
        """
        Fills one row of the table.
        :param row: The row number.
        :type row: int
        :param record: The reaction and how it was used.
        :type record: ReactionUsage
        :return: None
        :rtype: None
        """
        image = _read_only('')
        image.setIcon(QIcon(record.image_path or _PLACEHOLDER_PATH))
        image.setToolTip(record.image_path or 'The image has not been fetched')
        name = QTableWidgetItem(record.display_name)
        name.setData(Qt.ItemDataRole.UserRole, record.reaction_id)
        name.setToolTip('Double click to rename')
        enabled = _read_only('')
        enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        enabled.setCheckState(Qt.CheckState.Checked if record.enabled else Qt.CheckState.Unchecked)
        enabled.setToolTip('Whether messages holding only this image are shown as reactions')
        last_used = record.last_used.strftime(_DATE_FORMAT) if record.last_used is not None else ''
        cells = {IMAGE_COLUMN: image, NAME_COLUMN: name, ENABLED_COLUMN: enabled, USES_COLUMN: _read_only(f'{record.uses:,}'),
                 CHATS_COLUMN: _read_only(f'{record.chats:,}'), LAST_USED_COLUMN: _read_only(last_used),
                 URL_COLUMN: _read_only(record.url)}
        for column, item in cells.items():
            self.reactions_table.setItem(row, column, item)

    def item_changed(self, item: QTableWidgetItem) -> None:
        """
        Stores a reaction's new name, or whether it is treated as a reaction, after the user changed it in the table.
        :param item: The changed cell.
        :type item: QTableWidgetItem
        :return: None
        :rtype: None
        """
        row = item.row()
        if not 0 <= row < len(self.usage):
            return
        record = self.usage[row]
        with self.db.get_scoped_session() as session:
            if item.column() == NAME_COLUMN:
                rename_reaction(session, record.reaction_id, item.text())
            elif item.column() == ENABLED_COLUMN:
                set_reaction_enabled(session, record.url, item.checkState() == Qt.CheckState.Checked)
            else:
                return
        self.load()
        self.reactions_changed.emit()

    def download_missing(self) -> None:
        """
        Fetches the images of the reactions that have none, in the background.
        :return: None
        :rtype: None
        """
        if self.reaction_thread is not None:
            return
        self.download_button.setEnabled(False)
        self.status_label.setText('Fetching reaction images...')
        self.reaction_thread, self.reaction_fetcher = start_fetch_thread(self.images_fetched, self.fetch_done)

    def images_fetched(self, fetched: int, failed: int) -> None:
        """
        Lists the reactions again with the images just fetched.
        :param fetched: The number of images stored.
        :type fetched: int
        :param failed: The number of images that could not be fetched.
        :type failed: int
        :return: None
        :rtype: None
        """
        self.load()
        self.status_label.setText(f'Fetched {fetched:,} images' + (f'; {failed:,} could not be fetched' if failed else ''))
        if fetched:
            self.reactions_changed.emit()

    def fetch_done(self) -> None:
        """
        Releases the fetch thread once it has finished.
        :return: None
        :rtype: None
        """
        if self.reaction_thread is not None:
            self.reaction_thread.wait()
        self.reaction_thread = None
        self.reaction_fetcher = None
        missing = any(record.enabled and record.image_path is None for record in self.usage)
        self.download_button.setEnabled(missing)

    def open_folder(self) -> None:
        """
        Opens the folder the reaction images are stored in.
        :return: None
        :rtype: None
        """
        folder = reactions_folder()
        try:
            os.makedirs(folder, exist_ok=True)
            system_util.open_in_system(folder)
        except OSError:
            logger.warning('Could not open %s', folder, exc_info=True)
            self.status_label.setText(f'Could not open {folder}')

    def closeEvent(self, event: QCloseEvent) -> None:  # pylint: disable=invalid-name  # Qt override
        """
        Stops fetching images when the dialog is closed.
        :param event: The close event.
        :type event: QCloseEvent
        :return: None
        :rtype: None
        """
        if self.reaction_fetcher is not None:
            self.reaction_fetcher.stop()
        super().closeEvent(event)
