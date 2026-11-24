from typing import Optional, Union

from DownloaderForReddit.core.const import USER_OBJECT

from . import injector, TokenParser, system_util
from ..database.models import Post, Content, Comment
from ..database.export_models import ImportedMessage


class FilenameGenerator:

    """
    Provides functionality to generate filenames and directory paths based on given Reddit objects, handling duplicates,
    custom save paths, and naming methods.

    This class initializes and sets up the appropriate Reddit object, including posts and comments. It constructs
    title-based tokens and safely generates file paths by considering naming conventions, custom save paths, and save
    structures.

    :ivar settings_manager: The settings manager instance used to get configuration details for saving directories.
    :type settings_manager: SettingsManager
    :ivar post: The associated post object, extracted from the provided object.
    :type post: Post
    :ivar reddit_object: The significant Reddit object belonging to the post.
    :type reddit_object: RedditObject
    :ivar comment: The associated comment object, if applicable.
    :type comment: Comment
    :ivar is_duplicate: Flag indicating whether the object is a duplicate.
    :type is_duplicate: bool
    """

    def __init__(self, obj: Union[Post, Content, Comment, ImportedMessage], is_duplicate: bool = False):
        """
        :param obj: What a file is named for: a post, a comment, an imported message, or content found in one of them.
        :type obj: Union[Post, Content, Comment, ImportedMessage]
        :param is_duplicate: Whether the name is for a duplicate, which uses the duplicate naming settings.
        :type is_duplicate: bool
        """
        self.settings_manager = injector.get_settings_manager()
        self.post = None
        self.reddit_object = None
        self.comment = None
        self.message: Optional[ImportedMessage] = None
        self.is_duplicate = is_duplicate
        self.setup(obj)

    def setup(self, obj: Union[Post, Content, Comment, ImportedMessage]) -> None:
        """
        Configures internal state based on the provided object type. It handles several types of input objects and
        sets the corresponding attributes such as post, comment, and reddit_object.

        :param obj: The object to be used for configuration. It can be an instance of Comment, Content, or other types
                    containing a 'post' or 'significant_reddit_object' attribute.
        :type obj: Union[Comment, Content, Any]
        """
        if isinstance(obj, ImportedMessage):
            self._setup_message(obj)
        elif isinstance(obj, Content) and obj.post is None and obj.message is not None:
            self._setup_message(obj.message)
        elif isinstance(obj, Comment):
            self.comment = obj
            self.post = obj.post
            self.reddit_object = self.post.significant_reddit_object
        elif isinstance(obj, Content):
            self.post = obj.post
            self.reddit_object = self.post.significant_reddit_object
            self.comment = None
        else:
            self.post = obj
            self.reddit_object = obj.significant_reddit_object
            self.comment = None

    def _setup_message(self, message: ImportedMessage) -> None:
        """
        Names files for an imported message's content with the settings of the message's author, as a post's content
        is named with its significant reddit object's settings: the post naming method, save structure and custom post
        save path.  Folder tokens such as '%[author_name]' name the author, so each author's media goes to that
        author's own folder.
        :param message: The message.
        :type message: ImportedMessage
        """
        self.message = message
        self.post = None
        self.comment = None
        self.reddit_object = message.significant_reddit_object

    @property
    def title_obj(self) -> Union[Post, Comment, ImportedMessage]:
        """
        Provides a property to return the object that file names are made from.

        :return: The comment if one is set, otherwise the message if one is set, otherwise the post.
        :rtype: Union[Post, Comment, ImportedMessage]
        """
        if self.comment is not None:
            return self.comment
        if self.message is not None:
            return self.message
        return self.post

    def make_title(self) -> str:
        """
        Generate a title string by parsing tokens from the title object with the relevant data.

        :return: Parsed title string resulting from token processing
        """
        token_string = self._get_name_token_string()
        return TokenParser.parse_tokens(self.title_obj, token_string)

    def _get_name_token_string(self) -> str:
        """
        Constructs and returns a token string indicating the naming method of the Reddit object's associated entity.

        The naming method is determined by inspecting the object attributes. If a comment is associated, the naming
        corresponds to a comment-specific method. If the object is flagged as a duplicate, the naming is adjusted
        accordingly. Finally, a default naming method is used in all other cases.

        :return: A token string for the naming method based on the properties of the Reddit object
        """
        if self.comment is not None:
            return self.reddit_object.comment_naming_method
        elif self.is_duplicate:
            return self.reddit_object.duplicate_naming_method
        else:
            return self.reddit_object.post_download_naming_method

    def make_dir_path(self):
        """
        Generates a cleaned and correctly formatted directory path by combining base path and sub path constructed
        from tokens and object attributes.

        :return: A cleaned string representing the full directory path, ensuring it ends as a directory path.
        """
        token_string = self._get_dir_token_string()
        sub_path = TokenParser.parse_tokens(self.title_obj, token_string)
        clean_sub_path = system_util.clean_path(sub_path, ends_with_dir=True)
        base_path = self._get_base_path()
        combined_path = system_util.join_path(base_path, clean_sub_path)
        return combined_path

    def _get_dir_token_string(self) -> str:
        """
        Returns the token string used to generate the directory path based on what type title object is being used.

        It is possible for title objects to also be duplicates, which should take precedence.  `is_duplicate` is
        considered first, followed by comment, then the result defaults to the post save structure.
        :return: The token string used to generate the directory path for the title object.
        """
        if self.is_duplicate:
            return self.reddit_object.duplicate_save_structure
        elif self.comment is not None:
            return self.reddit_object.comment_save_structure
        else:
            return self.reddit_object.post_save_structure

    def _get_base_path(self) -> str:
        """
        Determine the base path to be used for saving operations.

        This method determines the base path by checking if there is a custom path set. If a custom path is provided,
        it will use that; otherwise, it defaults to returning a path based on the Reddit object type (e.g., user or
        subreddit) and the relevant global SettingsManager settings.

        :returns: The appropriate base path for saving files as a string.
        """
        custom_path = self._get_custom_path()
        if custom_path is not None and custom_path != '':
            return custom_path
        else:
            if self.reddit_object.object_type == USER_OBJECT:
                return self.settings_manager.user_save_directory
            else:
                return self.settings_manager.subreddit_save_directory

    def _get_custom_path(self) -> Optional[str]:
        """
        Returns the custom path to be used based on if the class has a comment set or not.
        :return: The custom path to be used, if one exists, or None.
        """
        if self.comment is not None:
            return self.reddit_object.custom_comment_save_path
        else:
            return self.reddit_object.custom_post_save_path
