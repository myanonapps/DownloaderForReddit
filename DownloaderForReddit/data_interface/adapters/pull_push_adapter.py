"""
Pull Push HTTP adapter for the Reddit Data Interface.

This module implements the RedditDataInterface on top of the PullPush archive API (https://api.pullpush.io), which
serves Reddit posts and comments rebuilt from the public Reddit data dumps.  The API is unauthenticated.

Endpoints used:
    /topic    submission search; filters ``ids``, ``author``, ``subreddit``, ``after``/``before`` (epoch seconds,
              inclusive), ``sort`` (asc/desc), ``sort_type`` (created_utc/score), ``size`` (<= 100), ``exclude_ids``.
    /comment  comment search with the same filters plus ``link_id``.

Every response carries its results under the ``"data"`` key, plus ``"metadata"`` and ``"error"``.  Items use Reddit's
own JSON field names (``id``, ``author``, ``author_fullname``, ``created_utc``, ``subreddit``, ``subreddit_id``...).

PullPush has no user or subreddit metadata endpoints, so redditors and subreddits are derived from their oldest
archived activity: the name comes from that item, and the creation date is the date of that item rather than the real
account or subreddit creation date.  Nothing can be looked up by user or subreddit id.
"""
from datetime import datetime
import logging
from typing import Any, override

from DownloaderForReddit.core.submission_filter import SubmissionFilter
from DownloaderForReddit.data_interface.adapters.adapter_redditor import AdapterRedditor
from DownloaderForReddit.data_interface.adapters.adapter_submission import AdapterSubmission
from DownloaderForReddit.data_interface.adapters.adapter_subreddit import AdapterSubreddit
from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.data_interface.reddit_data_interface import RedditDataInterface, ValidationSet
from DownloaderForReddit.database.model_enums import PostDownloadSource


BASE_URL = "https://api.pullpush.io/"
TOPIC_ENDPOINT = "topic"
COMMENT_ENDPOINT = "comment"
MAX_PAGE_SIZE = 100
DEFAULT_COMMENT_LIMIT = 1000
SUBMISSION_FULLNAME_PREFIX = "t3_"
USER_FULLNAME_PREFIX = "t2_"
SUBREDDIT_FULLNAME_PREFIX = "t5_"

logger = logging.getLogger(f'DownloaderForReddit.{__name__}')


def _strip_prefix(fullname: str | None, prefix: str) -> str:
    """
    Converts a Reddit fullname such as ``t2_abc123`` into the bare id ``abc123`` that the rest of the application
    stores as ``reddit_id``.

    :param fullname: The fullname from the API, which may be missing or already bare.
    :type fullname: str | None
    :param prefix: The type prefix to remove, for example ``t2_``.
    :type prefix: str
    :return: The id without its type prefix, or an empty string if no fullname was supplied.
    :rtype: str
    """
    if not fullname:
        return ""
    return fullname[len(prefix):] if fullname.startswith(prefix) else fullname


def _created(item: dict) -> int:
    """
    Reads an item's creation time as whole epoch seconds.

    :param item: A post or comment dictionary returned by the API.
    :type item: dict
    :return: The ``created_utc`` value, or 0 when it is missing or unreadable.
    :rtype: int
    """
    try:
        return int(item.get("created_utc") or 0)
    except (TypeError, ValueError):
        return 0


