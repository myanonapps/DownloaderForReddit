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


Unit tests for the archive comment adapters, for AdapterSubmission's comment loading, and for CommentHandler running
on archive submissions.
"""
import itertools
import logging
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests

from DownloaderForReddit.core.comment_handler import CommentHandler
from DownloaderForReddit.data_interface.adapters.adapter_comment import AdapterComment, build_comment_forest
from DownloaderForReddit.data_interface.adapters.adapter_submission import AdapterSubmission
from DownloaderForReddit.data_interface.adapters.arctic_shift_adapter import ArcticShiftAdapter
from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.database.model_enums import CommentDownload, CommentSortMethod, LimitOperator, PostDownloadSource
from DownloaderForReddit.utils import injector

SOURCE = PostDownloadSource.ARCTIC_SHIFT
BASE = 1_600_000_000


def enable_logging(test: TestCase) -> None:
    """
    Turns logging back on for one test.  ``Tests/__init__.py`` disables it for the whole run, which would make
    ``assertLogs`` fail and ``assertNoLogs`` pass without checking anything.  The previous setting is restored on
    cleanup.

    :param test: The test that needs logging.
    :type test: TestCase
    """
    previous = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    test.addCleanup(logging.disable, previous)


def comment(comment_id: str, parent_id: str, created: int = BASE, score: int = 0, **fields: object) -> dict:
    """
    Builds a minimal Reddit-format comment dictionary.

    :param comment_id: The comment id.
    :type comment_id: str
    :param parent_id: The parent's fullname, ``t3_`` for the submission or ``t1_`` for a comment.
    :type parent_id: str
    :param created: The creation time in epoch seconds.
    :type created: int
    :param score: The comment's score.
    :type score: int
    :param fields: Any extra fields.
    :type fields: object
    :return: The comment dictionary.
    :rtype: dict
    """
    return {"id": comment_id, "parent_id": parent_id, "created_utc": created, "score": score, "author": "someone",
            "body": f"body {comment_id}", "subreddit": "pics", **fields}


def tree_entry(data: dict, *children: dict) -> dict:
    """
    Wraps a comment in Reddit's nested listing format, as Arctic Shift's comment tree returns it.

    :param data: The comment's fields.
    :type data: dict
    :param children: Already wrapped reply entries.
    :type children: dict
    :return: The ``{"kind": "t1", "data": ...}`` entry.
    :rtype: dict
    """
    replies = {"kind": "Listing", "data": {"children": list(children)}} if children else ""
    return {"kind": "t1", "data": {**data, "replies": replies}}


class TestAdapterComment(TestCase):
    """
    Tests for AdapterComment and build_comment_forest.
    """

    def test_fields_and_fallbacks(self) -> None:
        """
        ``created`` falls back to ``created_utc``, ``body_html`` is built from markdown, and ``is_submitter`` falls back
        to comparing the author with the submission's author.
        """
        item = AdapterComment(SOURCE, comment("a", "t3_x", author="op", body="**hi**"), submission_author="op")

        self.assertEqual(("a", BASE, "op", "pics"), (item.id, item.created, item.author.name, item.subreddit.display_name))
        self.assertIn("<strong>hi</strong>", item.body_html)
        self.assertTrue(item.is_submitter)
        self.assertFalse(AdapterComment(SOURCE, comment("b", "t3_x", is_submitter=False, author="op"), "op").is_submitter)
        self.assertEqual([], item.replies.replace_more(limit=0))

    def test_flat_input_builds_tree(self) -> None:
        """
        Flat results are linked through ``parent_id``, duplicates are dropped, and orphans become top-level comments.
        """
        forest = build_comment_forest([
            comment("a", "t3_x", score=1),
            comment("b", "t1_a"),
            comment("c", "t1_b"),
            comment("b", "t1_a"),
            comment("d", "t1_missing", score=9),
        ], SOURCE)

        self.assertEqual(["d", "a"], [c.id for c in forest])
        self.assertEqual(["b"], [c.id for c in forest[1].replies])
        self.assertEqual(["c"], [c.id for c in forest[1].replies[0].replies])

    def test_nested_input_builds_tree(self) -> None:
        """
        Nested listing results keep their structure, and "more" stubs are dropped.
        """
        items = [
            tree_entry(comment("a", "t3_x"), tree_entry(comment("b", "t1_a"))),
            {"kind": "more", "data": {"children": ["z"]}},
        ]

        forest = build_comment_forest(items, SOURCE)

        self.assertEqual(["a"], [c.id for c in forest])
        self.assertEqual(["b"], [c.id for c in forest[0].replies])
        self.assertEqual([], forest[0].replies[0].replies)

    def test_sort_orders(self) -> None:
        """
        ``new`` and ``old`` sort by date, and other sorts by score, at every level.
        """
        items = [comment("a", "t3_x", BASE + 1, 5), comment("b", "t3_x", BASE + 2, 1), comment("c", "t3_x", BASE + 3, 9),
                 comment("r1", "t1_a", BASE + 5, 0), comment("r2", "t1_a", BASE + 4, 3)]

        self.assertEqual(["c", "b", "a"], [c.id for c in build_comment_forest(items, SOURCE, sort="new")])
        self.assertEqual(["a", "b", "c"], [c.id for c in build_comment_forest(items, SOURCE, sort="old")])
        top = build_comment_forest(items, SOURCE, sort="top")
        self.assertEqual(["c", "a", "b"], [c.id for c in top])
        self.assertEqual(["r2", "r1"], [c.id for c in top[1].replies])

    def test_parent_cycle_does_not_loop(self) -> None:
        """
        A corrupt record pair that names each other as parents ends up in the tree without looping forever.
        """
        forest = build_comment_forest([comment("a", "t1_b"), comment("b", "t1_a")], SOURCE)

        self.assertEqual(["b"], [c.id for c in forest])
        self.assertEqual(["a"], [c.id for c in forest[0].replies])


class TestAdapterSubmissionComments(TestCase):
    """
    Tests for AdapterSubmission's lazily loaded ``comments``.
    """

    def setUp(self) -> None:
        """
        Enables logging so that the log assertions check something.
        """
        enable_logging(self)

    def test_without_loader_comments_are_empty(self) -> None:
        """
        A submission built without a comment loader has an empty comment forest and logs no fallback error.
        """
        submission = AdapterSubmission(SOURCE, {"id": "x", "author": "op"})
        with self.assertNoLogs("DownloaderForReddit", level="ERROR"):
            self.assertEqual([], submission.comments)
            self.assertIsNone(submission.media)

    def test_loader_is_called_once_with_limit(self) -> None:
        """
        The loader receives the submission id and ``comment_limit``, is called only once, and the sort set before
        the first access is applied.
        """
        loader = MagicMock(return_value=[comment("a", "t3_x", BASE + 1), comment("b", "t3_x", BASE + 2)])
        submission = AdapterSubmission(SOURCE, {"id": "x", "author": "op"}, comment_loader=loader)
        submission.comment_limit = 7
        submission.comment_sort = "new"

        self.assertEqual(["b", "a"], [c.id for c in submission.comments])
        self.assertIs(submission.comments, submission.comments)
        loader.assert_called_once_with("x", 7)

    def test_loader_failure_gives_empty_comments(self) -> None:
        """
        A failed request is logged and leaves the submission with no comments instead of raising.
        """
        loader = MagicMock(side_effect=requests.exceptions.HTTPError("boom"))
        submission = AdapterSubmission(SOURCE, {"id": "x"}, comment_loader=loader)

        with self.assertLogs("DownloaderForReddit", level="ERROR"):
            self.assertEqual([], submission.comments)


class TestArcticShiftComments(TestCase):
    """
    Tests for ArcticShiftAdapter's comment requests.
    """

    def setUp(self) -> None:
        """
        Creates an adapter with a mocked settings manager and a mocked HTTP layer.
        """
        injector.settings_manager = MagicMock()
        self.adapter = ArcticShiftAdapter(RedditAdapterToken("arctic_shift_access", "arctic_shift_access_token"))
        patcher = patch.object(self.adapter, "make_http_request")
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_comments_requests_tree(self) -> None:
        """
        Comments come from the tree endpoint with a ``t3_`` link id, and the limit is capped at the API maximum.
        """
        tree = [tree_entry(comment("a", "t3_x"))]
        self.request.return_value = {"data": tree}

        self.assertEqual(tree, self.adapter.get_comments("x", 100000))
        self.request.assert_called_once_with("api/comments/tree", {"link_id": "t3_x", "limit": 25000})
        self.adapter.get_comments("t3_x", 30)
        self.assertEqual({"link_id": "t3_x", "limit": 30}, self.request.call_args.args[1])

    def test_submission_not_found_returns_none(self) -> None:
        """
        An empty lookup returns None instead of raising IndexError.
        """
        self.request.return_value = {"data": []}
        self.assertIsNone(self.adapter.submission("missing"))


class TestCommentHandlerWithArchiveSubmission(TestCase):
    """
    CommentHandler, written for PRAW, runs unchanged on an archive submission.
    """

    def test_extracts_comment_tree(self) -> None:
        """
        Every comment is handed to the creator with its parent's database id, and no fallback error is logged.
        """
        enable_logging(self)
        items = [tree_entry(comment("a", "t3_x", score=2), tree_entry(comment("b", "t1_a"))), comment("c", "t3_x", score=1)]
        submission = AdapterSubmission(SOURCE, {"id": "x", "author": "op"}, comment_loader=MagicMock(return_value=items))
        significant = SimpleNamespace(
            comment_sort_method=CommentSortMethod.TOP, comment_limit=100, comment_depth=100, comment_reply_limit=100,
            extract_comments=CommentDownload.DOWNLOAD, download_comments=CommentDownload.DO_NOT_DOWNLOAD,
            download_comment_content=CommentDownload.DO_NOT_DOWNLOAD, comment_score_limit_operator=LimitOperator.NO_LIMIT,
            comment_score_limit=0)
        post = SimpleNamespace(significant_reddit_object=significant)
        stop_run = MagicMock()
        stop_run.is_set.return_value = False
        db_ids = itertools.count(1)
        created = []

        def create_comment(praw_comment, *_args, parent_comment_id=None):
            """
            Records the comment and returns a stand-in database row.

            :param praw_comment: The comment being stored.
            :type praw_comment: AdapterComment
            :param parent_comment_id: The database id of the parent comment.
            :type parent_comment_id: int | None
            :return: A row with a new database id.
            :rtype: SimpleNamespace
            """
            row = SimpleNamespace(id=next(db_ids))
            created.append((praw_comment.id, parent_comment_id, row.id))
            return row

        with patch("DownloaderForReddit.core.comment_handler.injector"), \
                patch("DownloaderForReddit.core.comment_handler.SubmittableCreator.create_comment", side_effect=create_comment), \
                self.assertNoLogs("DownloaderForReddit", level="ERROR"):
            CommentHandler(submission, post, 1, stop_run, session=MagicMock()).run()

        self.assertEqual([("a", None, 1), ("c", None, 2), ("b", 1, 3)], created)
