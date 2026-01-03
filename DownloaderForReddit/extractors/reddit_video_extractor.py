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
"""

import re

import prawcore
import requests

from .base_extractor import BaseExtractor
from ..core import const
from ..core.errors import Error
from ..utils import reddit_utils, video_merger


class RedditVideoExtractor(BaseExtractor):

    url_key = ['v.redd.it']

    def __init__(self, post, **kwargs):
        super().__init__(post, **kwargs)
        self.post = post
        self.url = None
        self.audio_url = None

    def get_vid_url(self):
        """
        Extracts the video url from the reddit post and determines if the post is a video and will contain an audio
        file.
        """
        try:
            self.url = self.submission.media['reddit_video']['fallback_url']
        except (AttributeError, TypeError):
            self.url = self.submission.url
        if self.url is not None:
            self.get_audio_url()

    def is_gif(self):
        return self.submission.media['reddit_video']['is_gif']

    def extract_content(self):
        if self.settings_manager.download_reddit_hosted_videos:
            try:
                self.submission = self.get_host_submission()
                self.get_vid_url()
                if self.url is not None:
                    video_content = self.get_video_content()

                    if self.audio_url is not None:
                        audio_content = self.get_audio_content()
                        if audio_content is not None and video_content is not None:
                            merge_set = video_merger.MergeSet(
                                video_id=video_content.id,
                                audio_id=audio_content.id,
                                date_modified=self.post.date_posted
                            )
                            video_merger.videos_to_merge.append(merge_set)

                else:
                    message = 'Failed to find acceptable url for download'
                    self.handle_failed_extract(error=Error.FAILED_TO_LOCATE, message=message, log_exception=True,
                                               extractor_error_message=message)
            except prawcore.exceptions.TooManyRequests:
                message = (
                    f'Reddit rate limit reached.  Please wait a few minutes before trying again.\n'
                    f'For more information, please visit the link below\n'
                    f'{const.RATE_LIMIT_DOC_URL}'
                )
                self.handle_failed_extract(error=Error.RATE_LIMIT_ERROR, message=message, extractor_error_message=message,
                                           exc_info=True)

            except prawcore.RequestException:
                message = 'Failed to extract content'
                self.handle_failed_extract(error=Error.FAILED_TO_EXTRACT, message=message, extractor_error_message=message,
                                           exc_info=True)
            except prawcore.ResponseException:
                message = 'Failed to extract content'
                self.handle_failed_extract(error=Error.FAILED_TO_EXTRACT, message=message, extractor_error_message=message,
                                           exc_info=True)
            except Exception:
                message = 'Failed to extract content'
                self.handle_failed_extract(error=Error.FAILED_TO_EXTRACT, message=message, extractor_error_message=message,
                                           exc_info=True)
            except BaseException:
                message = 'Somebody throwing a BaseException. Failed to locate content'
                self.handle_failed_extract(error=Error.FAILED_TO_EXTRACT, message=message, extractor_error_message=message,
                                           exc_info=True)


    def get_video_content(self):
        ext = 'mp4'
        content = self.make_content(self.url, ext, name_modifier='(video)' if self.audio_url is not None else '')
        return content

    def get_audio_url(self):
        """
        Iterates through what I'm sure will be an increasing list of parsers to find a valid audio url. Because not only
        does reddit separate the audio files from its video files when hosting a video, but they also change the path
        to get the audio file about every three months for some reason.
        """
        parsers = [
            lambda url: url.rsplit('/', 1)[0] + '/audio',
            lambda url: re.sub('DASH_[A-z 0-9]+', 'DASH_audio', url)
        ]
        for parser in parsers:
            try:
                url = parser(self.url)
                if self.check_audio_content(url):
                    self.audio_url = url
                    return
            except AttributeError:
                self.logger.error('Failed to get audio link for reddit video.', extra=self.get_log_data())

    def check_audio_content(self, audio_url):
        """
        Checks the extracted audio url to make sure that a valid status code is returned.  Reddit videos are being
        mislabeled by reddit as being videos when they are in fact gifs.  This rectifies the problem by checking that
        the audio link is valid before trying to make content from the audio portion of a video which does not have
        audio.
        :return: True if the audio link is valid, False if not.
        """
        response = requests.head(audio_url)
        return response.status_code == 200

    def get_audio_content(self):
        ext = 'mp3'
        content = self.make_content(self.audio_url, ext, name_modifier='(audio)')
        return content