class PullPushAdapter(RedditDataInterface):
    """
    Adapter that provides the RedditDataInterface using the PullPush archive API.
    """

    def __init__(self, token: RedditAdapterToken, download_session=None):
        """
        Initializes the Pull Push adapter.

        :param token: The adapter's token.  PullPush needs no authentication, so it is normally empty.
        :type token: RedditAdapterToken
        :param download_session: The download session that rate limiting statistics are recorded against.
        :type download_session: DownloadSession | None
        """
        super().__init__(BASE_URL, token, download_session)
        self._source: PostDownloadSource = PostDownloadSource.PULL_PUSH

    def _search(self, endpoint: str, params: dict[str, Any]) -> list[dict]:
        """
        Runs one search request and returns its result items.

        :param endpoint: The endpoint to query, ``topic`` or ``comment``.
        :type endpoint: str
        :param params: The query parameters for the request.
        :type params: dict[str, Any]
        :return: The items under the response's ``data`` key, or an empty list if the API reported an error or
                 returned no data.
        :rtype: list[dict]
        :raises requests.exceptions.HTTPError: If the request fails after the base class's retries.
        """
        response = self.make_http_request(endpoint, params)
        if not isinstance(response, dict):
            return []
        if response.get("error"):
            logger.error("PullPush %s search failed: %s", endpoint, response["error"])
            return []
        data = response.get("data")
        return data if isinstance(data, list) else []

    def _oldest(self, endpoint: str, **filters: str) -> dict | None:
        """
        Fetches the oldest archived item matching the supplied filters.

        :param endpoint: The endpoint to query, ``topic`` or ``comment``.
        :type endpoint: str
        :param filters: The search filters, for example ``author="name"``.
        :type filters: str
        :return: The oldest matching item, or None if nothing matched.
        :rtype: dict | None
        """
        items = self._search(endpoint, {**filters, "sort": "asc", "sort_type": "created_utc", "size": 1})
        return items[0] if items else None

    def submission(self, id: str) -> AdapterSubmission | None:
        """
        Gets a submission by its id.

        :param id: The Reddit submission id, with or without the ``t3_`` prefix.
        :type id: str
        :return: The submission, or None if the archive does not hold it.
        :rtype: AdapterSubmission | None
        """
        items = self._search(TOPIC_ENDPOINT, {"ids": _strip_prefix(id, SUBMISSION_FULLNAME_PREFIX)})
        return AdapterSubmission(self._source, items[0], comment_loader=self.get_comments) if items else None

    def _paged_search(self, endpoint: str, params: dict[str, Any], limit: int) -> list[dict]:
        """
        Collects up to ``limit`` items in ascending ``created_utc`` order, one page at a time.

        Pages through the results with the method the PullPush documentation prescribes: the ``after`` boundary is
        kept at the last item's ``created_utc`` (filters are inclusive), and the ids already held that share that
        timestamp are sent in ``exclude_ids`` so that they are not returned again.

        :param endpoint: The endpoint to query, ``topic`` or ``comment``.
        :type endpoint: str
        :param params: The search filters, optionally with a starting ``after``.  Sorting and page size are added here.
        :type params: dict[str, Any]
        :param limit: The maximum number of items to collect.
        :type limit: int
        :return: The items found, oldest first.
        :rtype: list[dict]
        :raises requests.exceptions.HTTPError: If a request fails after the base class's retries.
        """
        params = {**params, "sort": "asc", "sort_type": "created_utc"}
        items: list[dict] = []
        held_ids: set[str] = set()
        while len(items) < limit:
            params["size"] = min(MAX_PAGE_SIZE, limit - len(items))
            new_items = [item for item in self._search(endpoint, dict(params)) if item.get("id") and item["id"] not in held_ids]
            if not new_items:
                break
            items.extend(new_items)
            held_ids.update(item["id"] for item in new_items)
            boundary = _created(items[-1])
            params["after"] = boundary
            tied_ids = []
            for item in reversed(items):
                if _created(item) != boundary:
                    break
                tied_ids.append(item["id"])
            params["exclude_ids"] = ",".join(tied_ids)
        return items[:limit]

    def posts_by_author(self) -> list[AdapterSubmission]:
        """
        Gets the current reddit object's posts made after its date limit, oldest first, up to its post limit.

        :return: The author's submissions, or an empty list if no reddit object is set.
        :rtype: list[AdapterSubmission]
        :raises requests.exceptions.HTTPError: If a request fails after the base class's retries.
        """
        reddit_object = self.get_reddit_object()
        if reddit_object is None:
            return []
        params: dict[str, Any] = {"author": reddit_object.name}
        date_limit = SubmissionFilter.get_date_limit(reddit_object)
        if date_limit is not None:
            params["after"] = int(date_limit.timestamp())
        posts = self._paged_search(TOPIC_ENDPOINT, params, reddit_object.post_limit)
        return [AdapterSubmission(self._source, post, comment_loader=self.get_comments) for post in posts]

    @override
    def get_comments(self, submission_id: str, limit: int | None = None) -> list[dict]:
        """
        Fetches a submission's comments from the ``comment`` endpoint, oldest first.  PullPush returns them flat, with
        each comment's ``parent_id`` linking it into the tree.

        :param submission_id: The submission id, with or without the ``t3_`` prefix.
        :type submission_id: str
        :param limit: The maximum number of comments wanted, or None for ``DEFAULT_COMMENT_LIMIT``.
        :type limit: int | None
        :return: The comment dictionaries.
        :rtype: list[dict]
        :raises requests.exceptions.HTTPError: If a request fails after the base class's retries.
        """
        link_id = _strip_prefix(submission_id, SUBMISSION_FULLNAME_PREFIX)
        return self._paged_search(COMMENT_ENDPOINT, {"link_id": link_id}, limit or DEFAULT_COMMENT_LIMIT)

    def redditor(self, name: str) -> AdapterRedditor:
        """
        Gets a redditor by name from their oldest archived post or comment.

        :param name: The Reddit username.
        :type name: str
        :return: The redditor.  Its fields are empty if the archive holds no activity for the name.
        :rtype: AdapterRedditor
        """
        found = [item for item in (self._oldest(TOPIC_ENDPOINT, author=name), self._oldest(COMMENT_ENDPOINT, author=name))
                 if item and item.get("author")]
        if not found:
            return AdapterRedditor(self._source, {})
        earliest = min(found, key=_created)
        fullname = next((item["author_fullname"] for item in found if item.get("author_fullname")), "")
        return AdapterRedditor(self._source, {
            "author": earliest["author"],
            "id": _strip_prefix(fullname, USER_FULLNAME_PREFIX),
            "created_utc": _created(earliest),
        })

    def redditor_by_id(self, user_id: str) -> AdapterRedditor:
        """
        Always returns an empty redditor, because PullPush cannot look users up by id.  Callers must use
        :meth:`redditor` with the username instead.

        :param user_id: The Reddit user id.
        :type user_id: str
        :return: An empty redditor, which fails validation.
        :rtype: AdapterRedditor
        """
        logger.warning("PullPush cannot look up users by id (%s); look them up by name instead", user_id)
        return AdapterRedditor(self._source, {})

    def redditor_hardcoded(self, name: str, user_id: str | None = None, created: datetime | None = None) -> AdapterRedditor:
        """
        Builds a redditor from known values without calling the API.

        :param name: The Reddit username.
        :type name: str
        :param user_id: The Reddit user id, if known.
        :type user_id: str | None
        :param created: The account creation date, if known.
        :type created: datetime | None
        :return: The redditor.
        :rtype: AdapterRedditor
        """
        data: dict[str, Any] = {"author": name, "id": user_id or ""}
        if created:
            data["created_utc"] = created.timestamp()
        return AdapterRedditor(self._source, data)

    def subreddit(self, name: str) -> AdapterSubreddit:
        """
        Gets a subreddit by name from its oldest archived post.

        :param name: The subreddit name, without the ``r/`` prefix.
        :type name: str
        :return: The subreddit.  Its fields are empty if the archive holds no posts for it.
        :rtype: AdapterSubreddit
        """
        post = self._oldest(TOPIC_ENDPOINT, subreddit=name)
        if not post or not post.get("subreddit"):
            return AdapterSubreddit(self._source, {})
        return AdapterSubreddit(self._source, {
            "name": post["subreddit"],
            "id": _strip_prefix(post.get("subreddit_id"), SUBREDDIT_FULLNAME_PREFIX),
            "created_utc": _created(post),
        })

    def subreddit_hardcoded(self, name: str, sub_id: str | None = None, created: datetime | None = None) -> AdapterSubreddit:
        """
        Builds a subreddit from known values without calling the API.

        :param name: The subreddit name.
        :type name: str
        :param sub_id: The subreddit id, if known.
        :type sub_id: str | None
        :param created: The subreddit creation date, if known.
        :type created: datetime | None
        :return: The subreddit.
        :rtype: AdapterSubreddit
        """
        data: dict[str, Any] = {"name": name, "id": sub_id or ""}
        if created:
            data["created_utc"] = created.timestamp()
        return AdapterSubreddit(self._source, data)

    def get_authenticated_user(self) -> str:
        """
        Gets the authenticated user's name.  PullPush has no user accounts.

        :return: Always an empty string.
        :rtype: str
        """
        return ""

    def check_user_name(self, name: str) -> ValidationSet:
        """
        Checks whether the archive holds any activity for a username.  A real account with no archived posts or
        comments is reported as invalid.

        :param name: The username to check.
        :type name: str
        :return: The validation result, with the name as the archive spells it and the date of its oldest activity.
        :rtype: ValidationSet
        """
        account = self.redditor(name)
        if account.fullname:
            return ValidationSet(name=account.fullname, date_created=datetime.fromtimestamp(account.created) if account.created else None,
                                 reddit_id=account.id, valid=True)
        return ValidationSet(name=name, date_created=None, reddit_id="", valid=False)

    def check_subreddit_name(self, name: str) -> ValidationSet:
        """
        Checks whether the archive holds any posts for a subreddit.  A real subreddit with no archived posts is
        reported as invalid.

        :param name: The subreddit name to check.
        :type name: str
        :return: The validation result, with the name as the archive spells it and the date of its oldest post.
        :rtype: ValidationSet
        """
        sub = self.subreddit(name)
        if sub.name:
            return ValidationSet(name=sub.name, date_created=datetime.fromtimestamp(sub.created) if sub.created else None,
                                 reddit_id=sub.id, valid=True)
        return ValidationSet(name=name, date_created=None, reddit_id="", valid=False)
