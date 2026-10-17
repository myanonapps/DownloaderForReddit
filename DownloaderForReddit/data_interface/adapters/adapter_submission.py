"""
PRAW Submission adapter for the Reddit Data Interface.

This module wraps PRAW Submission functionality to match the abstract AdapterData interface.
"""
from DownloaderForReddit.data_interface.adapter_data import CREATED_KEY
from DownloaderForReddit.data_interface.adapter_data import AUTHOR_NAME_KEY, CREATED_UTC_KEY, DOMAIN_KEY, FULLNAME_KEY, ID_KEY, IS_SELF_KEY, OVER_18_KEY,\
    SCORE_KEY, SELFTEXT_HTML_KEY, SELFTEXT_KEY, SUBREDDIT_NAME_KEY, TITLE_KEY, URL_KEY, AdapterData
from DownloaderForReddit.database.model_enums import PostDownloadSource
from DownloaderForReddit.utils.general_utils import dig


class AdapterSubmission(AdapterData):
    """
    Adapter that wraps PRAW Submission to provide a consistent interface.
    
    This class maintains backward compatibility with existing PRAW Submission usage
    while providing a consistent interface for different data adapter implementations.
    """

    def __init__(self, adapter_type:PostDownloadSource, data:dict):
        """
        Initialize the Submission adapter.
        
        Args:
            submission: The PRAW Submission object to wrap
        """
        super().__init__(adapter_type)
        self._supported_keys = [TITLE_KEY, URL_KEY, ID_KEY, DOMAIN_KEY, SCORE_KEY, OVER_18_KEY, IS_SELF_KEY, SELFTEXT_KEY, SELFTEXT_HTML_KEY, CREATED_UTC_KEY, CREATED_KEY, AUTHOR_NAME_KEY, SUBREDDIT_NAME_KEY, FULLNAME_KEY]
        match adapter_type:
            case PostDownloadSource.ARCTIC_SHIFT:
                self.from_arctic_shift(dict)
            case PostDownloadSource.PULL_PUSH:
                self.from_pull_push(dict)
            case PostDownloadSource.REDDIT:
                pass


    def from_arctic_shift(self, data:dict):
        setattr(self, TITLE_KEY, dig(data, TITLE_KEY, default=""))
        setattr(self, URL_KEY, dig(data, URL_KEY, default=""))
        setattr(self, ID_KEY, dig(data, ID_KEY, default=""))
        setattr(self, DOMAIN_KEY, dig(data, DOMAIN_KEY, default=""))
        setattr(self, SCORE_KEY, dig(data, SCORE_KEY, default=0))
        setattr(self, OVER_18_KEY, bool(dig(self._data, OVER_18_KEY, default=False)))
        setattr(self, IS_SELF_KEY, bool(dig(self._data, IS_SELF_KEY, default=False)))
        setattr(self, SELFTEXT_KEY, dig(data, SELFTEXT_KEY, default=""))
        setattr(self, SELFTEXT_HTML_KEY, dig(data, SELFTEXT_HTML_KEY, default=""))
        setattr(self, AUTHOR_NAME_KEY, dig(data, "author", default=""))
        setattr(self, FULLNAME_KEY, dig(data, "author_fullname", default=""))
        setattr(self, SUBREDDIT_NAME_KEY, dig(data, "subreddit", default=""))
        setattr(self, CREATED_KEY, dig(data, CREATED_KEY, default=0))
        setattr(self, CREATED_UTC_KEY, dig(data, CREATED_UTC_KEY, default=0))
