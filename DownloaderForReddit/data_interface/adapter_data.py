"""
Abstract base class for PRAW data adapter implementations.

This module defines the interface that all PRAW data adapter implementations must follow.
It allows for different PRAW model objects to be used interchangeably.
"""

from abc import ABC
import logging
from typing import Any, Optional
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
AUTHOR_NAME_KEY = "author_name"
SUBREDDIT_NAME_KEY = "subreddit_name"


class AdapterData(ABC):
    """
    Abstract base class for PRAW data adapters.
    
    All concrete implementations must inherit from this class and implement
    all abstract methods to provide a consistent interface for PRAW model operations.
    """

    def __init__(self, adapter_type:PostDownloadSource):
        """Initialize the adapter with data."""
        self._adapter_type:PostDownloadSource = adapter_type
        self._supported_keys = []
        self.logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

    def __getattr__(self, attr):
        if attr == "__iter__":
            return None
        self.logger.error("Invoked the fallback method in '%s' for missing: %s", self.__class__.__name__, attr)
        return None

    def _get(self, key:str, default=None) -> Optional[Any]:
        self._asserted_expected_attribute(key)
        return getattr(self, key, default)

    def _set(self, key:str, value:Any):
        self._asserted_expected_attribute(key)
        setattr(self, key, value)

    def _asserted_expected_attribute(self, key:str):
        if key not in self._supported_keys:
            raise AttributeError(f"Unexepected key for child class ({self.__class__.__name__}): {key}")

    def id(self) -> str:
        """
        Get the unique identifier of the PRAW object.
        
        Returns:
            The unique ID of the PRAW object
        """
        return self._get(ID_KEY, default="")

    def fullname(self) -> str:
        """
        Get the fullname of the PRAW object.
        
        Returns:
            The fullname of the PRAW object
        """
        return self._get(FULLNAME_KEY, default="")

    def name(self) -> Optional[str]:
        """
        Get the name of the PRAW object.
        
        Returns:
            The name of the PRAW object or None if not applicable
        """
        return self._get(NAME_KEY)

    def created_utc(self) -> Optional[float]:
        """
        Get the creation timestamp of the PRAW object.
        
        Returns:
            The creation timestamp or None if not applicable
        """
        return self._get(CREATED_UTC_KEY)

    def created(self) -> Optional[float]:
        """
        Get the creation timestamp of the PRAW object.
        
        Returns:
            The creation timestamp or None if not applicable
        """
        return self._get(CREATED_KEY)

    def display_name(self) -> Optional[str]:
        """
        Get the display name of the PRAW object.
        
        Returns:
            The display name of the PRAW object or None if not applicable
        """
        return self._get(DISPLAY_NAME_KEY)

    def score(self) -> Optional[int]:
        """
        Get the score of the PRAW object.
        
        Returns:
            The score of the PRAW object or None if not applicable
        """
        return self._get(SCORE_KEY)

    def title(self) -> Optional[str]:
        """
        Get the title of the PRAW object.
        
        Returns:
            The title of the PRAW object or None if not applicable
        """
        return self._get(TITLE_KEY)

    def url(self) -> Optional[str]:
        """
        Get the URL of the PRAW object.
        
        Returns:
            The URL of the PRAW object or None if not applicable
        """
        return self._get(URL_KEY)

    def domain(self) -> Optional[str]:
        """
        Get the domain of the PRAW object.
        
        Returns:
            The domain of the PRAW object or None if not applicable
        """
        return self._get(DOMAIN_KEY)

    def over_18(self) -> bool:
        """
        Check if the PRAW object is NSFW.
        
        Returns:
            True if the object is NSFW, False otherwise
        """
        return bool(dig(self._data, OVER_18_KEY, default=False))

    def is_self(self) -> bool:
        """
        Check if the PRAW object is a self-post.
        
        Returns:
            True if the object is a self-post, False otherwise
        """
        return bool(dig(self._data, IS_SELF_KEY, default=False))

    def selftext(self) -> Optional[str]:
        """
        Get the self-text content of the PRAW object.
        
        Returns:
            The self-text content or None if not applicable
        """
        return self._get(SELFTEXT_KEY)

    def selftext_html(self) -> Optional[str]:
        """
        Get the HTML version of self-text content.
        
        Returns:
            The HTML self-text content or None if not applicable
        """
        return self._get(SELFTEXT_HTML_KEY)

    def body(self) -> Optional[str]:
        """
        Get the body content of the PRAW object.
        
        Returns:
            The body content or None if not applicable
        """
        return self._get(BODY_KEY)

    def body_html(self) -> Optional[str]:
        """
        Get the HTML version of body content.
        
        Returns:
            The HTML body content or None if not applicable
        """
        return self._get(BODY_HTML_KEY)

    def author_name(self) -> Optional[str]:
        """
        Get the author name of the PRAW object.
        
        Returns:
            The author name or None if not applicable
        """
        return self._get(AUTHOR_NAME_KEY)

    def subreddit_name(self) -> Optional[str]:
        """
        Get the subreddit name of the PRAW object.
        
        Returns:
            The subreddit name or None if not applicable
        """
        return self._get(SUBREDDIT_NAME_KEY)

    def set_id(self, value:str):
        """
        Set the unique identifier of the PRAW object.
        
        """
        return self._set(ID_KEY, value=value)

    def set_fullname(self, value:str):
        """
        Set the fullname of the PRAW object.
        
        """
        self._set(FULLNAME_KEY, value=value)

    def set_name(self, value:str):
        """
        Set the name of the PRAW object.
        
        """
        self._set(NAME_KEY, value=value)

    def set_created_utc(self, value:float):
        """
        Set the creation timestamp of the PRAW object.
        
        """
        self._set(CREATED_UTC_KEY, value=value)

    def set_created(self, value:float):
        """
        Set the creation timestamp of the PRAW object.
        
        """
        self._set(CREATED_KEY, value=value)

    def set_display_name(self, value:str):
        """
        Set the display name of the PRAW object.
        
        """
        self._set(DISPLAY_NAME_KEY, value=value)

    def set_score(self, value) -> Optional[int]:
        """
        Set the score of the PRAW object.
        
        """
        self._set(SCORE_KEY, value=value)

    def set_title(self, value:str):
        """
        Set the title of the PRAW object.
        
        """
        self._set(TITLE_KEY, value=value)

    def set_url(self, value:str):
        """
        Set the URL of the PRAW object.
        
        """
        self._set(URL_KEY, value=value)

    def set_domain(self, value:str):
        """
        Set the domain of the PRAW object.
        
        """
        self._set(DOMAIN_KEY, value=value)

    def set_over_18(self, value:Any):
        """
        Check if the PRAW object is NSFW.
        
        """
        if value:
            self._set(OVER_18_KEY, value=True)
        else:
            self._set(OVER_18_KEY, value=False)

    def set_is_self(self, value:Any):
        """
        Check if the PRAW object is a self-post.
        
        """
        if value:
            self._set(IS_SELF_KEY, value=True)
        else:
            self._set(IS_SELF_KEY, value=False)

    def set_selftext(self, value:str):
        """
        Set the self-text content of the PRAW object.
        
        """
        self._set(SELFTEXT_KEY, value=value)

    def set_selftext_html(self, value:str):
        """
        Set the HTML version of self-text content.
        
        """
        self._set(SELFTEXT_HTML_KEY, value=value)

    def set_body(self, value:str):
        """
        Set the body content of the PRAW object.
        
        """
        self._set(BODY_KEY, value=value)

    def set_body_html(self, value:str):
        """
        Set the HTML version of body content.
        
        """
        self._set(BODY_HTML_KEY, value=value)

    def set_author_name(self, value:str):
        """
        Set the author name of the PRAW object.
        
        """
        self._set(AUTHOR_NAME_KEY, value=value)

    def set_subreddit_name(self, value:str):
        """
        Set the subreddit name of the PRAW object.
        
        """
        self._set(SUBREDDIT_NAME_KEY, value=value)
