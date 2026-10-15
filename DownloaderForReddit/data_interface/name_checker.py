from DownloaderForReddit.data_interface.adapter_manager import RedditAdapterManager
from DownloaderForReddit.data_interface.reddit_data_interface import ValidationSet
from DownloaderForReddit.database.model_enums import PostDownloadSource

class NameChecker:

    """
    This class is to check for the existence of a reddit object name using praw, then report back whether the name
    exists or not.  This class is intended to be ran in a separate thread.
    """

    def __init__(self, source:PostDownloadSource, object_type:str):
        """
        Initializes the NameChecker and establishes its operation setup regarding whether to target users or subreddits.
        :param object_type: The type of reddit object (USER or SUBREDDIT) that the supplied names will be.
        :type object_type: str, None
        """
        super().__init__()
        self._source = source
        self._object_type = object_type

    def check_reddit_object_name(self, name:str) -> ValidationSet:
        manager = RedditAdapterManager()
        adapter = manager.get_adapter(self._source)
        if self._object_type == 'USER':
            return adapter.check_user_name(name)
        elif self._object_type == 'SUBREDDIT':
            return adapter.check_subreddit_name(name)
        return ValidationSet(name=name, date_created=None, valid=False)

    def check_user_name(self, name:str) -> ValidationSet:
        self._object_type = 'USER'
        return self.check_reddit_object_name(name)

    def check_subreddit_name(self, name:str) -> ValidationSet:
        self._object_type = 'SUBREDDIT'
        return self.check_reddit_object_name(name)
