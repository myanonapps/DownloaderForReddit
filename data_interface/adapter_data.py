"""
Abstract base class for PRAW data adapter implementations.

This module defines the interface that all PRAW data adapter implementations must follow.
It allows for different PRAW model objects to be used interchangeably.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from DownloaderForReddit.utils.general_utils import dig


# Constants for data keys
ID_KEY = "id"
FULLNAME_KEY = "fullname"
NAME_KEY = "name"
CREATED_UTC_KEY = "created_utc"
DISPLAY_NAME_KEY = "display_name"
SCORE_KEY = "score"
TITLE_KEY = "title"
URL_KEY = "url"
DOMAIN_KEY = "domain"
OVER_18_KEY = "over_18"
IS_SELF_KEY = "is_self"
SELFTTEXT_KEY = "selftext"
SELFTTEXT_HTML_KEY = "selftext_html"
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
    
    def __init__(self, data: Optional[dict] = None):
        """Initialize the adapter with data."""
        self._data = data or {}
    
    def get_id(self) -> str:
        """
        Get the unique identifier of the PRAW object.
        
        Returns:
            The unique ID of the PRAW object
        """
        return dig(self._data, ID_KEY, default="")
    
    def get_fullname(self) -> str:
        """
        Get the fullname of the PRAW object.
        
        Returns:
            The fullname of the PRAW object
        """
        return dig(self._data, FULLNAME_KEY, default="")
    
    def get_name(self) -> Optional[str]:
        """
        Get the name of the PRAW object.
        
        Returns:
            The name of the PRAW object or None if not applicable
        """
        return dig(self._data, NAME_KEY)
    
    def get_created_utc(self) -> Optional[float]:
        """
        Get the creation timestamp of the PRAW object.
        
        Returns:
            The creation timestamp or None if not applicable
        """
        return dig(self._data, CREATED_UTC_KEY)
    
    def get_display_name(self) -> Optional[str]:
        """
        Get the display name of the PRAW object.
        
        Returns:
            The display name of the PRAW object or None if not applicable
        """
        return dig(self._data, DISPLAY_NAME_KEY)
    
    def get_score(self) -> Optional[int]:
        """
        Get the score of the PRAW object.
        
        Returns:
            The score of the PRAW object or None if not applicable
        """
        return dig(self._data, SCORE_KEY)
    
    def get_title(self) -> Optional[str]:
        """
        Get the title of the PRAW object.
        
        Returns:
            The title of the PRAW object or None if not applicable
        """
        return dig(self._data, TITLE_KEY)
    
    def get_url(self) -> Optional[str]:
        """
        Get the URL of the PRAW object.
        
        Returns:
            The URL of the PRAW object or None if not applicable
        """
        return dig(self._data, URL_KEY)
    
    def get_domain(self) -> Optional[str]:
        """
        Get the domain of the PRAW object.
        
        Returns:
            The domain of the PRAW object or None if not applicable
        """
        return dig(self._data, DOMAIN_KEY)
    
    def get_over_18(self) -> bool:
        """
        Check if the PRAW object is NSFW.
        
        Returns:
            True if the object is NSFW, False otherwise
        """
        return bool(dig(self._data, OVER_18_KEY, default=False))
    
    def get_is_self(self) -> bool:
        """
        Check if the PRAW object is a self-post.
        
        Returns:
            True if the object is a self-post, False otherwise
        """
        return bool(dig(self._data, IS_SELF_KEY, default=False))
    
    def get_selftext(self) -> Optional[str]:
        """
        Get the self-text content of the PRAW object.
        
        Returns:
            The self-text content or None if not applicable
        """
        return dig(self._data, SELFTTEXT_KEY)
    
    def get_selftext_html(self) -> Optional[str]:
        """
        Get the HTML version of self-text content.
        
        Returns:
            The HTML self-text content or None if not applicable
        """
        return dig(self._data, SELFTTEXT_HTML_KEY)
    
    def get_body(self) -> Optional[str]:
        """
        Get the body content of the PRAW object.
        
        Returns:
            The body content or None if not applicable
        """
        return dig(self._data, BODY_KEY)
    
    def get_body_html(self) -> Optional[str]:
        """
        Get the HTML version of body content.
        
        Returns:
            The HTML body content or None if not applicable
        """
        return dig(self._data, BODY_HTML_KEY)
    
    def get_author_name(self) -> Optional[str]:
        """
        Get the author name of the PRAW object.
        
        Returns:
            The author name or None if not applicable
        """
        return dig(self._data, AUTHOR_NAME_KEY)
    
    def get_subreddit_name(self) -> Optional[str]:
        """
        Get the subreddit name of the PRAW object.
        
        Returns:
            The subreddit name or None if not applicable
        """
        return dig(self._data, SUBREDDIT_NAME_KEY)