"""
Reddit Data Interface Adapter Manager

This module provides a manager that selects and creates the appropriate RedditAPI
implementation based on the PostDownloadSource configuration.
"""

from DownloaderForReddit.data_interface.reddit_adapter_token import RedditAdapterToken
from DownloaderForReddit.utils.general_utils import dig

from .reddit_data_interface import RedditDataInterface
from .adapters.praw_adapter import PRAWAdapter
from .adapters.arctic_shift_adapter import ArcticShiftAdapter
from .adapters.pull_push_adapter import PullPushAdapter
from ..utils import injector
from ..database.model_enums import PostDownloadSource

class RedditAdapterManager:
    """
    Manager class that handles selection and instantiation of Reddit Data Interface adapters.
    
    This class provides a factory pattern to create the appropriate RedditAPI
    implementation based on the configured PostDownloadSource.
    """

    _instance = None

    _dict_adapters:dict = {
        PostDownloadSource.REDDIT.name: {
            "class": PRAWAdapter,
            "token": RedditAdapterToken("reddit_access", "reddit_access_token")
        },
        PostDownloadSource.ARCTIC_SHIFT.name: {
            "class": ArcticShiftAdapter,
            "token": RedditAdapterToken("arctic_shift_access", "arctic_shift_access_token")
        },
        PostDownloadSource.PULL_PUSH.name: {
            "class": PullPushAdapter,
            "token": RedditAdapterToken("pull_push_access", "pull_push_access_token")
        }
    }

    def __new__(cls):
        """Singleton instance creation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def delete_adapter_token(self, source:PostDownloadSource) -> None:
        token:RedditAdapterToken = self._instance.get_adapter_token(source)()
        token.reset()
        settings_manager = injector.get_settings_manager()
        settings_manager.config['core'][token.get_key_settings_key()] = token.get_key()
        settings_manager.config['core'][token.get_key_settings_token()] = token.get_encrypted()
        setattr(settings_manager, token.get_key_settings_key(), settings_manager.config['core'][token.get_key_settings_key()])
        setattr(settings_manager, token.get_key_settings_token(), settings_manager.config['core'][token.get_key_settings_token()])

    def save_adapter_token(self, source:PostDownloadSource, decrypted:str) -> None:
        token:RedditAdapterToken = self._instance.get_adapter_token(source)()
        token.set(decrypted)
        settings_manager = injector.get_settings_manager()
        settings_manager.config['core'][token.get_key_settings_key()] = token.get_key()
        settings_manager.config['core'][token.get_key_settings_token()] = token.get_encrypted()
        setattr(settings_manager, token.get_key_settings_key(), settings_manager.config['core'][token.get_key_settings_key()])
        setattr(settings_manager, token.get_key_settings_token(), settings_manager.config['core'][token.get_key_settings_token()])

    def get_adapter_token(self, source:PostDownloadSource) -> RedditAdapterToken:
        return dig(self._dict_adapters, source.name, 'token', default=None)

    def get_adapter_class(self, source:PostDownloadSource):
        return dig(self._dict_adapters, source.name, 'class', default=None)

    def get_adapter(self, source:PostDownloadSource) -> RedditDataInterface:
        """
        Get the appropriate RedditDataInterface implementation based on the download source.
        
        Args:
            source: The PostDownloadSource enum value indicating which API to use
            
        Returns:
            An instance of a RedditDataInterface implementation
            
        Raises:
            ValueError: If an unsupported PostDownloadSource is provided
        """
        settings_manager = injector.get_settings_manager()
        class_adapter = self._instance.get_adapter_class(source)
        token:RedditAdapterToken = self._instance.get_adapter_token(source)
        token_key = settings_manager.get('core', token.get_key_settings_key(), None)
        token_value = settings_manager.get('core', token.get_key_settings_token(), None)
        if token.get_key() != token_key or token.get_encrypted() != token_value:
            token.load(token_key, token_value)

        adapter:RedditDataInterface = class_adapter(token)
        return adapter

    def get_data_interface_for_object(self, reddit_object) -> RedditDataInterface:
        """
        Get the appropriate RedditDataInterface implementation for a given Reddit object.
        
        Args:
            reddit_object: A RedditObject (User or Subreddit) from the database
            
        Returns:
            An instance of a RedditDataInterface implementation
        """
        return self.get_adapter(reddit_object.post_download_source)
