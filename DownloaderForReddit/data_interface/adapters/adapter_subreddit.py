"""
PRAW Subreddit adapter for the Reddit Data Interface.

This module wraps PRAW Subreddit functionality to match the abstract AdapterData interface.
"""



from DownloaderForReddit.data_interface.adapter_data import CREATED_KEY
from DownloaderForReddit.data_interface.adapter_data import CREATED_UTC_KEY, DISPLAY_NAME_KEY, FULLNAME_KEY, AdapterData
from DownloaderForReddit.database.model_enums import PostDownloadSource


class AdapterSubreddit(AdapterData):
    """
    Adapter that wraps PRAW Subreddit to provide a consistent interface.
    
    This class maintains backward compatibility with existing PRAW Subreddit usage
    while providing a consistent interface for different data adapter implementations.
    """

    def __init__(self, adapter_type:PostDownloadSource, data:dict):
        """
        Initialize the Subreddit adapter.
        
        Args:
            subreddit: The PRAW Subreddit object to wrap
        """
        super().__init__(adapter_type)
        self._supported_keys = [CREATED_KEY, CREATED_UTC_KEY, DISPLAY_NAME_KEY, FULLNAME_KEY]
