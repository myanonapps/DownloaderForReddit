"""
Filter settings class for managing date and other filter configurations.

This module contains the FilterSettings class that holds all the configuration
settings related to filtering posts and comments by date and other criteria.
"""

from datetime import datetime
from typing import Optional


class FilterSettings:
    """
    Class containing all filter settings for user, post, and comment configurations.
    
    This class manages various filter settings that can be applied when downloading
    Reddit content. It includes both date-based filters and other criteria such as
    score limits, NSFW filtering, etc.
    """

    def __init__(self):
        """Initialize the FilterSettings with default values."""
        # Date limit settings for posts
        self.post_date_limit: Optional[datetime] = None
        self.post_date_limit_enabled: bool = False

        # Date limit settings for comments
        self.comment_date_limit: Optional[datetime] = None
        self.comment_date_limit_enabled: bool = False

        # Date limit settings for users
        self.user_date_limit: Optional[datetime] = None
        self.user_date_limit_enabled: bool = False

        # Score limit settings for posts
        self.post_score_limit: int = 1000
        self.post_score_limit_operator: str = 'GREATER_THAN'

        # NSFW filter settings
        self.nsfw_filter: str = 'INCLUDE'  # INCLUDE, EXCLUDE, ONLY

        # Duplicate control settings
        self.avoid_duplicates: bool = True
        self.hash_duplicates: bool = False

        # Sorting and limit settings
        self.post_limit: int = 25
        self.post_sort_method: str = 'NEW'

        # Download source settings
        self.post_download_source: str = 'REDDIT'

        # Additional filtering flags
        self.filter_subreddits: bool = False

    def set_post_date_limit(self, date_limit: datetime):
        """Set the post date limit."""
        self.post_date_limit = date_limit
        self.post_date_limit_enabled = True

    def set_comment_date_limit(self, date_limit: datetime):
        """Set the comment date limit."""
        self.comment_date_limit = date_limit
        self.comment_date_limit_enabled = True

    def set_user_date_limit(self, date_limit: datetime):
        """Set the user date limit."""
        self.user_date_limit = date_limit
        self.user_date_limit_enabled = True

    def clear_post_date_limit(self):
        """Clear the post date limit."""
        self.post_date_limit = None
        self.post_date_limit_enabled = False

    def clear_comment_date_limit(self):
        """Clear the comment date limit."""
        self.comment_date_limit = None
        self.comment_date_limit_enabled = False

    def clear_user_date_limit(self):
        """Clear the user date limit."""
        self.user_date_limit = None
        self.user_date_limit_enabled = False

    def get_post_date_limit(self) -> Optional[datetime]:
        """Get the post date limit."""
        return self.post_date_limit if self.post_date_limit_enabled else None

    def get_comment_date_limit(self) -> Optional[datetime]:
        """Get the comment date limit."""
        return self.comment_date_limit if self.comment_date_limit_enabled else None

    def get_user_date_limit(self) -> Optional[datetime]:
        """Get the user date limit."""
        return self.user_date_limit if self.user_date_limit_enabled else None
