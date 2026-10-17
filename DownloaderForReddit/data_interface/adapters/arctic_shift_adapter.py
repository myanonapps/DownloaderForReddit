"""
Arctic Shift HTTP adapter for the Reddit Data Interface interface.

This module provides an HTTP-based implementation of the RedditAPI interface 
that uses Arctic Shift's HTTP API instead of PRAW.

The API serves the same archive as the bulk dumps over plain unauthenticated HTTP — no key, no registration — which matters because Reddit's tightening API policies have made independent data collection harder for non-commercial users. 
The base URL is https://arctic-shift.photon-reddit.com, the search UI sits at /search, and Heitmann offers no uptime or performance guarantees.
/api/posts/search and /api/comments/search — filter by author, subreddit, after, before, and sort, with limit from 1-100 or auto for 100-1000 results. Posts add title, selftext, query, and url; comments add body, link_id, and parent_id.
/api/posts/ids, /api/comments/ids, /api/subreddits/ids, /api/users/ids — direct lookup by comma-separated IDs, capped at 500 per request.
/api/comments/tree — the full comment tree beneath a post via link_id, up to 25,000 comments.
/api/posts/search/aggregate and /api/comments/search/aggregate — counts grouped by created_utc, author, or subreddit.
/api/subreddits/search, /api/subreddits/rules, and /api/subreddits/wikis — subreddit metadata, rule sets, and wiki pages.
/api/users/search and /api/users/interactions/users — user lookup and user-to-user interaction graphs.
Keyword parameters — title, selftext, body, and query — only work alongside an author or subreddit, and are unsupported for very active users or subreddits. Every endpoint accepts fields to trim the response payload; the search endpoints also take format as json, rss, or jsonfeed.

"""
from datetime import datetime, timezone
from typing import Any
from DownloaderForReddit.core.submission_filter import SubmissionFilter
from DownloaderForReddit.data_interface.adapters.adapter_redditor import AdapterRedditor
from DownloaderForReddit.data_interface.adapters.adapter_submission import AdapterSubmission
from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.data_interface.reddit_data_interface import RedditDataInterface, ValidationSet
from DownloaderForReddit.database.model_enums import PostDownloadSource
from DownloaderForReddit.utils.general_utils import dig


BASE_URL = "https://arctic-shift.photon-reddit.com/"

class ArcticShiftAdapter(RedditDataInterface):
    MAX_LIMIT = 100
    """
    Adapter that wraps Arctic Shift HTTP API to provide the RedditAPI interface.
    
    This class implements the RedditDataInterface using Arctic Shift's HTTP API
    which provides access to Reddit data through an HTTP endpoint.
    """
    def __init__(self, token:RedditAdapterToken):
        """
        Initialize the Arctic Shift adapter.
        
        """
        super().__init__(BASE_URL, token)

    def submission(self, id: str) -> Any:
        """
        Get a submission by its ID.
        
        Args:
            id: The Reddit submission ID
            
        Returns:
            Submission object from the Arctic Shift API
        """
        # Arctic Shift API endpoint for submissions
        endpoint = f"/submission/{id}"
        data = self.make_http_request(endpoint)
        return data

    def posts_by_author(self):
        submissions = []
        reddit_object = self.get_reddit_object()
        if reddit_object is None:
            return submissions
        limit = min(ArcticShiftAdapter.MAX_LIMIT, reddit_object.post_limit)
        # after like: 2026-10-14T15:50:26Z
        # Format to ISO string and replace the offset with 'Z'
        dt_limit = SubmissionFilter.get_date_limit(reddit_object)
        dt_utc = dt_limit.astimezone(timezone.utc)
        iso_string = dt_utc.isoformat().replace("+00:00", "Z")
        endpoint = f"api/posts/search?author={reddit_object.name}&after={iso_string}&limit={limit}&sort=asc"
        data = self.make_http_request(endpoint)
        if 'data' in data:
            for dict_submission in data['data']:
                submission = AdapterSubmission(PostDownloadSource.ARCTIC_SHIFT, dict_submission)
                submissions.append(submission)
        return submissions

    def redditor(self, name: str) -> AdapterRedditor:
        """
        Get a redditor (user) by name.
        
        Args:
            name: The Reddit username
            
        Returns:
            Redditor object from the Arctic Shift API
        """
        # Arctic Shift API endpoint for users
        endpoint = f"/api/users/search?author={name}&limit=1&sort=asc"
        data = self.make_http_request(endpoint)
        if data:
            data = dig(data, 'data', default = [])
            if data:
                data = data[0]
            else:
                data = {}
        else:
            data = {}
        return AdapterRedditor(PostDownloadSource.ARCTIC_SHIFT, data)

    def subreddit(self, name: str) -> Any:
        """
        Get a subreddit by name.
        
        Args:
            name: The subreddit name
            
        Returns:
            Subreddit object from the Arctic Shift API
        """
        # Arctic Shift API endpoint for subreddits
        endpoint = f"/r/{name}"
        data = self.make_http_request(endpoint)
        return data

    def get_authenticated_user(self) -> str:
        return ""

    def check_user_name(self, name) -> ValidationSet:
        account = self.redditor(name)
        if account and account.fullname:
            return ValidationSet(name=account.fullname, date_created=datetime.fromtimestamp(account.created), valid=True)
        return ValidationSet(name=name, date_created=None, valid=False)

    def check_subreddit_name(self, name) -> ValidationSet:
        pass
