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

import os


DATABASE_NAME = 'dfr.db'
IMAGE_EXT = ('jpg', 'jpeg', 'png', 'jpe')
GIF_EXT = ('gif', 'gifv', 'webm')
VID_EXT = ('mp4', 'wmv', 'avi', 'mpg', 'divx')
TEXT_EXT = ('txt', 'html')
ANIMATED_EXT = VID_EXT + GIF_EXT
ALL_EXT = IMAGE_EXT + GIF_EXT + VID_EXT
FIRST_POST_EPOCH = 1119537833

RESOURCES = os.path.abspath('Resources/')
SUPPORTED_SITES_FILE = os.path.join(RESOURCES, 'supported_video_sites.txt')
TIMEOUT_INCREMENT = 0.25
RATE_LIMIT_DOC_URL = 'https://github.com/MalloyDelacroix/DownloaderForReddit/wiki/The-Ongoing-Impact-of-Reddits-API-Rate-Limits'

USER_OBJECT = 'USER'
SUBREDDIT_OBJECT = 'SUBREDDIT'

DISABLED_OBJECT = 'disabled'
INACTIVE_OBJECT = 'inactive'
NEW_OBJECT = 'new'

SHOW_SCHEDULE = 'SHOW'
SHOW_ACTIVE_SCHEDULE = 'ONLY_WHEN_ACTIVE'
DONT_SHOW_SCHEDULE = 'DO_NOT_SHOW'

DEFAULT_REDDIT_OBJECT_COLORS = {
    DISABLED_OBJECT: (200, 60, 60),
    INACTIVE_OBJECT: (140, 140, 140),
    NEW_OBJECT: (60, 160, 60)
}

ERROR_TEXT_COLOR = (220, 50, 50)

NO_VALUE_OPERATORS = ('is_null', 'not_null')