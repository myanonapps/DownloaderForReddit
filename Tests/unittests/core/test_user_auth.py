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


Unit tests for UaNetworkAccessManager and the UserAuth OAuth flow.  The Qt OAuth classes and the adapter manager are
replaced by mocks, so no network or browser is used.
"""
from unittest import TestCase
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QByteArray, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest

from DownloaderForReddit.core.user_auth import UaNetworkAccessManager, UserAuth
from DownloaderForReddit.database.model_enums import PostDownloadSource

USER_AGENT = 'test_user_agent'
CLIENT_ID = 'test_client_id'
AUTHORIZATION_URL = QUrl('https://www.reddit.com/api/v1/authorize')
ACCESS_URL = QUrl('https://www.reddit.com/api/v1/access_token')
MODULE = 'DownloaderForReddit.core.user_auth'


class TestUaNetworkAccessManager(TestCase):
    """
    Tests for the network access manager that adds a User-Agent header.
    """

    def test_create_request_sets_user_agent(self) -> None:
        """
        Every request gets the configured User-Agent header.
        """
        manager = UaNetworkAccessManager('TestAgent')
        request = QNetworkRequest(QUrl('http://example.com'))

        with patch.object(QNetworkRequest, 'setRawHeader') as mock_set_header:
            manager.createRequest(QNetworkAccessManager.Operation.GetOperation, request)
            mock_set_header.assert_any_call(QByteArray(b'User-Agent'), QByteArray(b'TestAgent'))


class TestUserAuth(TestCase):
    """
    Tests for UserAuth, with the adapter manager mocked.
    """

    def setUp(self) -> None:
        """
        Patches the adapter manager to return a mock Reddit adapter and creates the UserAuth under test.
        """
        patcher = patch(f'{MODULE}.RedditAdapterManager')
        self.mock_manager_class = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_manager = self.mock_manager_class.return_value

        self.adapter = MagicMock()
        self.adapter.CLIENT_ID = CLIENT_ID
        self.adapter.TOKEN_SCOPES = ['identity', 'read']
        self.adapter.get_user_agent.return_value = USER_AGENT
        self.adapter.get_authorization_url.return_value = AUTHORIZATION_URL
        self.adapter.get_access_url.return_value = ACCESS_URL
        self.mock_manager.get_adapter.return_value = self.adapter

        self.user_auth = UserAuth()
        self.connected_slot = MagicMock()
        self.user_auth.connected.connect(self.connected_slot)

    def test_init(self) -> None:
        """
        A new UserAuth uses the Reddit adapter and has no OAuth flow yet.
        """
        self.mock_manager.get_adapter.assert_called_once_with(PostDownloadSource.REDDIT)
        self.assertIs(self.user_auth.adapter, self.adapter)
        self.assertIsNone(self.user_auth.oauth)

    @patch(f'{MODULE}.QDesktopServices')
    @patch(f'{MODULE}.QOAuth2AuthorizationCodeFlow')
    @patch(f'{MODULE}.QOAuthHttpServerReplyHandler')
    @patch(f'{MODULE}.UaNetworkAccessManager')
    def test_start_oauth(self, mock_ua_manager: MagicMock, mock_reply_handler: MagicMock, mock_oauth_flow: MagicMock,
                         mock_desktop_services: MagicMock) -> None:
        """
        Starting OAuth builds and configures the flow from the adapter's settings and opens the browser authorization.

        :param mock_ua_manager: The patched UaNetworkAccessManager class.
        :type mock_ua_manager: MagicMock
        :param mock_reply_handler: The patched QOAuthHttpServerReplyHandler class.
        :type mock_reply_handler: MagicMock
        :param mock_oauth_flow: The patched QOAuth2AuthorizationCodeFlow class.
        :type mock_oauth_flow: MagicMock
        :param mock_desktop_services: The patched QDesktopServices class.
        :type mock_desktop_services: MagicMock
        """
        oauth = self.user_auth.start_oauth()

        mock_oauth_instance = mock_oauth_flow.return_value
        self.assertIs(oauth, mock_oauth_instance)
        self.assertIs(self.user_auth.oauth, mock_oauth_instance)
        mock_ua_manager.assert_called_once_with(USER_AGENT, self.user_auth)
        mock_reply_handler.assert_called_once_with(8086, self.user_auth)
        mock_oauth_flow.assert_called_once_with(CLIENT_ID, AUTHORIZATION_URL, ACCESS_URL, mock_ua_manager.return_value, self.user_auth)

        mock_oauth_instance.granted.connect.assert_called_once_with(self.user_auth.finish_oauth)
        mock_oauth_instance.error.connect.assert_called_once()
        mock_oauth_instance.requestFailed.connect.assert_called_once()
        mock_oauth_instance.authorizeWithBrowser.connect.assert_called_once_with(mock_desktop_services.openUrl)
        mock_oauth_instance.setReplyHandler.assert_called_once_with(mock_reply_handler.return_value)
        mock_oauth_instance.setScope.assert_called_once_with('identity read')
        mock_oauth_instance.setUserAgent.assert_called_once_with(USER_AGENT)
        mock_oauth_instance.resourceOwnerAuthorization.assert_called_once_with(AUTHORIZATION_URL, {'duration': ['permanent']})

    @patch(f'{MODULE}.QDesktopServices')
    @patch(f'{MODULE}.QOAuth2AuthorizationCodeFlow')
    @patch(f'{MODULE}.QOAuthHttpServerReplyHandler')
    @patch(f'{MODULE}.UaNetworkAccessManager')
    def test_start_oauth_cleans_up_previous_flow(self, *_mocks: MagicMock) -> None:
        """
        Starting OAuth again closes the previous flow's reply handler and schedules its objects for deletion.

        :param _mocks: The patched Qt classes, unused.
        :type _mocks: MagicMock
        """
        old_oauth = MagicMock()
        self.user_auth.oauth = old_oauth

        self.user_auth.start_oauth()

        old_oauth.replyHandler.return_value.close.assert_called_once()
        old_oauth.replyHandler.return_value.deleteLater.assert_called_once()
        old_oauth.networkAccessManager.return_value.deleteLater.assert_called_once()
        old_oauth.deleteLater.assert_called_once()
        self.assertIsNot(self.user_auth.oauth, old_oauth)

    def test_finish_oauth_success(self) -> None:
        """
        A refresh token is saved for the Reddit source, the callback port is closed and success is reported.
        """
        self.user_auth.oauth = MagicMock()
        self.user_auth.oauth.refreshToken.return_value = 'test_refresh_token'

        self.user_auth.finish_oauth()

        self.mock_manager.save_adapter_token.assert_called_once_with(PostDownloadSource.REDDIT, 'test_refresh_token')
        self.user_auth.oauth.replyHandler.return_value.close.assert_called_once()
        self.connected_slot.assert_called_once_with(True)

    def test_finish_oauth_failure(self) -> None:
        """
        Without a refresh token nothing is saved, the callback port is closed and failure is reported.
        """
        self.user_auth.oauth = MagicMock()
        self.user_auth.oauth.refreshToken.return_value = None

        self.user_auth.finish_oauth()

        self.mock_manager.save_adapter_token.assert_not_called()
        self.user_auth.oauth.replyHandler.return_value.close.assert_called_once()
        self.connected_slot.assert_called_once_with(False)

    def test_finish_oauth_no_oauth_instance(self) -> None:
        """
        Finishing without a flow logs an error and reports failure.
        """
        self.user_auth.oauth = None

        with patch.object(self.user_auth.logger, 'error') as mock_log_error:
            self.user_auth.finish_oauth()

        self.connected_slot.assert_called_once_with(False)
        mock_log_error.assert_called_once_with('Failed to create OAuth (QOAuth2AuthorizationCodeFlow) object, cannot finish OAuth process')

    def test_finish_oauth_no_oauth_instance_at_cleanup(self) -> None:
        """
        If the flow is discarded while the refresh token is read, failure is still reported without crashing.
        """
        self.user_auth.oauth = MagicMock()

        def clear_oauth() -> None:
            """
            Discards the flow and returns no token.
            """
            self.user_auth.oauth = None

        self.user_auth.oauth.refreshToken.side_effect = clear_oauth

        self.user_auth.finish_oauth()

        self.connected_slot.assert_called_once_with(False)

    def _start_mocked_oauth(self) -> MagicMock:
        """
        Runs start_oauth with the Qt network and OAuth classes patched out.

        :return: The mock OAuth flow that start_oauth created.
        :rtype: MagicMock
        """
        with patch(f'{MODULE}.QDesktopServices'), patch(f'{MODULE}.QOAuthHttpServerReplyHandler'),                 patch(f'{MODULE}.UaNetworkAccessManager'), patch(f'{MODULE}.QOAuth2AuthorizationCodeFlow') as mock_oauth_flow:
            self.user_auth.start_oauth()
        return mock_oauth_flow.return_value

    def test_oauth_error_signal(self) -> None:
        """
        The slot connected to the error signal logs the error, cleans up the flow and reports failure once, even if
        signalled twice.
        """
        oauth = self._start_mocked_oauth()
        on_error = oauth.error.connect.call_args.args[0]

        with patch.object(self.user_auth.logger, 'error') as mock_log_error:
            on_error('error_code', 'error_description', QUrl())
            on_error('error_code', 'error_description', QUrl())

        mock_log_error.assert_called_once_with('OAuth error: %s - %s', 'error_code', 'error_description')
        self.connected_slot.assert_called_once_with(False)
        self.assertIsNone(self.user_auth.oauth)
        oauth.replyHandler.return_value.close.assert_called_once()

    def test_request_failed_signal(self) -> None:
        """
        The slot connected to the requestFailed signal logs the failure, cleans up the flow and reports failure.
        """
        oauth = self._start_mocked_oauth()
        on_request_failed = oauth.requestFailed.connect.call_args.args[0]

        with patch.object(self.user_auth.logger, 'error') as mock_log_error:
            on_request_failed('network error')

        mock_log_error.assert_called_once_with('OAuth request failed: %s', 'network error')
        self.connected_slot.assert_called_once_with(False)
        self.assertIsNone(self.user_auth.oauth)
