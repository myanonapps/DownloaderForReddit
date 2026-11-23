"""
Downloader for Reddit takes a list of reddit users and subreddits and downloads content posted to reddit either by the
users or on the subreddits.


Copyright (C) 2017, Kyle Hickey


This file is part of the Downloader for Reddit.

Downloader for Reddit is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Downloader for Reddit is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Downloader for Reddit.  If not, see <http://www.gnu.org/licenses/>.


Unit tests for PullPushAdapter.  HTTP calls are replaced by canned responses shaped like real PullPush responses.
"""
import copy
import logging
from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from DownloaderForReddit.data_interface.adapters.pull_push_adapter import PullPushAdapter
from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.data_interface.reddit_data_interface import RedditDataInterface
from DownloaderForReddit.utils import injector

# A recent epoch time; Windows cannot convert naive datetimes near 1970 back to timestamps
BASE = 1_600_000_000

# A trimmed copy of the real response to https://api.pullpush.io/topic?ids=6uey5x
TOPIC_ITEM = {
    "author": "--love", "created_utc": 1503023321, "domain": "i.imgur.com", "id": "6uey5x", "is_self": False,
    "is_video": False, "num_comments": 2239, "over_18": False, "permalink": "/r/pics/comments/6uey5x/bob_would_be_proud/",
    "score": 72625, "selftext": "", "stickied": False, "subreddit": "pics", "subreddit_id": "t5_2qh0u",
    "title": "Bob would be proud", "url": "http://i.imgur.com/9yTUkao.jpg",
}


def response(*items: dict, error: str | None = None) -> dict:
    """
    Builds a PullPush-style response body.

    :param items: The result items to place under ``data``.
    :type items: dict
    :param error: The value of the ``error`` key.
    :type error: str | None
    :return: The response dictionary.
    :rtype: dict
    """
    return {"data": list(items), "metadata": {}, "error": error}


def post(post_id: str, created_utc: int, **fields: object) -> dict:
    """
    Builds a minimal post item.

    :param post_id: The post id.
    :type post_id: str
    :param created_utc: The post's creation time in epoch seconds.
    :type created_utc: int
    :param fields: Any extra fields for the item.
    :type fields: object
    :return: The post dictionary.
    :rtype: dict
    """
    return {"id": post_id, "created_utc": created_utc, "author": "someone", **fields}


