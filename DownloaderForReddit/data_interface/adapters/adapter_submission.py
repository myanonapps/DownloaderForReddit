"""
PRAW Submission adapter for the Reddit Data Interface.

This module wraps PRAW Submission functionality to match the abstract AdapterData interface.
"""
from types import SimpleNamespace
from typing import Callable

import requests

from DownloaderForReddit.data_interface.adapter_data import AdapterData
from DownloaderForReddit.data_interface.adapters.adapter_comment import AdapterCommentForest, build_comment_forest
from DownloaderForReddit.database.model_enums import PostDownloadSource
from DownloaderForReddit.utils.general_utils import dig
from DownloaderForReddit.utils.html_formatting import markdown_to_html

# Constants for data keys
ID_KEY = "id"
FULLNAME_KEY = "fullname"
NAME_KEY = "name"
CREATED_UTC_KEY = "created_utc"
CREATED_KEY = "created"
DISPLAY_NAME_KEY = "display_name"
SCORE_KEY = "score"
TITLE_KEY = "title"
URL_KEY = "url"
DOMAIN_KEY = "domain"
OVER_18_KEY = "over_18"
IS_SELF_KEY = "is_self"
SELFTEXT_KEY = "selftext"
SELFTEXT_HTML_KEY = "selftext_html"
BODY_KEY = "body"
BODY_HTML_KEY = "body_html"
AUTHOR_KEY = "author"
SUBREDDIT_KEY = "subreddit"
PINNED_KEY = "pinned"
STICKIED_KEY = "stickied"
CROSSPOST_PARENT_KEY = "crosspost_parent"
MEDIA_METADATA_KEY = "media_metadata"
MEDIA_KEY = "media"
SECURE_MEDIA_KEY = "secure_media"


class AdapterSubmission(AdapterData):
    """
    Adapter that wraps PRAW Submission to provide a consistent interface.
    
    This class maintains backward compatibility with existing PRAW Submission usage
    while providing a consistent interface for different data adapter implementations.
    """

    def __init__(self, adapter_type:PostDownloadSource, dict_data:dict,
                 comment_loader: Callable[[str, int | None], list[dict]] | None = None):
        """
        Initializes the submission adapter from an archive result.

        :param adapter_type: The data source the submission came from.
        :type adapter_type: PostDownloadSource
        :param dict_data: The submission's fields as returned by the data source.
        :type dict_data: dict
        :param comment_loader: Fetches the raw comments of a submission, given its id and the maximum number of
                               comments wanted.  Without one, the submission has no comments.
        :type comment_loader: Callable[[str, int | None], list[dict]] | None
        """
        super().__init__(adapter_type)
        self._comment_loader = comment_loader
        self._comments: AdapterCommentForest | None = None
        # Set by CommentHandler before reading comments, as with PRAW submissions
        self.comment_sort: str = "best"
        self.comment_limit: int | None = None
        match adapter_type:
            case PostDownloadSource.ARCTIC_SHIFT:
                self.from_arctic_shift(dict_data)
            case PostDownloadSource.PULL_PUSH:
                self.from_pull_push(dict_data)
            case PostDownloadSource.REDDIT:
                pass


    def __getattr__(self, attr):
        if attr == "__iter__":
            return None
        self.logger.error("Invoked the fallback method in '%s' for missing: %s", self.__class__.__name__, attr)
        return None

    @property
    def comments(self) -> AdapterCommentForest:
        """
        The submission's comment tree, fetched from the data source on first access and then cached.  It is fetched
        lazily so that ``comment_sort`` and ``comment_limit`` can be set first, as with PRAW submissions.

        :return: The top-level comments, each holding its replies.  Empty if there is no comment loader or the fetch
                 fails.
        :rtype: AdapterCommentForest
        """
        if self._comments is None:
            # vars() avoids the logging __getattr__ fallback when the fields were never filled
            submission_id = vars(self).get(ID_KEY, "")
            author_name = getattr(vars(self).get(AUTHOR_KEY), NAME_KEY, "")
            items: list[dict] = []
            if self._comment_loader is not None and submission_id:
                try:
                    items = self._comment_loader(submission_id, self.comment_limit)
                except (requests.exceptions.RequestException, ValueError):
                    self.logger.exception("Failed to load comments for submission %s", submission_id)
            self._comments = build_comment_forest(items, self._adapter_type, author_name, self.comment_sort)
        return self._comments

    def from_pull_push(self, dict_data: dict) -> None:
        """
        Fills the submission from a PullPush ``/topic`` result.  PullPush serves posts in Reddit's own JSON format,
        the same as Arctic Shift, so the Arctic Shift parser is reused.  PullPush items carry only ``created_utc``,
        so ``created`` falls back to it.

        :param dict_data: One item from the ``data`` list of a PullPush ``/topic`` response.
        :type dict_data: dict
        """
        self.from_arctic_shift(dict_data)
        if not getattr(self, CREATED_KEY):
            setattr(self, CREATED_KEY, getattr(self, CREATED_UTC_KEY))

    def from_arctic_shift(self, dict_data:dict):
        setattr(self, TITLE_KEY, dig(dict_data, TITLE_KEY, default=""))
        setattr(self, URL_KEY, dig(dict_data, URL_KEY, default=""))
        setattr(self, ID_KEY, dig(dict_data, ID_KEY, default=""))
        setattr(self, DOMAIN_KEY, dig(dict_data, DOMAIN_KEY, default=""))
        setattr(self, SCORE_KEY, dig(dict_data, SCORE_KEY, default=0))
        setattr(self, PINNED_KEY, bool(dig(dict_data, PINNED_KEY, PINNED_KEY, default=False)))
        setattr(self, STICKIED_KEY, bool(dig(dict_data, STICKIED_KEY, STICKIED_KEY, default=False)))
        setattr(self, OVER_18_KEY, bool(dig(dict_data, OVER_18_KEY, default=False)))
        setattr(self, IS_SELF_KEY, bool(dig(dict_data, IS_SELF_KEY, default=False)))

        selftext = dig(dict_data, SELFTEXT_KEY, default="")
        selftext_html = dig(dict_data, SELFTEXT_HTML_KEY, default="")
        if not selftext_html and selftext:
            # Arctic Shift only sends selftext_html when asked with md2html, so build it from the markdown
            selftext_html = markdown_to_html(selftext) or ""
        setattr(self, SELFTEXT_KEY, selftext)
        setattr(self, SELFTEXT_HTML_KEY, selftext_html)

        author = SimpleNamespace()
        setattr(author, NAME_KEY, dig(dict_data, "author", default=""))
        setattr(self, AUTHOR_KEY, author)
        setattr(self, FULLNAME_KEY, dig(dict_data, "author_fullname", default=""))
        setattr(self, CREATED_KEY, dig(dict_data, CREATED_KEY, default=0))
        setattr(self, CREATED_UTC_KEY, dig(dict_data, CREATED_UTC_KEY, default=0))
        subreddit = SimpleNamespace()
        setattr(subreddit, DISPLAY_NAME_KEY, dig(dict_data, "subreddit", default=""))
        setattr(self, SUBREDDIT_KEY, subreddit)

        setattr(self, CROSSPOST_PARENT_KEY, dig(dict_data, CROSSPOST_PARENT_KEY, default=""))
        media_meta = dig(dict_data, MEDIA_METADATA_KEY, default={})
        setattr(self, MEDIA_METADATA_KEY, media_meta)
        setattr(self, MEDIA_KEY, dig(dict_data, MEDIA_KEY))
        setattr(self, SECURE_MEDIA_KEY, dig(dict_data, SECURE_MEDIA_KEY))
