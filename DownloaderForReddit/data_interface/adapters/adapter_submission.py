"""
PRAW Submission adapter for the Reddit Data Interface.

This module wraps PRAW Submission functionality to match the abstract AdapterData interface.
"""
from types import SimpleNamespace

from DownloaderForReddit.data_interface.adapter_data import AdapterData
from DownloaderForReddit.database.model_enums import PostDownloadSource
from DownloaderForReddit.utils.general_utils import dig

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


class AdapterSubmission(AdapterData):
    """
    Adapter that wraps PRAW Submission to provide a consistent interface.
    
    This class maintains backward compatibility with existing PRAW Submission usage
    while providing a consistent interface for different data adapter implementations.
    """

    def __init__(self, adapter_type:PostDownloadSource, dict_data:dict):
        """
        Initialize the Submission adapter.
        
        Args:
            submission: The PRAW Submission object to wrap
        """
        super().__init__(adapter_type)
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

    def from_arctic_shift(self, dict_data:dict):
        setattr(self, TITLE_KEY, dig(dict_data, TITLE_KEY, default=""))
        setattr(self, URL_KEY, dig(dict_data, URL_KEY, default=""))
        setattr(self, ID_KEY, dig(dict_data, ID_KEY, default=""))
        setattr(self, DOMAIN_KEY, dig(dict_data, DOMAIN_KEY, default=""))
        setattr(self, SCORE_KEY, dig(dict_data, SCORE_KEY, default=0))
        setattr(self, PINNED_KEY, bool(dig(PINNED_KEY, PINNED_KEY, default=False)))
        setattr(self, STICKIED_KEY, bool(dig(STICKIED_KEY, STICKIED_KEY, default=False)))
        setattr(self, OVER_18_KEY, bool(dig(dict_data, OVER_18_KEY, default=False)))
        setattr(self, IS_SELF_KEY, bool(dig(dict_data, IS_SELF_KEY, default=False)))
        setattr(self, SELFTEXT_KEY, dig(dict_data, SELFTEXT_KEY, default=""))
        setattr(self, SELFTEXT_HTML_KEY, dig(dict_data, SELFTEXT_HTML_KEY, default=""))
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