class TestPullPushAdapter(TestCase):
    """
    Tests for PullPushAdapter's requests and its parsing of PullPush responses.
    """

    def setUp(self) -> None:
        """
        Creates an adapter with a mocked settings manager and a mocked HTTP layer.
        """
        injector.settings_manager = MagicMock()
        self.adapter = PullPushAdapter(RedditAdapterToken("pull_push_access", "pull_push_access_token"))
        patcher = patch.object(self.adapter, "make_http_request")
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def params(self, call_index: int) -> dict:
        """
        Returns a copy of the query parameters sent with one HTTP request.

        :param call_index: The position of the request among all requests made.
        :type call_index: int
        :return: The parameters dictionary.
        :rtype: dict
        """
        return self.request.call_args_list[call_index].args[1]

    def test_is_reddit_data_interface(self) -> None:
        """
        The adapter implements every abstract method, so it can be created and used as a RedditDataInterface.
        """
        self.assertIsInstance(self.adapter, RedditDataInterface)
        self.assertEqual("", self.adapter.get_authenticated_user())

    def test_submission_parses_topic_item(self) -> None:
        """
        A /topic result is parsed into a submission, and ``created`` falls back to ``created_utc``.
        """
        self.request.return_value = response(TOPIC_ITEM)

        submission = self.adapter.submission("t3_6uey5x")

        self.assertEqual("topic", self.request.call_args.args[0])
        self.assertEqual({"ids": "6uey5x"}, self.params(0))
        self.assertEqual("6uey5x", submission.id)
        self.assertEqual("Bob would be proud", submission.title)
        self.assertEqual("http://i.imgur.com/9yTUkao.jpg", submission.url)
        self.assertEqual("--love", submission.author.name)
        self.assertEqual("pics", submission.subreddit.display_name)
        self.assertEqual(1503023321, submission.created)
        self.assertEqual(1503023321, submission.created_utc)
        self.assertFalse(submission.is_self)

    def test_submission_not_found_returns_none(self) -> None:
        """
        An empty result returns None instead of raising.
        """
        self.request.return_value = response()
        self.assertIsNone(self.adapter.submission("missing"))

    def test_api_error_is_treated_as_no_results(self) -> None:
        """
        A response whose ``error`` key is set yields no results, even if it also carries data.
        """
        self.request.return_value = response(TOPIC_ITEM, error="search failed")
        self.assertIsNone(self.adapter.submission("6uey5x"))

    def test_posts_by_author_without_reddit_object(self) -> None:
        """
        Without a reddit object there is nothing to search for, so no request is made.
        """
        self.assertEqual([], self.adapter.posts_by_author())
        self.request.assert_not_called()

    def test_posts_by_author_pages_with_inclusive_boundary(self) -> None:
        """
        Paging keeps ``after`` at the last held timestamp, excludes held ids tied on it, drops repeats, and stops
        when a page brings nothing new.
        """
        date_limit = datetime.fromtimestamp(BASE)
        self.adapter.set_reddit_object(SimpleNamespace(name="someone", post_limit=10, date_limit=date_limit))
        self.request.side_effect = [
            response(post("a", BASE + 100), post("b", BASE + 200), post("c", BASE + 200)),
            response(post("c", BASE + 200), post("d", BASE + 300)),
            response(post("d", BASE + 300)),
        ]

        posts = self.adapter.posts_by_author()

        self.assertEqual(["a", "b", "c", "d"], [p.id for p in posts])
        self.assertEqual(3, self.request.call_count)
        first, second, third = (copy.deepcopy(self.params(i)) for i in range(3))
        self.assertEqual({"author": "someone", "sort": "asc", "sort_type": "created_utc", "after": BASE, "size": 10}, first)
        self.assertEqual(BASE + 200, second["after"])
        self.assertEqual({"c", "b"}, set(second["exclude_ids"].split(",")))
        self.assertEqual(7, second["size"])
        self.assertEqual(BASE + 300, third["after"])
        self.assertEqual("d", third["exclude_ids"])
        self.assertEqual(6, third["size"])

    def test_posts_by_author_stops_at_post_limit(self) -> None:
        """
        Once the post limit is reached no further page is requested, and page size never exceeds 100.
        """
        self.adapter.set_reddit_object(SimpleNamespace(name="someone", post_limit=2, date_limit=datetime.fromtimestamp(BASE)))
        self.request.return_value = response(post("a", BASE + 100), post("b", BASE + 200))

        posts = self.adapter.posts_by_author()

        self.assertEqual(["a", "b"], [p.id for p in posts])
        self.assertEqual(1, self.request.call_count)

    def test_posts_by_author_caps_page_size(self) -> None:
        """
        A post limit above 100 is requested in pages of at most 100.
        """
        self.adapter.set_reddit_object(SimpleNamespace(name="someone", post_limit=1000, date_limit=datetime.fromtimestamp(BASE)))
        self.request.return_value = response()

        self.adapter.posts_by_author()

        self.assertEqual(100, self.params(0)["size"])

    def test_redditor_uses_oldest_post_or_comment(self) -> None:
        """
        The redditor's creation date is its oldest activity across posts and comments, and its id comes from
        whichever item carries ``author_fullname``.
        """
        self.request.side_effect = [
            response(post("p1", 200, author="Someone", author_fullname="t2_abc")),
            response(post("c1", 100, author="Someone")),
        ]

        redditor = self.adapter.redditor("someone")

        self.assertEqual(["topic", "comment"], [c.args[0] for c in self.request.call_args_list])
        self.assertEqual({"author": "someone", "sort": "asc", "sort_type": "created_utc", "size": 1}, self.params(0))
        self.assertEqual("Someone", redditor.name)
        self.assertEqual("Someone", redditor.fullname)
        self.assertEqual("abc", redditor.id)
        self.assertEqual(100, redditor.created)

    def test_check_user_name(self) -> None:
        """
        A name with archived activity is valid and uses the archive's spelling; a name without is invalid.
        """
        self.request.side_effect = [response(post("p1", 200, author="Someone", author_fullname="t2_abc")), response(),
                                    response(), response()]

        valid = self.adapter.check_user_name("someone")
        invalid = self.adapter.check_user_name("nobody")

        self.assertTrue(valid.valid)
        self.assertEqual("Someone", valid.name)
        self.assertEqual("abc", valid.reddit_id)
        self.assertEqual(datetime.fromtimestamp(200), valid.date_created)
        self.assertFalse(invalid.valid)
        self.assertEqual("nobody", invalid.name)

    def test_redditor_by_id_is_unsupported(self) -> None:
        """
        Lookup by id returns an empty redditor without making a request, so validation fails.
        """
        redditor = self.adapter.redditor_by_id("abc")

        self.assertFalse(redditor.fullname)
        self.request.assert_not_called()

    def test_subreddit_from_oldest_post(self) -> None:
        """
        A subreddit is derived from its oldest post, with the ``t5_`` prefix removed from its id.
        """
        self.request.return_value = response(TOPIC_ITEM)

        subreddit = self.adapter.subreddit("PICS")

        self.assertEqual({"subreddit": "PICS", "sort": "asc", "sort_type": "created_utc", "size": 1}, self.params(0))
        self.assertEqual("pics", subreddit.name)
        self.assertEqual("pics", subreddit.fullname)
        self.assertEqual("2qh0u", subreddit.id)
        self.assertEqual(1503023321, subreddit.created)

    def test_check_subreddit_name_invalid(self) -> None:
        """
        A subreddit with no archived posts is invalid.
        """
        self.request.return_value = response()

        result = self.adapter.check_subreddit_name("nothing_here")

        self.assertFalse(result.valid)
        self.assertEqual("nothing_here", result.name)

    def test_hardcoded_objects(self) -> None:
        """
        Hand-built redditors and subreddits keep the supplied values and pass validation without a request.
        """
        created = datetime.fromtimestamp(1500000000)

        redditor = self.adapter.redditor_hardcoded("someone", "abc", created)
        subreddit = self.adapter.subreddit_hardcoded("pics", "2qh0u")

        self.assertEqual(("someone", "someone", "abc", 1500000000), (redditor.name, redditor.fullname, redditor.id, redditor.created))
        self.assertEqual(("pics", "pics", "2qh0u", 0), (subreddit.name, subreddit.fullname, subreddit.id, subreddit.created))
        self.request.assert_not_called()

    def test_get_comments_pages_by_link_id(self) -> None:
        """
        Comments are searched by the bare link id, oldest first, with the same paging as posts.
        """
        self.request.side_effect = [
            response(post("c1", BASE + 100), post("c2", BASE + 200)),
            response(post("c2", BASE + 200)),
        ]

        comments = self.adapter.get_comments("t3_6uey5x", 5)

        self.assertEqual(["c1", "c2"], [c["id"] for c in comments])
        self.assertEqual("comment", self.request.call_args_list[0].args[0])
        self.assertEqual({"link_id": "6uey5x", "sort": "asc", "sort_type": "created_utc", "size": 5}, copy.deepcopy(self.params(0)))
        self.assertEqual("c2", self.params(1)["exclude_ids"])

    def test_submission_comments_are_loaded_from_archive(self) -> None:
        """
        A submission's ``comments`` are fetched lazily through the adapter and built into a tree, without falling
        back to the missing-attribute handler.
        """
        self.request.side_effect = [
            response(TOPIC_ITEM),
            response(post("c1", BASE + 100, parent_id="t3_6uey5x", author="--love", body="top", score=5),
                     post("c2", BASE + 200, parent_id="t1_c1", body="reply", score=1)),
            response(),
        ]

        previous_disable = logging.root.manager.disable
        logging.disable(logging.NOTSET)  # Tests/__init__.py disables logging, which would make assertNoLogs vacuous
        self.addCleanup(logging.disable, previous_disable)
        submission = self.adapter.submission("6uey5x")
        self.assertEqual(1, self.request.call_count)
        with self.assertNoLogs("DownloaderForReddit", level="ERROR"):
            submission.comment_limit = 50
            forest = submission.comments
            self.assertEqual([], forest.replace_more(limit=0))

        self.assertEqual(["c1"], [c.id for c in forest])
        self.assertTrue(forest[0].is_submitter)
        self.assertEqual(["c2"], [c.id for c in forest[0].replies])
        self.assertFalse(forest[0].replies[0].is_submitter)
        self.assertEqual({"link_id": "6uey5x", "sort": "asc", "sort_type": "created_utc", "size": 50}, copy.deepcopy(self.params(1)))
        self.assertIs(forest, submission.comments)
        self.assertEqual(3, self.request.call_count)
