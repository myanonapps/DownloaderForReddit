"""
Tests for the optional nickname of users and subreddits: how it is displayed, searched and sorted.


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
"""

import os
from types import SimpleNamespace
from typing import Optional
from unittest import TestCase

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from DownloaderForReddit.core.const import USER_OBJECT
from DownloaderForReddit.database.database_handler import DatabaseHandler
from DownloaderForReddit.database.filters import RedditObjectFilter
from DownloaderForReddit.database.models import ListAssociation, RedditObjectList, User
from DownloaderForReddit.utils import injector
from DownloaderForReddit.viewmodels.reddit_object_list_model import RedditObjectListModel


LIST_NAME = 'Nickname test list'


class TestRedditObjectNickname(TestCase):
    """Tests for RedditObject.nickname_or_name, the nickname search and sort filters, and the list model's use of them."""

    @classmethod
    def setUpClass(cls) -> None:
        """Creates the QApplication the list model's icons need, without opening a window."""
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        """Creates an in-memory database holding a user list with one user that has a nickname and two that do not."""
        injector.database_handler = DatabaseHandler(in_memory=True)
        injector.settings_manager = SimpleNamespace(
            main_window_tooltip_display_dict={'name': True, 'nickname': True},
            list_order_method='name',
            order_list_desc=False,
        )
        self.db = injector.get_database_handler()
        with self.db.get_scoped_session() as session:
            user_list = RedditObjectList(name=LIST_NAME, list_type=USER_OBJECT)
            session.add(user_list)
            for name, nickname in (('alpha_user', None), ('beta_user', 'Zed'), ('gamma_user', '')):
                user = User(name=name, nickname=nickname)
                session.add(user)
                session.add(ListAssociation(reddit_object_list=user_list, reddit_object=user))
            session.commit()

    def tearDown(self) -> None:
        """Removes the test database and settings from the injector so other tests do not share them."""
        injector.database_handler = None
        injector.settings_manager = None

    def _ordered_names(self, order: str, desc: bool = False, search: Optional[str] = None) -> list[str]:
        """
        Queries the users through RedditObjectFilter.
        :param order: The field to order by.
        :type order: str
        :param desc: True to order descending.
        :type desc: bool
        :param search: Optional text that the name or nickname must contain.
        :type search: Optional[str]
        :return: The reddit names of the matching users, in order.
        :rtype: list[str]
        """
        filters = [('name_or_nickname', 'like', search)] if search else []
        with self.db.get_scoped_session() as session:
            return [user.name for user in RedditObjectFilter().filter(session, *filters, order_by=order, desc=desc).all()]

    def test_nickname_or_name_falls_back_to_name(self) -> None:
        """nickname_or_name is the nickname when it is set, and the reddit name when it is None, empty or blank."""
        self.assertEqual('Zed', User(name='beta_user', nickname='Zed').nickname_or_name)
        self.assertEqual('alpha_user', User(name='alpha_user', nickname=None).nickname_or_name)
        self.assertEqual('gamma_user', User(name='gamma_user', nickname='').nickname_or_name)
        self.assertEqual('gamma_user', User(name='gamma_user', nickname='   ').nickname_or_name)

    def test_search_matches_name_or_nickname(self) -> None:
        """The name_or_nickname filter finds an object by its reddit name or by its nickname, ignoring case."""
        self.assertEqual(['beta_user'], self._ordered_names('name', search='zed'))
        self.assertEqual(['beta_user'], self._ordered_names('name', search='beta'))
        self.assertEqual(['alpha_user', 'beta_user', 'gamma_user'], self._ordered_names('name', search='_user'))

    def test_order_by_nickname_uses_displayed_name(self) -> None:
        """Ordering by nickname sorts by the displayed name, so objects without a nickname are sorted among the rest."""
        self.assertEqual(['alpha_user', 'gamma_user', 'beta_user'], self._ordered_names('nickname'))
        self.assertEqual(['beta_user', 'gamma_user', 'alpha_user'], self._ordered_names('nickname', desc=True))

    def test_nickname_is_an_order_field(self) -> None:
        """Nickname is offered as a sort option for reddit object lists."""
        self.assertIn('nickname', RedditObjectFilter.get_order_fields())

    def test_list_model_displays_nickname(self) -> None:
        """The list model shows the nickname in place of the name, and searching by nickname finds the object."""
        model = RedditObjectListModel(USER_OBJECT)
        model.set_list(LIST_NAME)
        displayed = [model.data(model.createIndex(row, 0), Qt.ItemDataRole.DisplayRole) for row in range(model.rowCount())]
        self.assertEqual(['alpha_user', 'Zed', 'gamma_user'], displayed)

        model.search_list('zed')
        self.assertEqual(['beta_user'], [user.name for user in model.reddit_objects])
        model.close_session()

    def test_tooltip_shows_nickname_and_tolerates_missing_key(self) -> None:
        """The tooltip has a nickname line when enabled, and a tooltip setting without that key does not fail."""
        model = RedditObjectListModel(USER_OBJECT)
        model.set_list(LIST_NAME)
        beta = next(user for user in model.reddit_objects if user.name == 'beta_user')
        self.assertEqual('Name: beta_user\nNickname: Zed', model.set_tooltips(beta))

        injector.settings_manager.main_window_tooltip_display_dict = {'name': True}
        self.assertEqual('Name: beta_user', model.set_tooltips(beta))
        model.close_session()
