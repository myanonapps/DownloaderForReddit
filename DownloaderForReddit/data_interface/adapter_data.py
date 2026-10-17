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


class AdapterData(ABC):
    """
    Abstract base class for PRAW data adapters.
    
    All concrete implementations must inherit from this class and implement
    all abstract methods to provide a consistent interface for PRAW model operations.
    """

    def __init__(self, adapter_type:PostDownloadSource):
        """Initialize the adapter with data."""
        self._adapter_type:PostDownloadSource = adapter_type
        self.logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

    def __getattr__(self, attr):
        if attr == "__iter__":
            return None
        self.logger.error("Invoked the fallback method in '%s' for missing: %s", self.__class__.__name__, attr)
        return None

    def _get(self, key:str, default=None) -> Optional[Any]:
        return getattr(self, key, default)

    def _set(self, key:str, value:Any):
        setattr(self, key, value)
