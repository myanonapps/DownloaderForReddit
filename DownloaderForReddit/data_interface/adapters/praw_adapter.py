"""
PRAW adapter for the Reddit Data Interface interface.

This module wraps PRAW functionality to match the abstract RedditAPI interface.
"""
from datetime import datetime
import logging
from typing import Any
import praw
import prawcore

from DownloaderForReddit.core import const
from DownloaderForReddit.core.const import RATE_LIMIT_DOC_URL
from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.data_interface.reddit_data_interface import RedditDataInterface, ValidationSet
from DownloaderForReddit.database.model_enums import PostDownloadSource
from DownloaderForReddit.messaging.message import Message

logger = logging.getLogger(f'DownloaderForReddit.{__name__}')
# Configuration values from reddit_utils.py
TOKEN_SCOPES = ['identity', 'mysubreddits', 'subscribe', 'account', 'history', 'read']
TOKEN_DURATION = 'permanent'

CLIENT_ID = 'frGEUVAuHGL2PQ'


class PRAWAdapter(RedditDataInterface):
    """
    Adapter that wraps PRAW to provide the RedditAPI interface.
    
    This class maintains backward compatibility with existing PRAW usage
    while providing a consistent interface for different Reddit Data Interface implementations.
    """

    def __init__(self, token:RedditAdapterToken, download_session=None):
        """
        Initialize the PRAW adapter.
        
        Args:
            token: Optional refresh token for authenticated access
        """
        super().__init__("", token, download_session)
        self._praw = None
        self._source:PostDownloadSource = PostDownloadSource.REDDIT


    def _get_praw_instance(self) -> praw.Reddit:
        """Get or create a Reddit instance."""
        if self._praw is not None:
            return self._praw

        if self._token is not None:
            self._praw = praw.Reddit(
                client_id=CLIENT_ID,
                user_agent=self.get_user_agent(),
                client_secret=None,
                refresh_token=self._token.get_decrypted()
            )
        else:
            self._praw = praw.Reddit(
                client_id=CLIENT_ID,
                user_agent=self.get_user_agent(),
                client_secret=None,
                redirect_uri=self.get_redirect_url()
            )

        return self._praw

    def posts_by_author(self):
        pass   

    def submission(self, id: str) -> Any:
        """
        Get a submission by its ID.
        
        Args:
            id: The Reddit submission ID
            
        Returns:
            Submission object from PRAW
        """
        reddit = self._get_praw_instance()
        return reddit.submission(id=id)

    def redditor(self, name: str) -> Any:
        """
        Get a redditor (user) by name.
        
        Args:
            name: The Reddit username
            
        Returns:
            Redditor object from PRAW
        """
        reddit = self._get_praw_instance()
        return reddit.redditor(name)

    def redditor_by_id(self, user_id: str) -> Any:
        """
        Get a redditor (user) by id.
        
        Args:
            name: The Reddit username
            
        Returns:
            Redditor object from PRAW
        """
        pass
    

    def subreddit(self, name: str) -> Any:
        """
        Get a subreddit by name.
        
        Args:
            name: The subreddit name
            
        Returns:
            Subreddit object from PRAW
        """
        reddit = self._get_praw_instance()
        return reddit.subreddit(name)

    def get_authenticated_user(self) -> str:
        try:
            if not self._get_praw_instance().read_only:
                user = self._get_praw_instance().user.me().name
                return user
        except prawcore.exceptions.TooManyRequests:
            # This error's except clause must be tried first because it is a subclass of prawcore.ResponseException
            logger.error('Too many requests', exc_info=True)
            message = (
                f'Reddit rate limit reached.  Please wait a few minutes before trying again.\n'
                f'For more information, please visit the link below\n'
                f'{RATE_LIMIT_DOC_URL}'
            )
            Message.send_error(message)
        except prawcore.RequestException:
            logger.error('Praw request failed', exc_info=True)
        except prawcore.ResponseException:
            logger.error('Praw response failed', exc_info=True)
        except: # pylint: disable=bare-except
            # Handle unknown exception here to keep the application from completely crashing.
            logger.error('Error checking reddit account', exc_info=True)
        return None

    def check_user_name(self, name) -> ValidationSet:
        try:
            user = self._get_praw_instance().redditor(name)
            # actual name pulled from reddit because capitalization differences may cause problems throughout the app.
            # Creation date is checked first because praw objects are evaluated lazily, and calling user.name first will
            # not send anything to the server and will only return the name as it was supplied.  By getting the creation
            # date first, the redditor object is updated with information supplied by reddit's server.
            created = datetime.fromtimestamp(user.created)
            actual_name = user.name
            return ValidationSet(name=actual_name, date_created=created, reddit_id=user.id, valid=True)
        except (prawcore.exceptions.NotFound, prawcore.exceptions.Redirect, AttributeError):
            return ValidationSet(name=name, date_created=None, reddit_id="", valid=False)
        except prawcore.exceptions.TooManyRequests:
            # This error's except clause must be tried first because it is a subclass of prawcore.ResponseException
            logger.error('Too many requests', exc_info=True)
            message = (
                f'Reddit rate limit reached.  Please wait a few minutes before trying again.\n'
                f'For more information, please visit the link below\n'
                f'{const.RATE_LIMIT_DOC_URL}'
            )
            Message.send_error(message)
            return ValidationSet(name=name, date_created=None, reddit_id="", valid=False)
        except Exception:
            logger.error('Unable to validate user name', extra={'user_name': name}, exc_info=True)
            return ValidationSet(name=name, date_created=None, reddit_id="", valid=False)
        except BaseException:
            logger.error('Somebody is throwing a BaseException. Unable to validate user name', extra={'user_name': name}, exc_info=True)
            return ValidationSet(name=name, date_created=None, reddit_id="", valid=False)

    def check_subreddit_name(self, name) -> ValidationSet:
        try:
            sub = self._get_praw_instance().subreddit(name)
            # actual name pulled from reddit because capitalization differences may cause problems throughout the app
            created = datetime.fromtimestamp(sub.created)
            actual_name = sub.display_name
            return ValidationSet(name=actual_name, date_created=created, reddit_id=sub.id, valid=True)
        except (prawcore.exceptions.NotFound, prawcore.exceptions.Redirect, AttributeError):
            return ValidationSet(name=name, date_created=None, reddit_id="", valid=False)
        except prawcore.exceptions.TooManyRequests:
            # This error's except clause must be tried first because it is a subclass of prawcore.ResponseException
            logger.error('Too many requests', exc_info=True)
            message = (
                f'Reddit rate limit reached.  Please wait a few minutes before trying again.\n'
                f'For more information, please visit the link below\n'
                f'{const.RATE_LIMIT_DOC_URL}'
            )
            Message.send_error(message)
            return ValidationSet(name=name, date_created=None, valid=False)
        except Exception:
            logger.error('Unable to validate subreddit name', extra={'subreddit_name': name}, exc_info=True)
            return ValidationSet(name=name, date_created=None, reddit_id="", valid=False)
        except BaseException:
            logger.error('Somebody is throwing a BaseException. Unable to validate subreddit name', extra={'subreddit_name': name}, exc_info=True)
            return ValidationSet(name=name, date_created=None, reddit_id="", valid=False)

