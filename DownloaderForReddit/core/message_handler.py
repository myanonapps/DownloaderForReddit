"""
Extracts the media linked in an imported chat or private message.

Each http(s) link in the message's text is matched to an extractor, as a post's link is.  The content made is tied to
the message and downloaded as the settings of the message's author say: nothing is downloaded for an author whose
download is disabled, and the files go to the author's own folder.  An import puts every user it finds in conversations
on the chosen user list, so these are that list's settings.  The id of each content made is put on the download queue.
Links that no extractor handles are ordinary web links, not media, and are passed over.


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
from queue import Queue
from threading import Event
from typing import Optional

import requests

from .errors import Error
from .runner import Runner
from .submission_handler import assign_extractor
from ..database.export_models import ImportedMessage
from ..messaging.message import Message
from ..utils import injector
from ..utils.message_links import find_links


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

# What an extractor can raise for a bad or unreachable link.  Most extractors report their own failures; these are
# caught so that one bad link does not stop the rest of the message's links from being extracted.
_EXTRACTION_ERRORS = (requests.exceptions.RequestException, OSError, ValueError, KeyError, IndexError, AttributeError,
                      TypeError)


class MessageHandler(Runner):
    """Extracts the links in one imported message and queues the content made from them for download."""

    def __init__(self, message: ImportedMessage, download_queue: Queue, stop_run: Event,
                 download_session_id: Optional[int] = None) -> None:
        """
        :param message: The message to extract, attached to an open session.
        :type message: ImportedMessage
        :param download_queue: The queue the ids of the content made are put on.
        :type download_queue: Queue
        :param stop_run: Set when the download session is stopped.
        :type stop_run: Event
        :param download_session_id: The download session the extraction runs in, for output messages.
        :type download_session_id: Optional[int]
        """
        super().__init__(stop_run)
        self.message = message
        self.download_queue = download_queue
        self.extractor_dict: dict[str, bool] = injector.get_settings_manager().extractor_dict  # enabled extractors by name
        self.download_session_id = download_session_id
        self.content_ids: list[int] = []
        self.failures: list[str] = []

    def extract(self) -> None:
        """
        Extracts every link in the message, queues the content made, and records the message as extracted, or as
        failed with the reasons when a media link could not be extracted.  Nothing is recorded when the run is stopped
        part way.  A message whose author has download disabled is skipped and left unextracted, so its media is
        downloaded once download is enabled again; one without a linked author is recorded as failed.  A chat reaction is
        recorded as extracted without extracting anything, since the reaction's image is stored once for every chat.
        :return: None
        :rtype: None
        """
        if getattr(self.message, 'is_reaction', False):
            self.message.set_extracted()
            return
        author = self.message.significant_reddit_object
        if author is None:
            self.message.set_extraction_failed(Error.FAILED_TO_EXTRACT, 'The message has no known author')
            return
        if not author.download_enabled:
            logger.debug('Download is disabled for %s; media in %s left for later', author.name, self.message)
            return
        links = find_links(self.message.body)
        numbered = len(links) > 1
        for number, url in enumerate(links, start=1):
            if not self.continue_run:
                return
            self.extract_link(url, number if numbered else None)
        if self.failures:
            self.message.set_extraction_failed(Error.TEXT_LINK_FAILURE, '\n'.join(self.failures))
        else:
            self.message.set_extracted()

    def extract_link(self, url: str, count: Optional[int]) -> None:
        """
        Extracts one link of the message and queues the content made from it.
        :param url: The link.
        :type url: str
        :param count: The link's number among the message's links, used to number its files; None for a message with
                      a single link.
        :type count: Optional[int]
        :return: None
        :rtype: None
        """
        extractor_class = assign_extractor(url, self.extractor_dict)
        if extractor_class is None:
            logger.debug('No extractor handles %s; treated as an ordinary link', url)
            return
        if extractor_class.needs_post:
            self.fail(url, 'this kind of link can only be downloaded from the reddit post it belongs to')
            return
        extractor = extractor_class(None, message=self.message, url=url, count=count)
        try:
            extractor.extract_content()
        except _EXTRACTION_ERRORS:
            logger.exception('Failed to extract %s from %s', url, self.message)
            self.fail(url, 'an unexpected error occurred')
            return
        if extractor.failed_extraction and extractor.extraction_error != Error.FAILED_FILTER:
            if extractor_class.matches_loosely and not extractor.extracted_content:
                logger.debug('%s found no media in %s; treated as an ordinary link', extractor_class.__name__, url)
            else:
                self.failures.append(f'{url}: {extractor.failed_extraction_message or extractor.extraction_error}')
        for content in extractor.extracted_content:
            self.content_ids.append(content.id)
            self.download_queue.put(content.id)

    def fail(self, url: str, reason: str) -> None:
        """
        Records that a link of the message could not be extracted, and reports it in the output.
        :param url: The link.
        :type url: str
        :param reason: Why it could not be extracted.
        :type reason: str
        :return: None
        :rtype: None
        """
        self.failures.append(f'{url}: {reason}')
        Message.send_extraction_error(f'Could not extract a link in a message: {reason}\nMessage: {self.message.title}\nUrl: {url}',
                                      session_id=self.download_session_id)
