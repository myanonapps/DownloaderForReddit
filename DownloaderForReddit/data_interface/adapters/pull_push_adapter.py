"""
Pull Push HTTP adapter for the Reddit Data Interface interface.

This module provides an HTTP-based implementation of the RedditAPI interface 
that uses Pull Push's HTTP API instead of PRAW.
"""
from typing import Any

from DownloaderForReddit.data_interface.adapters.adapter_redditor import AdapterRedditor
from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.data_interface.reddit_data_interface import RedditDataInterface


BASE_URL = "https://api.pullpush.io/"
class PullPushAdapter(RedditDataInterface):
    """
    Adapter that wraps Pull Push HTTP API to provide the RedditAPI interface.
    
    This class implements the RedditAPI interface using Pull Push's HTTP API
    which provides access to Reddit data through an HTTP endpoint.
    """

    def __init__(self, token:RedditAdapterToken, download_session=None):
        """
        Initialize the Pull Push adapter.
        
        Args:
            api_key: The API key for authenticating with Pull Push
            base_url: The base URL of the Pull Push API (default: https://api.pullpush.io/)
        """
        super().__init__(BASE_URL, token, download_session)

    def posts_by_author(self):
        pass

    def submission(self, id: str) -> Any:
        """
        Get a submission by its ID.
        
        Args:
            id: The Reddit submission ID
            
        Returns:
            Submission object from the Pull Push API
        """
        # Pull Push API endpoint for submissions (using search with ID)
        endpoint = "/search"
        params = {
            "id": id,
            "size": 1
        }
        data = self.make_http_request(endpoint, params)
        # Return the first result if available
        return data.get('hits', [{}])[0] if data.get('hits') else {}

    def redditor(self, name: str) -> AdapterRedditor:
        """
        Get a redditor (user) by name.
        
        Args:
            name: The Reddit username
            
        Returns:
            Redditor object from the Pull Push API
        """
        pass

    def redditor_by_id(self, user_id: str) -> AdapterRedditor:
        """
        Get a redditor (user) by id.
        
        Args:
            name: The Reddit username
            
        Returns:
            Redditor object from the Pull Push API
        """
        pass

    def subreddit(self, name: str) -> Any:
        """
        Get a subreddit by name.
        
        Args:
            name: The subreddit name
            
        Returns:
            Subreddit object from the Pull Push API
        """
        # Pull Push API endpoint for subreddits (using search)
        endpoint = "/search"
        params = {
            "subreddit": name,
            "size": 1
        }
        data = self.make_http_request(endpoint, params)
        # Return the first result if available
        return data.get('hits', [{}])[0] if data.get('hits') else {}

    def get_authenticated_user(self) -> str:
        return ""
