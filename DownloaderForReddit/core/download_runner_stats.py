import copy

from DownloaderForReddit.database.models import DownloadSession
from DownloaderForReddit.utils import system_util
from DownloaderForReddit.utils.general_utils import dig


class DownloadRunnerStats:
    """
    A class to track statistics during download sessions.
    
    This class maintains various statistics about the download process including
    session information, rate limiting data, user and subreddit counts, 
    post/comment extraction counts, and content download statistics.
    """

    def __init__(self, dict_data:dict):
        self._dict_data = {}
        self.reset()
        if dict_data:
            self.set_session_count(1)
            self.set_id(dig(dict_data, "id", default=0))
            self.set_stopped(dig(dict_data, "stopped", default=False))
            self.set_session_duration(DownloadRunnerStats.get_session_duration_from_dict(dict_data))
            self.set_user_significant_count(DownloadRunnerStats.get_user_significant_count_from_dict(dict_data))
            self.set_user_total_count(DownloadRunnerStats.get_user_total_count_from_dict(dict_data))
            self.set_subreddit_significant_count(DownloadRunnerStats.get_subreddit_significant_count_from_dict(dict_data))
            self.set_subreddit_total_count(DownloadRunnerStats.get_subreddit_total_count_from_dict(dict_data))
            self.set_comment_extracted_count(DownloadRunnerStats.get_comment_extracted_count_from_dict(dict_data))
            self.set_content_downloaded_count(DownloadRunnerStats.get_content_downloaded_count_from_dict(dict_data))
            self.set_post_extracted_count(DownloadRunnerStats.get_post_extracted_count_from_dict(dict_data))
            self.set_ratelimit_count(DownloadRunnerStats.get_ratelimit_count_from_dict(dict_data))
            self.set_ratelimit_duration(DownloadRunnerStats.get_ratelimit_duration_from_dict(dict_data))
            self.set_post_extraction_error_count(DownloadRunnerStats.get_post_extraction_error_count_from_dict(dict_data))
            self.set_comment_extraction_error_count(DownloadRunnerStats.get_comment_extraction_error_count_from_dict(dict_data))
            self.set_content_error_count(DownloadRunnerStats.get_content_error_count_from_dict(dict_data))

    def reset(self):
        self._dict_data = {
            "id": 0,
            "count": 0,
            "duration": 0.0,
            "stopped": False,
            "ratelimit": {
                "count": 0,
                "duration": 0.0
            },
            "user": {
                "significant": 0,
                "total": 0
            },
            "subreddit": {
                "significant": 0,
                "total": 0
            },
            "post": {
                "extracted": 0,
                "error": 0
            },
            "comment": {
                "extracted": 0,
                "error": 0
            },
            "content": {
                "downloaded": 0,
                "error": 0
            }

        }

    def is_stopped(self) -> bool:
        return dig(self._dict_data, "stopped", default=False)

    def set_stopped(self, stopped:bool):
        self._dict_data["stopped"] = stopped

    def get_id(self) -> int:
        """
        Get the ID of this statistics object.
        
        Returns:
            int: The ID value
        """
        return dig(self._dict_data, "id", default="")

    def set_id(self, id_value: int):
        """
        Set the ID of this statistics object.
        
        Args:
            id_value (int): The ID value to set
        """
        self._dict_data["id"] = id_value

    @staticmethod
    def get_session_count_from_dict(dict_data:dict) -> int:
        return dig(dict_data, "count", default=0)

    def get_session_count(self) -> int:
        """
        Get the number of sessions.
        
        Returns:
            int: The session count
        """
        return DownloadRunnerStats.get_session_count_from_dict(self._dict_data)

    def set_session_count(self, count: int):
        """
        Set the number of sessions.
        
        Args:
            count (int): The session count to set
        """
        self._dict_data["count"] = count

    @staticmethod
    def get_session_duration_from_dict(dict_data:dict) -> dict:
        return dig(dict_data, "duration", default=0.0)

    def get_session_duration(self) -> float:
        """
        Get the total session duration in seconds.
        
        Returns:
            float: The session duration
        """
        return DownloadRunnerStats.get_session_duration_from_dict(self._dict_data)

    def set_session_duration(self, duration: float):
        """
        Set the total session duration in seconds.
        
        Args:
            duration (float): The session duration to set
        """
        self._dict_data["duration"] = duration

    def get_session_duration_time(self) -> str:
        """
        Get the formatted session duration time string.
        
        Returns:
            str: Formatted duration time string
        """
        return system_util.format_duration_full(self.get_session_duration())

    def get_ratelimit_duration_time(self) -> str:
        """
        Get the formatted rate limit duration time string.
        
        Returns:
            str: Formatted duration time string
        """
        return system_util.format_duration_full(self.get_ratelimit_duration())

    @staticmethod
    def get_ratelimit_count_from_dict(dict_data:dict) -> int:
        """
        Get the number of rate limit events.
        
        Returns:
            int: The rate limit count
        """
        return dig(dict_data, "ratelimit", "count", default=0)

    def get_ratelimit_count(self) -> int:
        """
        Get the number of rate limit events.
        
        Returns:
            int: The rate limit count
        """
        return DownloadRunnerStats.get_ratelimit_count_from_dict(self._dict_data)

    def set_ratelimit_count(self, count: int):
        """
        Set the number of rate limit events.
        
        Args:
            count (int): The rate limit count to set
        """
        self._dict_data["ratelimit"]["count"] = count

    @staticmethod
    def get_ratelimit_duration_from_dict(dict_data:dict) -> float:
        """
        Get the total rate limit duration in seconds.
        
        Returns:
            float: The rate limit duration
        """
        return dig(dict_data, "ratelimit", "duration", default=0.0)

    def get_ratelimit_duration(self) -> float:
        """
        Get the total rate limit duration in seconds.
        
        Returns:
            float: The rate limit duration
        """
        return DownloadRunnerStats.get_ratelimit_duration_from_dict(self._dict_data)

    def set_ratelimit_duration(self, duration: float):
        """
        Set the total rate limit duration in seconds.
        
        Args:
            duration (float): The rate limit duration to set
        """
        self._dict_data["ratelimit"]["duration"] = duration

    @staticmethod
    def get_user_significant_count_from_dict(dict_data:dict) -> int:
        """
        Get the count of significant users.
        
        Returns:
            int: The significant user count
        """
        return dig(dict_data, "user", "significant", default=0)

    def get_user_significant_count(self) -> int:
        """
        Get the count of significant users.
        
        Returns:
            int: The significant user count
        """
        return DownloadRunnerStats.get_user_significant_count_from_dict(self._dict_data)

    def set_user_significant_count(self, count: int):
        """
        Set the count of significant users.
        
        Args:
            count (int): The significant user count to set
        """
        self._dict_data["user"]["significant"] = count

    @staticmethod
    def get_user_total_count_from_dict(dict_data:dict) -> int:
        """
        Get the total count of users.
        
        Returns:
            int: The total user count
        """
        return dig(dict_data, "user", "total", default=0)

    def get_user_total_count(self) -> int:
        """
        Get the total count of users.
        
        Returns:
            int: The total user count
        """
        return DownloadRunnerStats.get_user_total_count_from_dict(self._dict_data)

    def set_user_total_count(self, count: int):
        """
        Set the total count of users.
        
        Args:
            count (int): The total user count to set
        """
        self._dict_data["user"]["total"] = count

    @staticmethod
    def get_subreddit_significant_count_from_dict(dict_data:dict) -> int:
        """
        Get the count of significant subreddits.
        
        Returns:
            int: The significant subreddit count
        """
        return dig(dict_data, "subreddit", "significant", default=0)

    def get_subreddit_significant_count(self) -> int:
        """
        Get the count of significant subreddits.
        
        Returns:
            int: The significant subreddit count
        """
        return DownloadRunnerStats.get_subreddit_significant_count_from_dict(self._dict_data)

    def set_subreddit_significant_count(self, count: int):
        """
        Set the count of significant subreddits.
        
        Args:
            count (int): The significant subreddit count to set
        """
        self._dict_data["subreddit"]["significant"] = count

    @staticmethod
    def get_subreddit_total_count_from_dict(dict_data:dict) -> int:
        """
        Get the total count of subreddits.
        
        Returns:
            int: The total subreddit count
        """
        return dig(dict_data, "subreddit", "total", default=0)

    def get_subreddit_total_count(self) -> int:
        """
        Get the total count of subreddits.
        
        Returns:
            int: The total subreddit count
        """
        return DownloadRunnerStats.get_subreddit_total_count_from_dict(self._dict_data)

    def set_subreddit_total_count(self, count: int):
        """
        Set the total count of subreddits.
        
        Args:
            count (int): The total subreddit count to set
        """
        self._dict_data["subreddit"]["total"] = count

    @staticmethod
    def get_post_extracted_count_from_dict(dict_data:dict) -> int:
        """
        Get the number of posts extracted.
        
        Returns:
            int: The post extraction count
        """
        return dig(dict_data, "post", "extracted", default=0)

    def get_post_extracted_count(self) -> int:
        """
        Get the number of posts extracted.
        
        Returns:
            int: The post extraction count
        """
        return DownloadRunnerStats.get_post_extracted_count_from_dict(self._dict_data)

    def set_post_extracted_count(self, count: int):
        """
        Set the number of posts extracted.
        
        Args:
            count (int): The post extraction count to set
        """
        self._dict_data["post"]["extracted"] = count

    @staticmethod
    def get_comment_extracted_count_from_dict(dict_data:dict) -> int:
        """
        Get the number of comments extracted.
        
        Returns:
            int: The comment extraction count
        """
        return dig(dict_data, "comment", "extracted", default=0)

    def get_comment_extracted_count(self) -> int:
        """
        Get the number of comments extracted.
        
        Returns:
            int: The comment extraction count
        """
        return DownloadRunnerStats.get_comment_extracted_count_from_dict(self._dict_data)

    def set_comment_extracted_count(self, count: int):
        """
        Set the number of comments extracted.
        
        Args:
            count (int): The comment extraction count to set
        """
        self._dict_data["comment"]["extracted"] = count

    @staticmethod
    def get_content_downloaded_count_from_dict(dict_data:dict) -> int:
        """
        Get the number of content items downloaded.
        
        Returns:
            int: The content download count
        """
        return dig(dict_data, "content", "downloaded", default=0)

    def get_content_downloaded_count(self) -> int:
        """
        Get the number of content items downloaded.
        
        Returns:
            int: The content download count
        """
        return DownloadRunnerStats.get_content_downloaded_count_from_dict(self._dict_data)

    def set_content_downloaded_count(self, count: int):
        """
        Set the number of content items downloaded.
        
        Args:
            count (int): The content download count to set
        """
        self._dict_data["content"]["downloaded"] = count

    def is_publish_worthy(self, check_duration=False, check_rate_limit=False) -> bool:
        if self.is_stopped():
            return True
        if self.get_content_downloaded_count():
            return True
        if self.get_comment_extracted_count():
            return True
        if self.get_post_extracted_count():
            return True
        if self.get_subreddit_total_count():
            return True
        if self.get_user_total_count():
            return True
        if self.get_subreddit_significant_count():
            return True
        if self.get_user_significant_count():
            return True
        if self.get_post_extraction_error_count():
            return True
        if self.get_comment_extraction_error_count():
            return True
        if self.get_content_error_count():
            return True        
        if check_rate_limit:
            if self.get_ratelimit_duration():
                return True
            if self.get_ratelimit_count():
                return True
        if check_duration:
            if self.get_session_duration():
                return True
        return False

    @staticmethod
    def get_post_extraction_error_count_from_dict(dict_data:dict) -> int:
        return dig(dict_data, "post", "error", default=0)

    @staticmethod
    def get_comment_extraction_error_count_from_dict(dict_data:dict) -> int:
        return dig(dict_data, "comment", "error", default=0)

    @staticmethod
    def get_content_error_count_from_dict(dict_data:dict) -> int:
        return dig(dict_data, "content", "error", default=0)

    def get_post_extraction_error_count(self) -> int:
        return DownloadRunnerStats.get_post_extraction_error_count_from_dict(self._dict_data)
    
    def get_comment_extraction_error_count(self) -> int:
        return DownloadRunnerStats.get_comment_extraction_error_count_from_dict(self._dict_data)

    def get_content_error_count(self) -> int:
        return DownloadRunnerStats.get_content_error_count_from_dict(self._dict_data)

    def set_content_error_count(self, count:int) -> int:
        self._dict_data["content"]["error"] = count

    def set_post_extraction_error_count(self, count:int) -> int:
        self._dict_data["post"]["error"] = count

    def set_comment_extraction_error_count(self, count:int) -> int:
        self._dict_data["comment"]["error"] = count

    def add_session(self, dict_data: dict) -> None:
        self._dict_data["id"] = 0
        self._dict_data["stopped"] = False

        self.set_content_downloaded_count(self.get_content_downloaded_count() + self.get_content_downloaded_count_from_dict(dict_data))
        self.set_comment_extracted_count(self.get_comment_extracted_count() + self.get_comment_extracted_count_from_dict(dict_data))
        self.set_post_extracted_count(self.get_post_extracted_count() + self.get_post_extracted_count_from_dict(dict_data))
        self.set_subreddit_total_count(self.get_subreddit_total_count() + self.get_subreddit_total_count_from_dict(dict_data))
        self.set_user_total_count(self.get_user_total_count() + self.get_user_total_count_from_dict(dict_data))
        self.set_subreddit_significant_count(self.get_subreddit_significant_count() + self.get_subreddit_significant_count_from_dict(dict_data))
        self.set_user_significant_count(self.get_user_significant_count() + self.get_user_significant_count_from_dict(dict_data))
        self.set_ratelimit_duration(self.get_ratelimit_duration() + self.get_ratelimit_duration_from_dict(dict_data))
        self.set_ratelimit_count(self.get_ratelimit_count() + self.get_ratelimit_count_from_dict(dict_data))
        self.set_session_duration(self.get_session_duration() + self.get_session_duration_from_dict(dict_data))
        self.set_session_count(self.get_session_count() + 1)
        self.set_post_extraction_error_count(DownloadRunnerStats.get_post_extraction_error_count_from_dict(dict_data))
        self.set_comment_extraction_error_count(DownloadRunnerStats.get_comment_extraction_error_count_from_dict(dict_data))
        self.set_content_error_count(DownloadRunnerStats.get_content_error_count_from_dict(dict_data))        
        

    def to_dict(self, times:bool=True) -> dict:
        cloned = copy.deepcopy(self._dict_data)
        if times:
            cloned['time'] = self.get_session_duration_time()
            cloned["ratelimit"]['time'] = self.get_ratelimit_duration_time()
        return cloned

    def to_output_string(self, with_id:bool=False) -> str:
        prefix = ""
        if with_id and self.get_id():
            prefix = f' ({self.get_id()})'
        suffix = ""
        if self.is_stopped():
            suffix = " (Stopped)"
            
        return f'Run{prefix}: {self.get_session_count()} for {self.get_session_duration_time()}{suffix}\n' \
                  f'Rate Limit: {self.get_ratelimit_count()} for {self.get_ratelimit_duration_time()}\n'\
                  f'Download Errors: {self.get_content_error_count()}\n' \
                  f'Post Errors: {self.get_post_extraction_error_count()}\n' \
                  f'Comment Errors: {self.get_comment_extraction_error_count()}\n' \
                  f'Download Count: {self.get_content_downloaded_count()}\n' \
                  f'Downloaded Users: {self.get_user_significant_count()}\n' \
                  f'Downloaded Subreddits: {self.get_subreddit_significant_count()}\n' \
                  f'Post Count: {self.get_post_extracted_count()}\n' \
                  f'Comment Count: {self.get_comment_extracted_count()}'

