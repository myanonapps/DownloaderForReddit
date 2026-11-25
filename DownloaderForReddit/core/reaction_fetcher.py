"""
Fetches the images of chat reactions into the application's reactions folder.

Each reaction's image is stored once, whichever chats use it.  When the image was already downloaded as the media of a
message (as happened before reactions were recognized), that file is copied; otherwise the image is downloaded.


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
import shutil
import threading
from typing import Callable, Optional
from urllib.parse import urlparse

import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database.export_models import ChatReaction, reactions_folder
from ..database.models import Content
from ..messaging.message import Message
from ..utils import injector


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

_TIMEOUT_SECONDS = 30
_DEFAULT_EXTENSION = '.gif'


def reaction_file_name(reaction: ChatReaction) -> str:
    """
    Returns the name a reaction's image is stored under: its image id and the extension of its url.
    :param reaction: The reaction.
    :type reaction: ChatReaction
    :return: The file name.
    :rtype: str
    """
    extension = os.path.splitext(urlparse(reaction.url or '').path)[1] or _DEFAULT_EXTENSION
    return f'{reaction.image_id or reaction.id}{extension.lower()}'


def _downloaded_copy(session: Session, url: str) -> Optional[str]:
    """
    Finds a file already downloaded from a url as the media of a post, comment or message.
    :param session: The database session.
    :type session: Session
    :param url: The url.
    :type url: str
    :return: The file's path, or None when no downloaded file of the url is on disk.
    :rtype: Optional[str]
    """
    for content in session.query(Content).filter(Content.url == url, Content.downloaded.is_(True)):
        path = content.get_full_file_path()
        if path and os.path.isfile(path):
            return path
    return None


def _download(url: str, target: str) -> None:
    """
    Downloads a url to a file, writing a temporary file first so that a failed download leaves no partial image.
    :param url: The url.
    :type url: str
    :param target: The file to write.
    :type target: str
    :return: None
    :rtype: None
    :raises requests.exceptions.RequestException: When the request fails or the response is not successful.
    :raises OSError: When the file cannot be written.
    """
    response = requests.get(url, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    partial = f'{target}.part'
    with open(partial, 'wb') as file:
        file.write(response.content)
    os.replace(partial, target)


def fetch_reaction_image(session: Session, reaction: ChatReaction) -> bool:
    """
    Stores a reaction's image in the reactions folder, copying a file already downloaded from its url when there is
    one, and records the file name, or the error when it could not be stored.  The caller commits.
    :param session: The database session.
    :type session: Session
    :param reaction: The reaction.
    :type reaction: ChatReaction
    :return: True when the image was stored.
    :rtype: bool
    """
    folder = reactions_folder()
    file_name = reaction_file_name(reaction)
    target = os.path.join(folder, file_name)
    try:
        os.makedirs(folder, exist_ok=True)
        source = _downloaded_copy(session, reaction.url)
        if source is not None:
            shutil.copyfile(source, target)
        else:
            _download(reaction.url, target)
    except (OSError, requests.exceptions.RequestException) as error:
        logger.warning('Could not fetch the image of reaction %s', reaction.url, exc_info=True)
        reaction.fetch_error = str(error)
        return False
    reaction.file_name = file_name
    reaction.fetch_error = None
    return True


def fetch_missing_reaction_images(session: Session, stop_event: Optional[threading.Event] = None) -> tuple[int, int]:
    """
    Fetches the image of every enabled reaction whose image is not on disk, committing after each one.
    :param session: The database session.
    :type session: Session
    :param stop_event: Stops the fetch between images when set.
    :type stop_event: Optional[threading.Event]
    :return: The number of images fetched and the number that failed.
    :rtype: tuple[int, int]
    """
    fetched, failed = 0, 0
    for reaction in session.query(ChatReaction).filter(ChatReaction.enabled.isnot(False)).order_by(ChatReaction.id).all():
        if stop_event is not None and stop_event.is_set():
            break
        if reaction.has_image:
            continue
        if fetch_reaction_image(session, reaction):
            fetched += 1
        else:
            failed += 1
        session.commit()
    return fetched, failed


def report_fetch(fetched: int, failed: int) -> None:
    """
    Tells the user how a fetch of reaction images went, when it did anything.
    :param fetched: The number of images fetched.
    :type fetched: int
    :param failed: The number of images that could not be fetched.
    :type failed: int
    :return: None
    :rtype: None
    """
    if fetched:
        Message.send_info(f'Stored {fetched:,} chat reaction images')
    if failed:
        Message.send_warning(f'{failed:,} chat reaction images could not be fetched; see the log for details')


class ReactionFetcher(QObject):
    """Fetches the missing reaction images off the GUI thread; run() is meant to be started by a QThread."""

    finished = pyqtSignal(int, int)  # images fetched, images that failed

    def __init__(self) -> None:
        """Creates the fetcher."""
        super().__init__()
        self.stop_event = threading.Event()

    def stop(self) -> None:
        """
        Asks the fetch to stop after the image it is fetching.
        :return: None
        :rtype: None
        """
        self.stop_event.set()

    def run(self) -> None:
        """
        Fetches the missing images, reports the outcome and emits finished, even when the fetch fails.
        :return: None
        :rtype: None
        """
        fetched, failed = 0, 0
        try:
            with injector.get_database_handler().get_scoped_session() as session:
                fetched, failed = fetch_missing_reaction_images(session, self.stop_event)
            report_fetch(fetched, failed)
        except SQLAlchemyError:
            logger.exception('Fetching chat reaction images failed')
            Message.send_error('Fetching chat reaction images failed; see the log for details')
        finally:
            self.finished.emit(fetched, failed)


def start_fetch_thread(on_fetched: Callable[[int, int], None], on_done: Callable[[], None]) -> tuple[QThread, ReactionFetcher]:
    """
    Starts fetching the missing reaction images on a thread of its own.  The caller keeps the returned thread and
    fetcher alive until on_done is called, after the thread has finished.
    :param on_fetched: Called with the number of images fetched and the number that failed; connect a method of an
                       object of the GUI thread so it runs there.
    :type on_fetched: Callable[[int, int], None]
    :param on_done: Called once the thread has finished, when the thread and fetcher may be released.
    :type on_done: Callable[[], None]
    :return: The thread and the fetcher.
    :rtype: tuple[QThread, ReactionFetcher]
    """
    fetcher = ReactionFetcher()
    thread = QThread()
    fetcher.moveToThread(thread)
    thread.started.connect(fetcher.run)
    fetcher.finished.connect(thread.quit)
    fetcher.finished.connect(on_fetched)
    thread.finished.connect(on_done)
    thread.start()
    return thread, fetcher
