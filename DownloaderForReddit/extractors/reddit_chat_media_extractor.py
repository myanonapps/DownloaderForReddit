"""
Extracts media uploaded to Reddit chat.

Images and videos sent in Reddit chat are stored on Reddit's Matrix media server (matrix.redditspace.com), and chat
messages link to them with urls such as https://matrix.redditspace.com/_matrix/media/r0/download/reddit.com/<media id>.
These urls end in the media id rather than a file extension, so the extension is taken from the type the server
reports for the file.


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

import mimetypes
from typing import Optional
from urllib.parse import urlparse

import requests

from .base_extractor import BaseExtractor
from ..core import const
from ..core.errors import Error


_TIMEOUT = 10
# Types the mimetypes module names with an extension other than the one usually used for them.
_PREFERRED_EXTENSIONS = {'image/jpeg': 'jpg', 'video/quicktime': 'mov', 'image/webp': 'webp'}


def extension_for_type(content_type: Optional[str]) -> Optional[str]:
    """
    Returns the file extension for a media type, as reported in a Content-Type header.
    :param content_type: The header value, which may carry parameters such as a charset.
    :type content_type: Optional[str]
    :return: The extension without its dot, or None when the type is missing or not a known media type.
    :rtype: Optional[str]
    """
    if not content_type:
        return None
    media_type = content_type.split(';', 1)[0].strip().lower()
    if media_type in _PREFERRED_EXTENSIONS:
        return _PREFERRED_EXTENSIONS[media_type]
    extension = mimetypes.guess_extension(media_type)
    return extension.lstrip('.') if extension else None


def media_id_from_url(url: str) -> str:
    """
    Returns the media id a chat media url ends with.
    :param url: The chat media url.
    :type url: str
    :return: The last part of the url's path.
    :rtype: str
    """
    return urlparse(url).path.rstrip('/').rsplit('/', 1)[-1]


class RedditChatMediaExtractor(BaseExtractor):
    """Extracts a file uploaded to Reddit chat."""

    url_key = ['matrix.redditspace.com']

    def extract_content(self) -> None:
        """
        Makes content for the linked file.  A url that already ends in a known extension is used as it is; otherwise
        the server is asked for the file's type.
        :return: None
        :rtype: None
        """
        if self.url.lower().endswith(const.ALL_EXT):
            self.extract_direct_link()
            return
        try:
            extension = self.find_extension()
        except requests.exceptions.RequestException:
            self.handle_failed_extract(error=Error.CONNECTION_ERROR, message='Failed to reach the Reddit chat media server',
                                       log_exception=True)
            return
        if extension is None:
            self.handle_failed_extract(error=Error.UNRECOGNIZED_EXTENSION,
                                       message='Could not tell what kind of file the Reddit chat media is', log=False)
            return
        self.make_content(self.url, extension, media_id=media_id_from_url(self.url))

    def find_extension(self) -> Optional[str]:
        """
        Asks the media server for the file's type.  A HEAD request is tried first; servers that do not answer HEAD
        with a type are asked with a streamed GET, of which only the headers are read.
        :return: The extension, or None when the server reports no known media type.
        :rtype: Optional[str]
        :raises requests.exceptions.RequestException: When the server cannot be reached.
        """
        response = requests.head(self.url, timeout=_TIMEOUT, allow_redirects=True)
        extension = extension_for_type(response.headers.get('Content-Type')) if response.ok else None
        if extension is None:
            with requests.get(self.url, timeout=_TIMEOUT, stream=True) as get_response:
                if get_response.ok:
                    extension = extension_for_type(get_response.headers.get('Content-Type'))
        return extension
