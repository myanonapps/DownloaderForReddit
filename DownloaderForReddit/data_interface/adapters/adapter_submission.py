"""
PRAW Submission adapter for the Reddit Data Interface.

This module wraps PRAW Submission functionality to match the abstract AdapterData interface.
"""
from DownloaderForReddit.data_interface.adapter_data import CREATED_KEY
from data_interface.adapter_data import AUTHOR_NAME_KEY, CREATED_UTC_KEY, DOMAIN_KEY, FULLNAME_KEY, ID_KEY, IS_SELF_KEY, OVER_18_KEY,\
    SCORE_KEY, SELFTTEXT_HTML_KEY, SELFTTEXT_KEY, SUBREDDIT_NAME_KEY, TITLE_KEY, URL_KEY, AdapterData


class AdapterSubmission(AdapterData):
    """
    Adapter that wraps PRAW Submission to provide a consistent interface.
    
    This class maintains backward compatibility with existing PRAW Submission usage
    while providing a consistent interface for different data adapter implementations.
    """

    def __init__(self, data:dict):
        """
        Initialize the Submission adapter.
        
        Args:
            submission: The PRAW Submission object to wrap
        """
        super().__init__(data)
        self._supported_keys = [TITLE_KEY, URL_KEY, ID_KEY, DOMAIN_KEY, SCORE_KEY, OVER_18_KEY, IS_SELF_KEY, SELFTTEXT_KEY, SELFTTEXT_HTML_KEY, CREATED_UTC_KEY, CREATED_KEY, AUTHOR_NAME_KEY, SUBREDDIT_NAME_KEY, FULLNAME_KEY]
