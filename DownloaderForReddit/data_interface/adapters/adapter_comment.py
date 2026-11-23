"""
Downloader for Reddit takes a list of reddit users and subreddits and downloads content posted to reddit either by the
users or on the subreddits.


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


Comment adapters for the archive data sources (Arctic Shift and PullPush).

``CommentHandler`` was written against PRAW's ``Comment`` and ``CommentForest``.  The classes here provide the subset of
that interface it uses (``replace_more``, ``replies``, ``reply_sort``, ``is_submitter``, ``id``, ``body``, ``body_html``,
``score``, ``created``, ``author.name`` and ``subreddit.display_name``), so archive comments go through the same
extraction path as comments fetched from Reddit.
"""
import logging
from types import SimpleNamespace
from typing import Any, Iterable

from DownloaderForReddit.data_interface.adapter_data import AdapterData
from DownloaderForReddit.database.model_enums import PostDownloadSource
from DownloaderForReddit.utils.general_utils import dig
from DownloaderForReddit.utils.html_formatting import markdown_to_html

COMMENT_FULLNAME_PREFIX = "t1_"
COMMENT_KIND = "t1"
MORE_KIND = "more"

logger = logging.getLogger(f'DownloaderForReddit.{__name__}')


class AdapterCommentForest(list):
    """
    A list of comments that stands in for PRAW's ``CommentForest``.  The archives return every stored comment at once,
    so there are never "load more comments" stubs to replace.
    """

    def replace_more(self, limit: int | None = 0) -> list:
        """
        Does nothing, because archive comment lists are already complete.  Present so callers written for PRAW work.

        :param limit: Ignored; PRAW's maximum number of "more comments" stubs to replace.
        :type limit: int | None
        :return: Always an empty list, as PRAW returns the stubs that were not replaced.
        :rtype: list
        """
        logger.debug("replace_more(limit=%s) is not needed for archive comments", limit)
        return []


class AdapterComment(AdapterData):  # pylint: disable=too-many-instance-attributes,too-few-public-methods  # a data holder mirroring PRAW Comment's fields
    """
    A comment from an archive data source, shaped like the parts of PRAW's ``Comment`` that the application uses.
    """

    def __init__(self, adapter_type: PostDownloadSource, dict_data: dict, submission_author: str = ""):
        """
        Builds the comment from one Reddit-format comment dictionary.  Arctic Shift and PullPush both use Reddit's own
        field names, so the same parser serves both.

        :param adapter_type: The data source the comment came from.
        :type adapter_type: PostDownloadSource
        :param dict_data: The comment's fields as returned by the archive.
        :type dict_data: dict
        :param submission_author: The name of the submission's author, used to work out ``is_submitter`` when the
                                  archive does not record it.
        :type submission_author: str
        """
        super().__init__(adapter_type)
        self.id: str = str(dig(dict_data, "id", default=""))
        self.parent_id: str = str(dig(dict_data, "parent_id", default=""))
        self.link_id: str = str(dig(dict_data, "link_id", default=""))
        self.body: str = dig(dict_data, "body", default="")
        body_html = dig(dict_data, "body_html", default="")
        if not body_html and self.body:
            # The archives usually store only the markdown, so build the html the same way submissions do
            body_html = markdown_to_html(self.body) or ""
        self.body_html: str = body_html
        self.score: int = dig(dict_data, "score", default=0)
        self.created_utc: float = dig(dict_data, "created_utc", default=0)
        self.created: float = dig(dict_data, "created", default=0) or self.created_utc
        author_name = dig(dict_data, "author", default="")
        self.author = SimpleNamespace(name=author_name)
        self.subreddit = SimpleNamespace(display_name=dig(dict_data, "subreddit", default=""))
        is_submitter = dig(dict_data, "is_submitter")
        if is_submitter is None:
            is_submitter = bool(author_name) and author_name == submission_author
        self.is_submitter: bool = bool(is_submitter)
        self.replies: AdapterCommentForest = AdapterCommentForest()
        self.reply_sort: str = "best"