def from_session(dl_session:DownloadSession, stopped:bool=False, post_errors:int=0, comment_errors:int=0, content_errors:int=0) -> DownloadRunnerStats:
    stats:DownloadRunnerStats = DownloadRunnerStats({})
    stats.set_session_count(1)
    stats.set_stopped(stopped)
    stats.set_post_extraction_error_count(post_errors)
    stats.set_comment_extraction_error_count(comment_errors)
    stats.set_content_error_count(content_errors)

    stats.set_id(dl_session.id)
    stats.set_session_duration(dl_session.get_duration())
    stats.set_user_significant_count(dl_session.get_downloaded_user_count())
    stats.set_user_total_count(dl_session.get_downloaded_user_count(significant=False))
    stats.set_subreddit_significant_count(dl_session.get_downloaded_subreddit_count())
    stats.set_subreddit_total_count(dl_session.get_downloaded_subreddit_count(significant=False))
    stats.set_comment_extracted_count(dl_session.get_comment_count())
    stats.set_content_downloaded_count(dl_session.get_downloaded_content_count())
    stats.set_post_extracted_count(dl_session.get_extracted_post_count())
    stats.set_ratelimit_count(dl_session.get_rate_limit_count())
    stats.set_ratelimit_duration(dl_session.get_rate_limit_duration())
    return stats
