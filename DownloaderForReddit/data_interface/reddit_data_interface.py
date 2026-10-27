"""
Base abstract class for Reddit Data Interface implementations.

This module defines the interface that all Reddit Data Interface implementations must follow.
It allows for different backends (PRAW, HTTP APIs, etc.) to be used interchangeably.
"""

from abc import ABC, abstractmethod
from collections import namedtuple
from datetime import datetime, timezone
from http import HTTPStatus
import logging
import time
from typing import Any, Optional
from urllib.parse import urljoin
from email.utils import parsedate_to_datetime
import requests
from PyQt6.QtCore import QUrl

from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.database.models import DownloadSession, RedditObject
from DownloaderForReddit.messaging.message import Message
from DownloaderForReddit.utils import system_util
from ..version import __version__

ValidationSet = namedtuple('ValidationSet', 'name date_created valid reddit_id')

REDIRECT_URL = 'http://127.0.0.1:8086/'
USER_AGENT = (
    f'{system_util.get_platform_str()}:DownloaderForReddit:{__version__} '
    f'(by /u/MalloyDelacroix; contact: downloaderforreddit@gmail.com)'
)
DEFAULT_WAIT_S=10
DEFAULT_RETRIES=20

class RedditDataInterface(ABC):
    """
    Abstract base class for Reddit Data Interface implementations.
    
    All concrete implementations must inherit from this class and implement
    all abstract methods to provide a consistent interface for Reddit operations.
    """
    def __init__(self, base_url:str, token: RedditAdapterToken, download_session=None):
        self._base_url:str = base_url
        self._authorization_url = QUrl("")
        self._access_url = QUrl("")
        self._redirect_url:str = REDIRECT_URL
        self._user_agent:str = USER_AGENT
        self._http_session = None
        self._token = token
        self._reddit_object = None
        self.logger = logging.getLogger(f'DownloaderForReddit.{__name__}')
        self._download_session:DownloadSession = download_session

    def get_authorization_url(self) -> QUrl:
        return self._authorization_url

    def get_access_url(self) -> QUrl:
        return self._access_url

    def increment_rate_limit_count(self):
        """Increment the rate limit count in the download session."""
        if self._download_session is not None:
            try:
                # Increment rate limit counter (assuming it's a SQLAlchemy model with rate_limit_count attribute)
                self._download_session.rate_limit_count = self._download_session.rate_limit_count + 1
                self._download_session.save()
            except Exception as e:
                self.logger.error("Failed to increment rate limit count: %s", str(e))

    def add_rate_limit_duration(self, duration):
        """Add duration of rate limiting to the download session."""
        if self._download_session is not None:
            try:
                # Add to rate limit duration (assuming it's a SQLAlchemy model with rate_limit_duration attribute)
                self._download_session.rate_limit_duration = self._download_session.rate_limit_duration + duration
                self._download_session.save()
            except Exception as e:
                self.logger.error("Failed to add rate limit duration: %s", str(e))

    @abstractmethod
    def posts_by_author(self):
        pass

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
    def redditor_by_id(self, user_id: str) -> Any:
        """
        Get a redditor (user) by id.
        
        Args:
            name: The Reddit username
            
        Returns:
            Redditor object from the Arctic Shift API
        """
        pass

    @abstractmethod
    def redditor_hardcoded(self, name: str, user_id:str|None=None, created:datetime|None=None) -> Any:
        """
        Create a redditor (user) object by hand.
        
        Args:
            name: The Reddit username
            
        Returns:
            Redditor object from data
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

    @abstractmethod
    def subreddit_hardcoded(self, name: str, sub_id:str|None=None, created:datetime|None=None) -> Any:
        """
        Create a subreddit by hand.
        
        Args:
            name: The subreddit object name
            sub_id: The subreddit object id
            
        Returns:
            Subreddit object from data
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

    def get_retry_after_seconds(self, response: requests.Response) -> int:
        header = response.headers.get("Retry-After")
        if not header:
            return 0

        # 1. Delta-seconds format (e.g., "120")
        if header.isdigit():
            return int(header)

        # 2. HTTP-date format (e.g., "Wed, 21 Apr 2026 07:28:00 GMT")
        try:
            retry_date = parsedate_to_datetime(header)
            now_utc = datetime.now(timezone.utc)
            delta = (retry_date - now_utc).total_seconds()
            return max(0, delta)
        except (TypeError, ValueError):
            return 0

    def get_x_ratelimit_reset_seconds(self, response: requests.Response) -> int:
        """
            Calculates seconds to sleep from an x-ratelimit-reset header value.
            Handles Unix timestamps (epoch) or relative delta seconds.
        """
        header = response.headers.get("x-ratelimit-reset")
        if not header:
            return 0

        if header.isdigit():
            return int(header)

        try:
            val = float(header)
        except ValueError:
            return 0

        # If the value is huge (e.g., > Jan 1, 2030 or 10 digits+), it is a Unix epoch timestamp
        if val > 1_000_000_000:
            # Check if it's in milliseconds (13 digits+)
            if val > 10_000_000_000_00:
                val /= 1000.0
            wait_time = int(val - time.time())
        else:
            # Otherwise, it's a relative delta (seconds remaining)
            wait_time = int(val)

        return wait_time

    def get_rate_limit_seconds(self, response: requests.Response) -> int:
        wait_time = 0

        # 1. Try to honor the server's explicit Retry-After header
        wait_time = self.get_retry_after_seconds(response)
        if wait_time:
            return wait_time
        wait_time = self.get_x_ratelimit_reset_seconds(response)
        if wait_time:
            return wait_time
        wait_time = self.get_x_ratelimit_reset_at_seconds(response)
        if wait_time:
            return wait_time

        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            return DEFAULT_WAIT_S

    def get_x_ratelimit_reset_at_seconds(self, response: requests.Response) -> int:
        """
        Checks for x-ratelimit-reset-at, calculates sleep time, and pauses execution.
        """
        # 1. Check if the header exists (case-insensitive lookups are handled by requests)
        reset_at = response.headers.get("x-ratelimit-reset-at")
        if not reset_at:
            return

        # Get the current time in UTC (with timezone awareness)
        now = datetime.now(timezone.utc)
        reset_datetime = None

        # 2. Try parsing as a Unix timestamp (integer/float)
        try:
            # Works for both seconds (e.g., 1792233600) and milliseconds
            timestamp = float(reset_at)
            # If the timestamp is way in the future, it might be in milliseconds
            if timestamp > 1e11:
                timestamp /= 1000
            reset_datetime = datetime.fromtimestamp(timestamp, timezone.utc)
        except ValueError:
            pass

        # 3. Try parsing as an ISO 8601 string if Unix parsing failed
        if not reset_datetime:
            try:
                # fromisoformat handles standard formats like '2026-10-17T21:20:00Z'
                # Note: Replace 'Z' with '+00:00' for compatibility in older Python versions
                clean_reset_at = reset_at.replace("Z", "+00:00")
                reset_datetime = datetime.fromisoformat(clean_reset_at)
            except ValueError:
                self.logger.error("Unknown rate limit reset format: %s", reset_at)
                return 0

        # 4. Calculate sleep duration
        # total_seconds() can be negative if the reset time already passed
        return (reset_datetime - now).total_seconds()

    def check_specialiazed_429(self, response) -> bool:
        return False

    def check_too_many_requests(self, response) -> tuple[bool, bool]:
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            return True, False

        return False, self.check_specialiazed_429(response)

    def make_http_request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """
        Make a request to the Reddit Data Interface.

        Args:
            endpoint: The API endpoint to call
            params: Optional parameters for the request
            
        Returns:
            JSON response from the API
        """
        response = None
        if self._http_session is None:
            self._http_session = requests.Session()
        if self._token.get_decrypted():
            self._http_session.headers.update({
                'Authorization': f'Bearer {self._token.get_decrypted()}',
                'User-Agent': self.get_user_agent()
            })
        tries = DEFAULT_RETRIES
        loop = 0

        url = urljoin(self._base_url, endpoint)
        while True:
            loop += 1
            self.logger.debug("HTTP get executing to: %s", url)
            response = self._http_session.get(url, timeout=10, params=params)
            if response.ok:
                break
            b_429, b_specialized = self.check_too_many_requests(response)
            if b_429 or b_specialized:
                wait_time = 0
                if loop >= tries:
                    if not b_specialized:
                        response.raise_for_status()
                    else:
                         # Change the status code and reason of the response object
                        response.status_code = 429
                        response.reason = "Too Many Requests"

                        # Option A: Re-raise the modified HTTPError
                        raise requests.exceptions.HTTPError(
                            f"Specialized ({response.status_code}) converted to 429",
                            response=response
                        )
                    break # should never get here

                self.increment_rate_limit_count()
                wait_time = self.get_rate_limit_seconds(response)
                self.add_rate_limit_duration(wait_time)
                Message.send_warning(f"Sleeping {wait_time} seconds due to rate limit: {endpoint}")
                self.logger.warning("Sleeping %d seconds due to rate limit on: %s", wait_time, endpoint)
                time.sleep(wait_time)
            else:
                response.raise_for_status()
                break # should never get here
        return response.json()

    def set_reddit_object(self, reddit_object:RedditObject):
        self._reddit_object = reddit_object

    def get_reddit_object(self) -> RedditObject:
        return self._reddit_object