def _flatten(items: Iterable[Any]) -> list[dict]:
    """
    Converts archive comment results into a flat list of comment dictionaries.  Accepts both flat results (PullPush, and
    Arctic Shift searches) and Reddit's nested listing format (Arctic Shift's comment tree), in which each entry is
    ``{"kind": "t1", "data": {..., "replies": {"kind": "Listing", "data": {"children": [...]}}}}``.  "more" stubs are
    dropped, since the archive has no way to expand them.

    :param items: The entries returned by the archive.
    :type items: Iterable[Any]
    :return: Every comment found, parents before their replies, without the nested ``replies`` key.
    :rtype: list[dict]
    """
    flat: list[dict] = []
    stack = list(reversed(list(items or [])))
    while stack:
        item = stack.pop()
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind == MORE_KIND:
            continue
        data = item.get("data") if kind == COMMENT_KIND and isinstance(item.get("data"), dict) else item
        replies = data.get("replies")
        flat.append({key: value for key, value in data.items() if key != "replies"})
        children = dig(replies, "data", "children", default=[]) if isinstance(replies, dict) else replies
        if isinstance(children, list):
            stack.extend(reversed(children))
    return flat


def _sort_forest(forest: AdapterCommentForest, sort: str) -> None:
    """
    Sorts a comment level, and every level below it, in place.  The archives cannot apply Reddit's ranking, so ``new``
    and ``old`` sort by date and every other sort method sorts by score, highest first.

    :param forest: The comments to sort.
    :type forest: AdapterCommentForest
    :param sort: The sort method name, as ``CommentHandler`` sets it (for example ``new``, ``old`` or ``top``).
    :type sort: str
    """
    if sort == "new":
        forest.sort(key=lambda comment: comment.created_utc, reverse=True)
    elif sort == "old":
        forest.sort(key=lambda comment: comment.created_utc)
    else:
        forest.sort(key=lambda comment: comment.score or 0, reverse=True)
    for comment in forest:
        _sort_forest(comment.replies, sort)


def build_comment_forest(items: Iterable[Any], adapter_type: PostDownloadSource, submission_author: str = "",
                         sort: str = "best") -> AdapterCommentForest:
    """
    Builds the comment tree of a submission from archive results.  Comments are linked to their parents through
    ``parent_id``.  A comment whose parent is the submission, or whose parent the archive does not hold, becomes a
    top-level comment so that it is not lost.

    :param items: The comment entries returned by the archive, flat or nested.
    :type items: Iterable[Any]
    :param adapter_type: The data source the comments came from.
    :type adapter_type: PostDownloadSource
    :param submission_author: The name of the submission's author, used for ``is_submitter``.
    :type submission_author: str
    :param sort: The sort method to order each level by.
    :type sort: str
    :return: The top-level comments, each holding its replies.
    :rtype: AdapterCommentForest
    """
    comments: dict[str, AdapterComment] = {}
    for data in _flatten(items):
        comment = AdapterComment(adapter_type, data, submission_author)
        if comment.id and comment.id not in comments:
            comments[comment.id] = comment

    parent_of: dict[str, str] = {}
    forest = AdapterCommentForest()
    for comment in comments.values():
        parent = None
        if comment.parent_id.startswith(COMMENT_FULLNAME_PREFIX):
            parent = comments.get(comment.parent_id[len(COMMENT_FULLNAME_PREFIX):])
        if parent is not None and not _creates_cycle(comment.id, parent.id, parent_of):
            parent.replies.append(comment)
            parent_of[comment.id] = parent.id
        else:
            forest.append(comment)
    _sort_forest(forest, sort or "best")
    return forest


def _creates_cycle(comment_id: str, parent_id: str, parent_of: dict[str, str]) -> bool:
    """
    Checks whether attaching a comment to a parent would make the comment its own ancestor.  Real data never does this,
    but a corrupt archive record must not send tree building or sorting into an endless loop.

    :param comment_id: The id of the comment being attached.
    :type comment_id: str
    :param parent_id: The id of the proposed parent.
    :type parent_id: str
    :param parent_of: The parent of every comment attached so far, keyed by comment id.
    :type parent_of: dict[str, str]
    :return: True if the comment is the proposed parent or one of its ancestors.
    :rtype: bool
    """
    current: str | None = parent_id
    while current is not None:
        if current == comment_id:
            return True
        current = parent_of.get(current)
    return False
