"""
Package for Reddit Data Interface interfaces.

This module exports all the main components of the data interface package.
"""

from .adapter_manager import RedditAdapterManager
from .reddit_data_interface import RedditDataInterface
from .adapters.praw_adapter import PRAWAdapter
from .adapters.arctic_shift_adapter import ArcticShiftAdapter
from .adapters.pull_push_adapter import PullPushAdapter
from .adapter_data import AdapterData
from .adapters.adapter_submission import AdapterSubmission
from .adapters.adapter_redditor import AdapterRedditor
from .adapters.adapter_subreddit import AdapterSubreddit

__all__ = [
    'RedditAdapterManager',
    'RedditDataInterface', 
    'PRAWAdapter',
    'ArcticShiftAdapter',
    'PullPushAdapter',
    'AdapterData',
    'AdapterSubmission',
    'AdapterRedditor',
    'AdapterSubreddit'
]