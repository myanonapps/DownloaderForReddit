"""
PRAW Redditor adapter for the Reddit Data Interface.

This module wraps PRAW Redditor functionality to match the abstract AdapterData interface.
"""
from datetime import datetime, timezone

from DownloaderForReddit.database.model_enums import PostDownloadSource
from DownloaderForReddit.utils.general_utils import dig
from DownloaderForReddit.data_interface.adapter_data import CREATED_KEY, ID_KEY
from DownloaderForReddit.data_interface.adapter_data import CREATED_UTC_KEY, FULLNAME_KEY, NAME_KEY, AdapterData


class AdapterRedditor(AdapterData):
    """
    Adapter that wraps PRAW Redditor to provide a consistent interface.
    
    This class maintains backward compatibility with existing PRAW Redditor usage
    while providing a consistent interface for different data adapter implementations.
    """

    def __init__(self, adapter_type:PostDownloadSource, data:dict):
        """
        Initialize the Redditor adapter.
        
        Args:
            redditor: The PRAW Redditor object to wrap
        """
        super().__init__(adapter_type)
        self._supported_keys = [ID_KEY, NAME_KEY, CREATED_UTC_KEY, CREATED_KEY, FULLNAME_KEY]
        match adapter_type:
            case PostDownloadSource.ARCTIC_SHIFT:
                self.from_arctic_shift(dict)
            case PostDownloadSource.PULL_PUSH:
                self.from_pull_push(dict)
            case PostDownloadSource.REDDIT:
                pass

    def __getattr__(self, attr):
        if attr == "__iter__":
            return None
        self.logger.error("Invoked the fallback method in '%s' for missing: %s", self.__class__.__name__, attr)
        return None

    def from_pull_push(self, data:dict):
        pass

    def from_arctic_shift(self, data:dict):
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
        setattr(self, NAME_KEY, dig(data, "author", default=""))
        setattr(self, FULLNAME_KEY, dig(data, "author", default=""))
        setattr(self, ID_KEY, dig(data, "id", default=""))
        maximum = datetime.max.replace(tzinfo=timezone.utc).timestamp()
        earliest = min(dig(data, "_meta", "earliest_comment_at", default=maximum), dig(data, "_meta", "earliest_post_at", default=maximum))
        if earliest == maximum:
            earliest = 0
        setattr(self, CREATED_KEY, earliest)
        setattr(self, CREATED_UTC_KEY, earliest)
