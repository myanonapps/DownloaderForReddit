"""
Base abstract class for Reddit Data Interface implementations.

This module defines the interface that all Reddit Data Interface implementations must follow.
It allows for different backends (PRAW, HTTP APIs, etc.) to be used interchangeably.
"""

from abc import ABC, abstractmethod
from collections import namedtuple
from typing import Any, Optional
from urllib.parse import urljoin
import requests

from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.database.models import RedditObject
from DownloaderForReddit.utils import system_util
from ..version import __version__

ValidationSet = namedtuple('ValidationSet', 'name date_created valid')

REDIRECT_URL = 'http://127.0.0.1:8086/'
USER_AGENT = (
    f'{system_util.get_platform_str()}:DownloaderForReddit:{__version__} '
    f'(by /u/MalloyDelacroix; contact: downloaderforreddit@gmail.com)'
)

class RedditDataInterface(ABC):
    """
    Abstract base class for Reddit Data Interface implementations.
    
    All concrete implementations must inherit from this class and implement
    all abstract methods to provide a consistent interface for Reddit operations.
    """
    def __init__(self, base_url:str, token: RedditAdapterToken):
        self._base_url:str = base_url
        self._redirect_url:str = REDIRECT_URL
        self._user_agent:str = USER_AGENT
        self._session = None
        self._token = token
        self._reddit_object = None

    @abstractmethod
    def check_user_name(self, name):
        pass

    @abstractmethod
    def check_subreddit_name(self, name):
        pass

    @abstractmethod
    def get_authenticated_user(self) -> str:
        """
        Gets authenticated user name.

        """
        pass

    @abstractmethod
    def submission(self, id: str) -> Any:
        """
        Get a submission by its ID.
        
        Args:
            id: The Reddit submission ID
            
        Returns:
            Submission object from the Reddit Data Interface
        """
        pass

    @abstractmethod
    def redditor(self, name: str) -> Any:
        """
        Get a redditor (user) by name.
        
        Args:
            name: The Reddit username
            
        Returns:
            Redditor object from the Reddit Data Interface
        """
        pass

    @abstractmethod
    def subreddit(self, name: str) -> Any:
        """
        Get a subreddit by name.
        
        Args:
            name: The subreddit name
            
        Returns:
            Subreddit object from the Reddit Data Interface
        """
        pass

    def get_user_agent(self) -> str:
        """
        Get the user agent string for the Reddit Data Interface.
        
        Returns:
            User agent string
        """
        return self._user_agent

    def get_redirect_url(self) -> str:
        """
        Get the redirect url for the Reddit Data Interface.
        
        Returns:
            url string
        """
        return self._redirect_url

    def make_http_request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """
        Make a request to the Reddit Data Interface.

        Args:
            endpoint: The API endpoint to call
            params: Optional parameters for the request
            
        Returns:
            JSON response from the API
        """
        try:
            if self._session is None:
                self._session = requests.Session()
            if self._token.get_decrypted():
                self._session.headers.update({
                    'Authorization': f'Bearer {self._token.get_decrypted()}',
                    'User-Agent': self.get_user_agent()
                })
            response = self._session.get(urljoin(self._base_url, endpoint), params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception("Reddit Data Interface HTTP request failed") from e

    def set_reddit_object(self, reddit_object:RedditObject):
        self._reddit_object = reddit_object

    def get_reddit_object(self) -> RedditObject:
        return self._reddit_object