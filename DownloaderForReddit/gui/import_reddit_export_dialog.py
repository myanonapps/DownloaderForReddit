"""
Dialog that sets up the import of a Reddit data export archive.

The user picks the zip file, checks the detected account name and the record counts, and chooses the user list that
the account, and every user found in its chats and private messages, is added to, as when adding users anywhere else
in the application.  The list decides the download source that missing data is filled in from, and users not on a list
yet take the list's download settings, which then decide whether and where each author's media is downloaded.  Whether missing data is
filled in, and whether the media in the imported posts and messages is downloaded afterwards, are chosen with two
checkboxes, and a summary describes what the import will do.  The import itself is run by the main window on a
background thread.


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

import html
import logging
import os
from enum import Enum
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QStyle, QWidget
from sqlalchemy import func

from ..core.const import USER_OBJECT
from ..database.export_models import ExportImport
from ..database.models import RedditObject, RedditObjectList, User
from ..database.model_enums import PostDownloadSource
from ..guiresources.import_reddit_export_dialog_auto import Ui_ImportRedditExportDialog
from ..utils import injector, system_util, TokenParser
from ..utils.importers.reddit_export import InvalidExportError
from ..utils.importers.reddit_export.export_importer import ExportImportOptions
from ..utils.importers.reddit_export.export_reader import RedditExportReader
from ..utils.importers.reddit_export.export_records import (ExportManifest, POSTS_FILE, COMMENTS_FILE, CHAT_HISTORY_FILE,
                                                            MESSAGES_FILE, MESSAGES_ARCHIVE_FILE)


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

SUMMARY_STYLE = ('QLabel#summary_label { background: palette(alternate-base); border: 1px solid palette(mid); '
                 'border-radius: 6px; }')


class StatusSeverity(Enum):
    """How serious a message in the dialog's status banner is, which decides the banner's color and icon."""

    ERROR = ('rgba(220, 53, 69, 0.15)', 'rgba(220, 53, 69, 0.6)', QStyle.StandardPixmap.SP_MessageBoxCritical)
    WARNING = ('rgba(255, 193, 7, 0.18)', 'rgba(255, 193, 7, 0.7)', QStyle.StandardPixmap.SP_MessageBoxWarning)

    @property
    def style_sheet(self) -> str:
        """
        The banner frame's style sheet: a translucent tint and border, so that it reads on light and dark themes.
        :return: The style sheet.
        :rtype: str
        """
        background, border, _ = self.value
        return f'QFrame#status_frame {{ background: {background}; border: 1px solid {border}; border-radius: 6px; }}'

    @property
    def icon(self) -> QStyle.StandardPixmap:
        """
        The standard icon shown beside the message.
        :return: The icon.
        :rtype: QStyle.StandardPixmap
        """
        return self.value[2]


def bold(text: str) -> str:
    """
    Escapes text for a rich-text label and makes it bold.
    :param text: The plain text.
    :type text: str
    :return: The HTML.
    :rtype: str
    """
    return f'<b>{html.escape(text)}</b>'


def bare_account_name(text: str) -> str:
    """
    Returns an account name as typed, without surrounding space or a 'u/' prefix.
    :param text: The typed name.
    :type text: str
    :return: The bare name.
    :rtype: str
    """
    return text.strip().removeprefix('/u/').removeprefix('u/')


def save_folder(user: User) -> str:
    """
    Returns the folder a user's post media is saved in, which is also where the media in its imported messages is
    saved.  Tokens in the save structure that depend on a post, such as the title, are left out.
    :param user: The user, with its download settings.
    :type user: User
    :return: The folder.
    :rtype: str
    """
    base = user.custom_post_save_path or injector.get_settings_manager().user_save_directory
    sub_path = system_util.clean_path(TokenParser.parse_tokens(user, user.post_save_structure or ''), ends_with_dir=True)
    return system_util.join_path(base, sub_path)


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

        self.summary_label.setStyleSheet(SUMMARY_STYLE)
        # A margin, unlike style sheet padding, is counted in the label's height for its width, so wrapped text is not cut off.
        self.summary_label.setMargin(8)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setStyleSheet('background: transparent; border: none;')
        self.status_icon_label.setStyleSheet('background: transparent; border: none;')
        self.status_frame.hide()

        self.hydrate_check_box.setChecked(bool(self.settings_manager.export_import_hydrate))
        self.download_media_check_box.setChecked(bool(self.settings_manager.export_import_queue_downloads))

        with injector.get_database_handler().get_scoped_session() as session:
            for list_id, list_name in session.query(RedditObjectList.id, RedditObjectList.name) \
                    .filter(RedditObjectList.list_type == USER_OBJECT).order_by(RedditObjectList.name):
                self.account_list_combo.addItem(list_name, list_id)
        if self.account_list_combo.count() == 0:
            self.account_list_combo.setToolTip('There are no user lists. Create one before importing.')

        self.browse_button.clicked.connect(self.select_file)
        self.account_line_edit.textChanged.connect(self.update_ok_button)
        self.account_list_combo.currentIndexChanged.connect(self.update_ok_button)
        for check_box in (self.posts_check_box, self.comments_check_box, self.chats_check_box,
                          self.private_messages_check_box, self.hydrate_check_box, self.download_media_check_box):
            check_box.toggled.connect(self.update_ok_button)
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
            self._show_status(f'This is not a Reddit data export: {error}', StatusSeverity.ERROR)
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
        self._show_status(self._previous_import_text(manifest), StatusSeverity.WARNING)
        self.update_ok_button()

    def _show_status(self, text: str, severity: StatusSeverity) -> None:
        """
        Shows a message in the status banner, tinted and with an icon for its severity, or hides the banner when there
        is no message.
        :param text: The message, or an empty string to hide the banner.
        :type text: str
        :param severity: How serious the message is.
        :type severity: StatusSeverity
        :return: None
        :rtype: None
        """
        if not text:
            self.status_frame.hide()
            return
        self.status_label.setText(text)
        self.status_icon_label.setPixmap(self.style().standardIcon(severity.icon).pixmap(20, 20))
        self.status_frame.setStyleSheet(severity.style_sheet)
        self.status_frame.show()
        self._fit_height()

    def _fit_height(self) -> None:
        """
        Makes the dialog tall enough for its wrapped summary and status text at its current width.  Qt does not grow a
        window for wrapped labels by itself, so without this the end of a long summary is cut off.  The dialog never
        shrinks here, so it does not jump while the user changes options.
        :return: None
        :rtype: None
        """
        needed = self.layout().totalHeightForWidth(self.width())
        if needed > self.height():
            self.resize(self.width(), needed)

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

    @property
    def account_list_id(self) -> Optional[int]:
        """
        The id of the user list the account is added to.
        :return: The list id, or None while no list is chosen (only when there are no user lists).
        :rtype: Optional[int]
        """
        return self.account_list_combo.currentData()

    def update_ok_button(self) -> None:
        """
        Enables the OK button once a valid archive is loaded, an account is named, a list is chosen and something is
        selected, enables the media download checkbox when posts or messages are imported, and refreshes the summary.
        :return: None
        :rtype: None
        """
        anything_selected = any(box.isChecked() for box in (self.posts_check_box, self.comments_check_box,
                                                            self.chats_check_box, self.private_messages_check_box))
        ready = (self.zip_path is not None and bool(bare_account_name(self.account_line_edit.text()))
                 and self.account_list_id is not None and anything_selected)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ready)
        self.download_media_check_box.setEnabled(any(box.isChecked() for box in (
            self.posts_check_box, self.chats_check_box, self.private_messages_check_box)))
        self.update_summary()

    def update_summary(self) -> None:
        """
        Describes what the import will do with the choices made: the users added to the list, whether and from where
        missing data is filled in, and whether and where media is downloaded.
        :return: None
        :rtype: None
        """
        name = bare_account_name(self.account_line_edit.text())
        list_id = self.account_list_id
        if not name or list_id is None:
            placeholder = ('Name the account and choose a user list to see what the import will do.'
                           if self.account_list_combo.count() else
                           'There are no user lists. Create a user list before importing.')
            self.summary_label.setText(f'<i>{html.escape(placeholder)}</i>')
            return
        with injector.get_database_handler().get_scoped_session() as session:
            user_list = session.query(RedditObjectList).get(list_id)
            list_name = bold(user_list.name)
            existing = session.query(User).filter(func.lower(User.name) == name.lower()).first()
            lines = [self._account_line(name, user_list, existing)]
            if self.chats_check_box.isChecked() or self.private_messages_check_box.isChecked():
                lines.append(f"Add every user in the imported chats and private messages to {list_name}. Users "
                             "not on a list yet take the list's settings; users already on a list keep their own.")
            if self.hydrate_check_box.isChecked():
                lines.append(f'Fill in scores and metadata from {bold(user_list.post_download_source.display_name)}.')
            else:
                lines.append('Do not look up missing data.')
            if self.download_media:
                # An account not on a list yet takes the list's settings, so its folder is that of a user with them.
                takes_list_settings = existing is None or not existing.significant
                settings_user = User(name=name, **user_list.get_default_dict()) if takes_list_settings else existing
                lines.append("Download media for each author whose download is enabled, into the author's own folder "
                             f'({bold(f"u/{name}")}: <code>{html.escape(save_folder(settings_user))}</code>).')
            else:
                lines.append('Do not download media.')
        items = ''.join(f'<li>{line}</li>' for line in lines)
        self.summary_label.setText(f'<b>This import will:</b><ul style="margin-left: -24px;">{items}</ul>')
        self._fit_height()

    @staticmethod
    def _account_line(name: str, user_list: RedditObjectList, existing: Optional[User]) -> str:
        """
        Describes what happens to the account: added to the list with the list's settings when it is not on a list yet
        (new, or known only from other people's posts and messages), added keeping its own settings, or already on it.
        :param name: The account name.
        :type name: str
        :param user_list: The chosen list.
        :type user_list: RedditObjectList
        :param existing: The account when it is already in the database.
        :type existing: Optional[User]
        :return: The description, as rich text with the names escaped and in bold.
        :rtype: str
        """
        list_name = bold(user_list.name)
        if existing is None or not existing.significant:
            return f"Add {bold(f'u/{name}')} to list {list_name} with the list's download settings."
        account = bold(f'u/{existing.name}')
        if user_list.reddit_objects.filter(RedditObject.id == existing.id).first() is not None:
            return f'{account} is already on list {list_name} and keeps its own settings.'
        return f'Add {account} to list {list_name}; it keeps its own settings.'

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
            account_list_id=self.account_list_id,
        )

    @property
    def hydration_source(self) -> Optional[PostDownloadSource]:
        """
        The download source missing data is filled in from: the chosen list's, when filling in is checked.
        :return: The source, or None when nothing is to be looked up.
        :rtype: Optional[PostDownloadSource]
        """
        list_id = self.account_list_id
        if not self.hydrate_check_box.isChecked() or list_id is None:
            return None
        with injector.get_database_handler().get_scoped_session() as session:
            user_list = session.query(RedditObjectList).get(list_id)
            return user_list.post_download_source if user_list is not None else None

    @property
    def download_media(self) -> bool:
        """
        Whether the media in the imported posts and messages is to be downloaded after the import.
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
        self.settings_manager.export_import_hydrate = self.hydrate_check_box.isChecked()
        self.settings_manager.export_import_queue_downloads = self.download_media_check_box.isChecked()
        super().accept()
