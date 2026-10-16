"""
PRAW Redditor adapter for the Reddit Data Interface.

This module wraps PRAW Redditor functionality to match the abstract AdapterData interface.
"""

from DownloaderForReddit.data_interface.adapter_data import CREATED_KEY
from data_interface.adapter_data import CREATED_UTC_KEY, FULLNAME_KEY, NAME_KEY, AdapterData


class AdapterRedditor(AdapterData):
    """
    Adapter that wraps PRAW Redditor to provide a consistent interface.
    
    This class maintains backward compatibility with existing PRAW Redditor usage
    while providing a consistent interface for different data adapter implementations.
    """

    def __init__(self, data:dict):
        """
        Initialize the Redditor adapter.
        
        Args:
            redditor: The PRAW Redditor object to wrap
        """
        super().__init__(data)
        self._supported_keys = [NAME_KEY, CREATED_UTC_KEY, CREATED_KEY, FULLNAME_KEY]

    @staticmethod
    def from_arctic_shift(data:dict) -> AdapterRedditor:
        '''
        {
            "_meta": {
                "comment_karma": "None",
                "comment_stats_updated_at": "None",
                "earliest_comment_at": "None",
                "earliest_post_at": 1747697079,
                "last_comment_at": "None",
                "last_post_at": 1755884070,
                "num_comments": "None",
                "num_posts": 117,
                "post_karma": 7970,
                "post_stats_updated_at": 1756166402,
                "total_karma": 7970
            },
            "author": "Name",
            "id": "1ppe7c12h2"
            }
        '''        
