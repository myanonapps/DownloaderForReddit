"""
PRAW Subreddit adapter for the Reddit Data Interface.

This module wraps PRAW Subreddit functionality to match the abstract AdapterData interface.
"""


from DownloaderForReddit.data_interface.adapter_data import AdapterData
from DownloaderForReddit.database.model_enums import PostDownloadSource
from DownloaderForReddit.utils.general_utils import dig

# Constants for data keys
ID_KEY = "id"
NAME_KEY = "name"
CREATED_UTC_KEY = "created_utc"
CREATED_KEY = "created"

class AdapterSubreddit(AdapterData):
    """
    Adapter that wraps PRAW Subreddit to provide a consistent interface.
    
    This class maintains backward compatibility with existing PRAW Subreddit usage
    while providing a consistent interface for different data adapter implementations.
    """

    def __init__(self, adapter_type:PostDownloadSource, dict_data:dict):
        """
        Initialize the Subreddit adapter.
        
        Args:
            subreddit: The PRAW Subreddit object to wrap
        """
        super().__init__(adapter_type)
        match adapter_type:
            case PostDownloadSource.ARCTIC_SHIFT:
                self.from_arctic_shift(dict_data)
            case PostDownloadSource.PULL_PUSH:
                self.from_pull_push(dict_data)
            case PostDownloadSource.REDDIT:
                pass

    def __getattr__(self, attr):
        if attr == "__iter__":
            return None
        self.logger.error("Invoked the fallback method in '%s' for missing: %s", self.__class__.__name__, attr)
        return None

    def from_pull_push(self, dict_data:dict):
        pass

    def from_arctic_shift(self, dict_data:dict):
        '''
            {
            "data": [
                {
                "_meta": {
                    "earliest_comment": 1393014392,
                    "earliest_post": 1392862403,
                    "num_comments": 389893,
                    "num_comments_updated_at": 1791825490,
                    "num_posts": 44916,
                    "num_posts_updated_at": 1791710798
                },
                "accept_followers": true,
                "accounts_active": null,
                "accounts_active_is_fuzzed": false,
                "active_user_count": null,
                "advertiser_category": "",
                "all_original_content": false,
                "allow_discovery": true,
                "allow_galleries": true,
                "allow_images": false,
                "allow_polls": true,
                "allow_prediction_contributors": false,
                "allow_predictions": false,
                "allow_predictions_tournament": false,
                "allow_talks": false,
                "allow_videogifs": false,
                "allow_videos": false,
                "allowed_media_in_comments": [
                ],
                "banner_background_color": "",
                "banner_background_image": "",
                "banner_img": "",
                "banner_size": null,
                "can_assign_link_flair": false,
                "can_assign_user_flair": false,
                "collapse_deleted_comments": false,
                "comment_contribution_settings": {
                    "allowed_media_types": [
                    "expression"
                    ]
                },
                "comment_score_hide_mins": 0,
                "community_icon": "",
                "community_reviewed": true,
                "created": 1392860936,
                "created_utc": 1392860936,
                "description": "",
                "disable_contributor_requests": false,
                "display_name": "askwtf",
                "display_name_prefixed": "r/askwtf",
                "emojis_custom_size": null,
                "emojis_enabled": false,
                "free_form_reports": true,
                "has_menu_widget": false,
                "header_img": null,
                "header_size": null,
                "header_title": "",
                "hide_ads": false,
                "icon_img": "",
                "icon_size": null,
                "id": "30h5e",
                "is_crosspostable_subreddit": true,
                "is_enrolled_in_new_modmail": null,
                "key_color": "",
                "lang": "en",
                "link_flair_enabled": false,
                "link_flair_position": "",
                "mobile_banner_image": "",
                "name": "t5_30h5e",
                "notification_level": null,
                "original_content_tag_enabled": false,
                "over18": true,
                "prediction_leaderboard_entry_type": 1,
                "primary_color": "",
                "public_description": "",
                "public_traffic": false,
                "quarantine": false,
                "restrict_commenting": false,
                "restrict_posting": true,
                "retrieved_on": 1739562992,
                "should_archive_posts": false,
                "should_show_media_in_comments_setting": false,
                "show_media": true,
                "show_media_preview": true,
                "spoilers_enabled": false,
                "submission_type": "any",
                "submit_link_label": "",
                "submit_text": "",
                "submit_text_html": "",
                "submit_text_label": "",
                "subreddit_type": "public",
                "subscribers": 126485,
                "suggested_comment_sort": null,
                "title": "",
                "url": "",
                "user_can_flair_in_sr": null,
                "user_flair_background_color": null,
                "user_flair_css_class": null,
                "user_flair_enabled_in_sr": false,
                "user_flair_position": "right",
                "user_flair_richtext": [
                ],
                "user_flair_template_id": null,
                "user_flair_text": null,
                "user_flair_text_color": null,
                "user_flair_type": "text",
                "user_has_favorited": false,
                "user_is_banned": false,
                "user_is_contributor": false,
                "user_is_moderator": false,
                "user_is_muted": false,
                "user_is_subscriber": false,
                "user_sr_flair_enabled": null,
                "user_sr_theme_enabled": true,
                "wiki_enabled": null,
                "wls": null
                }
            ]
            }
        '''
        name = dig(dict_data, "name", default="")
        setattr(self, NAME_KEY, dig(dict_data, "title", default=name))
        setattr(self, ID_KEY, dig(dict_data, "id", default=""))
        setattr(self, CREATED_KEY, dig(dict_data, "created", default=""))
        setattr(self, CREATED_UTC_KEY, dig(dict_data, "created_utc", default=""))

