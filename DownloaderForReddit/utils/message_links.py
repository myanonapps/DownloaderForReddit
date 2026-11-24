"""
Finds the links in the text of an imported chat or private message.

Message bodies in a Reddit data export are plain text or markdown, not html, so links are found in the text itself:
markdown links ([text](url) and <url>) and bare http(s) urls.


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

import re
from typing import Optional


_URL = re.compile(r'https?://[^\s<>"\'\]\[]+', re.IGNORECASE)
# Characters that end a sentence or close a bracket, and so usually follow a url in text rather than belong to it.
_TRAILING = '.,;:!?\'"*_~'
_BRACKETS = {')': '(', ']': '['}


def _trim(url: str) -> str:
    """
    Removes the punctuation that ends a sentence or closes a bracket from the end of a url found in text.  A closing
    bracket is kept when the url opens one, as in Wikipedia style urls.
    :param url: The url as found.
    :type url: str
    :return: The url without trailing punctuation.
    :rtype: str
    """
    while url:
        last = url[-1]
        if last in _TRAILING:
            url = url[:-1]
        elif last in _BRACKETS and url.count(_BRACKETS[last]) < url.count(last):
            url = url[:-1]
        else:
            break
    return url


def find_links(body: Optional[str]) -> list[str]:
    """
    Returns the http(s) links in a message's text, each once, in the order they first appear.  Markdown link syntax
    is understood: the url of [text](url) is found without its closing bracket, and <url> without its angle brackets.
    :param body: The message text.
    :type body: Optional[str]
    :return: The links.
    :rtype: list[str]
    """
    if not body:
        return []
    links: list[str] = []
    for match in _URL.finditer(body):
        url = _trim(match.group())
        if url and url not in links and len(url) > len('https://'):
            links.append(url)
    return links


def has_links(body: Optional[str]) -> bool:
    """
    Whether a message's text holds at least one http(s) link.
    :param body: The message text.
    :type body: Optional[str]
    :return: True when there is a link.
    :rtype: bool
    """
    return bool(find_links(body))
