"""
PRAW Subreddit adapter for the Reddit Data Interface.

This module wraps PRAW Subreddit functionality to match the abstract AdapterData interface.
"""


from DownloaderForReddit.data_interface.adapter_data import AdapterData
from DownloaderForReddit.database.model_enums import PostDownloadSource


class AdapterSubreddit(AdapterData):
    """
    Adapter that wraps PRAW Subreddit to provide a consistent interface.
    
    This class maintains backward compatibility with existing PRAW Subreddit usage
    while providing a consistent interface for different data adapter implementations.
    """

    def __init__(self, adapter_type:PostDownloadSource, dict_data:dict):
        """
        Initialize the Subreddit adapter.
        
        Args:
            subreddit: The PRAW Subreddit object to wrap
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

    def from_pull_push(self, dict_data:dict):
        pass

    def from_arctic_shift(self, dict_data:dict):
        '''
        {
            "_meta": {
                "comment_karma": None,
                "comment_stats_updated_at": None,
                "earliest_comment_at": None,
                "earliest_post_at": 1747697079,
                "last_comment_at": None,
                "last_post_at": 1755884070,
                "num_comments": None,
                "num_posts": 117,
                "post_karma": 7970,
                "post_stats_updated_at": 1756166402,
                "total_karma": 7970
            },
            "author": "Name",
            "id": "1ppe7c12h2"
            }
        '''
