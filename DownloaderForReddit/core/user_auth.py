import logging

from PyQt6.QtCore import QByteArray, QObject, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QNetworkAccessManager
from PyQt6.QtNetworkAuth import QOAuthHttpServerReplyHandler, QOAuth2AuthorizationCodeFlow

from DownloaderForReddit.data_interface.adapter_manager import RedditAdapterManager
from DownloaderForReddit.data_interface.adapters.praw_adapter import PRAWAdapter
from DownloaderForReddit.database.model_enums import PostDownloadSource



class UaNetworkAccessManager(QNetworkAccessManager):
    """
    Handles network requests with a customizable User-Agent header.

    This class extends QNetworkAccessManager to allow setting a custom User-Agent header for all network requests.

    :ivar _ua: Encoded User-Agent string that will be added as a header in network requests.
    :type _ua: bytes
    """
    def __init__(self, user_agent: str, parent=None):
        super().__init__(parent)
        self._ua = user_agent.encode('utf-8')

    def createRequest(self, op, request, outgoingData=None):
        request.setRawHeader(QByteArray(b'User-Agent'), QByteArray(self._ua))
        return super().createRequest(op, request, outgoingData)


class UserAuth(QObject):
    """
    Handles user authentication using OAuth2 for Reddit Data Interface.

    This class provides functionality to initialize and manage the OAuth2 authentication process,
    including requesting user authorization, obtaining access tokens, and emitting signals upon
    successful or failed connection.

    :ivar connected: Signal emitted indicating authentication success or failure.
    :type connected: pyqtSignal
    :ivar reddit_utils: Utility object that provides required Reddit Data Interface details such as client ID,
        user agent, redirect URL, and token scopes.
    :type reddit_utils: RedditUtils
    :ivar client_id: The client ID required for Reddit OAuth2.
    :type client_id: str
    :ivar user_agent: The user agent string used in HTTP requests during OAuth2 flow.
    :type user_agent: str
    :ivar redirect_uri: Redirect URI used in the authentication process with Reddit.
    :type redirect_uri: str
    :ivar token_scope: A list of token scopes defining permissions granted during authentication.
    :type token_scope: list[str]
    :ivar authorization_url: URL used for initiating the Reddit authorization process.
    :type authorization_url: QUrl
    :ivar access_url: URL used for obtaining access tokens from Reddit.
    :type access_url: QUrl
    :ivar oauth: Instance of QOAuth2AuthorizationCodeFlow that manages the OAuth2 flow. Initialized
        during the authentication process.
    :type oauth: QOAuth2AuthorizationCodeFlow or None
    """
    connected = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.logger = logging.getLogger(f'DownloaderForReddit.{__name__}')
        self.adapter:PRAWAdapter = RedditAdapterManager().get_adapter(PostDownloadSource.REDDIT)
        self.oauth = None

    def start_oauth(self):
        """
        Starts the OAuth 2.0 authorization process for the application. This involves setting up an authorization flow,
        configuring the required parameters, and initiating the authorization dialog using the appropriate
        web browser. The user is expected to grant access during the process.

        The function utilizes the QOAuth2AuthorizationCodeFlow class to handle the request and response cycle, while
        ensuring the necessary authentication details such as client ID, authorization URL, and access token URL
        are properly configured.

        :return: Instance of QOAuth2AuthorizationCodeFlow configured for the authorization process.
        :rtype: QOAuth2AuthorizationCodeFlow
        """
        # Discard any previous flow so its reply handler releases the callback port
        self._cleanup_oauth()

        manager = UaNetworkAccessManager(self.adapter.get_user_agent(), self)
        # Parented to self: setReplyHandler does not take ownership, so without a parent the
        # handler could be garbage collected as soon as this method returns
        reply_handler = QOAuthHttpServerReplyHandler(8086, self)
        oauth = QOAuth2AuthorizationCodeFlow(
           self.adapter.CLIENT_ID,
           self.adapter.get_authorization_url(),
           self.adapter.get_access_url(),
           manager,
           self
        )

        oauth.granted.connect(self.finish_oauth)
        oauth.error.connect(self._on_oauth_error)
        oauth.requestFailed.connect(self._on_request_failed)

        oauth.authorizeWithBrowser.connect(QDesktopServices.openUrl)
        oauth.setReplyHandler(reply_handler)
        oauth.setScope(" ".join(self.adapter.TOKEN_SCOPES))
        oauth.setUserAgent(self.adapter.get_user_agent())

        # Qt6 takes these as a multi-map (key -> list of values). A bare string is
        # iterated character by character, giving duration=p&duration=e&...
        params = {
            "duration": ["permanent"]
        }

        self.oauth = oauth
        oauth.resourceOwnerAuthorization(self.adapter.get_authorization_url(), params)
        return oauth

    def _cleanup_oauth(self):
        """
        Closes the reply handler (freeing the callback port) and discards the current OAuth flow, if any.

        :return: None
        """
        oauth, self.oauth = self.oauth, None
        if oauth is None:
            return

        handler = oauth.replyHandler()
        if handler is not None:
            handler.close()
            handler.deleteLater()

        manager = oauth.networkAccessManager()
        oauth.deleteLater()
        if manager is not None:
            manager.deleteLater()

    def _fail_oauth(self, message, *args):
        """
        Logs a failure, cleans up the OAuth flow, and reports the failed connection. Does nothing if the flow
        has already been cleaned up, since a single failure can trigger more than one signal.

        :return: None
        """
        if self.oauth is None:
            return
        self.logger.error(message, *args)
        self._cleanup_oauth()
        self.connected.emit(False)

    def _on_oauth_error(self, error, description, uri):
        self._fail_oauth('OAuth error: %s - %s', error, description)

    def _on_request_failed(self, error):
        self._fail_oauth('OAuth request failed: %s', error)

    def finish_oauth(self):
        """
        Handles the finalization of the OAuth process by refreshing tokens, saving the resulting token,
        and emitting the connection status signal.

        :return: None
        """
        if not self.oauth:
            self.connected.emit(False)
            self.logger.error(
                'Failed to create OAuth (QOAuth2AuthorizationCodeFlow) object, cannot finish OAuth process'
            )
            return

        token = self.oauth.refreshToken()
        if not token:
            self.connected.emit(False)
            if self.oauth:
                self.oauth.replyHandler().close()
            self.logger.error(
                'Failed to connect reddit account: OAuth object has no refresh token'
            )
            return

        RedditAdapterManager().save_adapter_token(PostDownloadSource.REDDIT, token)

        if self.oauth:
            self.oauth.replyHandler().close()
        self.connected.emit(True)
        self.logger.info('Successfully connected to reddit account')
