import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap

from DownloaderForReddit.core.const import DISABLED_OBJECT, INACTIVE_OBJECT, NEW_OBJECT, RESOURCES, SUBREDDIT_OBJECT, USER_OBJECT

STATES = (DISABLED_OBJECT, INACTIVE_OBJECT, NEW_OBJECT)  # in priority order: the first state that applies wins

ACTIVE_OBJECT = "active"

DEFAULT_COLORS = {
    DISABLED_OBJECT: (200, 60, 60),
    INACTIVE_OBJECT: (140, 140, 140),
    NEW_OBJECT: (60, 160, 60)
}

ICONS = {
    USER_OBJECT: {
        DISABLED_OBJECT: QIcon(os.path.join(RESOURCES, "images", "user_disabled.svg")),
        INACTIVE_OBJECT: QIcon(os.path.join(RESOURCES, "images", "user_nonactive.svg")),
        NEW_OBJECT: QIcon(os.path.join(RESOURCES, "images", "user_new.svg")),
        ACTIVE_OBJECT: QIcon(os.path.join(RESOURCES, "images", "user_active.svg")),
    },
    SUBREDDIT_OBJECT: {
        DISABLED_OBJECT: QIcon(os.path.join(RESOURCES, "images", "forum_disabled.svg")),
        INACTIVE_OBJECT: QIcon(os.path.join(RESOURCES, "images", "forum_nonactive.svg")),
        NEW_OBJECT: QIcon(os.path.join(RESOURCES, "images", "forum_new.svg")),
        ACTIVE_OBJECT: QIcon(os.path.join(RESOURCES, "images", "forum_active.svg")),
    }
}

class RedditObjectStateDisplay:
    """
    Decides how the state of a reddit object (disabled, inactive or new) is shown in a list.  A state can be shown as
    colored text, as an icon, as both, or not at all, and each state is configured separately with these settings:

        colorize_<state>_reddit_objects     True to color the text of reddit objects in that state
        <state>_reddit_object_display_color  the (r, g, b) of that color; it is also the color of the default icon
        iconize_<state>_reddit_objects      True to show an icon next to reddit objects in that state
        <state>_reddit_object_icon          optional path (a file or a Qt resource such as ':/icons/new.png') of the icon
                                            to use instead of the default one that is drawn

    where <state> is disabled, inactive or new.  Settings that do not exist count as off (or unset), so a settings
    manager that only has the colorize settings behaves exactly as it always has.  Color and icon are worked out
    separately: each uses the first state, in the order above, that applies to the reddit object and has that way of
    showing it turned on.

    The model should call color() for Qt.ItemDataRole.ForegroundRole and icon() for Qt.ItemDataRole.DecorationRole.
    """

    ICON_SIZE = 32

    def __init__(self, settings_manager):
        self.settings_manager = settings_manager
        self._icons = {}
        self._blank_icon = QIcon(self.new_pixmap())

    def setting(self, name, default=None):
        return getattr(self.settings_manager, name, default)

    @staticmethod
    def has_state(reddit_object, state):
        if state == DISABLED_OBJECT:
            return not reddit_object.download_enabled
        if state == INACTIVE_OBJECT:
            return not reddit_object.active
        return bool(reddit_object.new)

    def colorized(self, state):
        return bool(self.setting(f'colorize_{state}_reddit_objects', False))

    def state_rgb(self, state):
        rgb = self.setting(f'{state}_reddit_object_display_color')
        return tuple(rgb) if rgb else DEFAULT_COLORS[state]

    def color(self, reddit_object):
        """The QColor for the text of the reddit object, or None for the default text color."""
        for state in STATES:
            if self.colorized(state) and self.has_state(reddit_object, state):
                r, g, b = self.state_rgb(state)
                return QColor(r, g, b, 255)
        return None

    def icon(self, reddit_object):
        """
        The QIcon to show next to the reddit object, or None if no state is shown as an icon.  When some state is shown
        as an icon, reddit objects that are in none of those states get a blank icon so that all the names line up.
        """
        if not bool(self.setting('iconize_reddit_objects', True)):
            return self.blank()
        if not reddit_object.download_enabled:
            return ICONS[reddit_object.object_type][DISABLED_OBJECT]
        if not reddit_object.active:
            return ICONS[reddit_object.object_type][INACTIVE_OBJECT]
        if reddit_object.new:
            return ICONS[reddit_object.object_type][NEW_OBJECT]
        return ICONS[reddit_object.object_type][ACTIVE_OBJECT]

    def blank(self):
        return self._blank_icon

    def new_pixmap(self):
        pixmap = QPixmap(self.ICON_SIZE, self.ICON_SIZE)
        pixmap.fill(Qt.GlobalColor.transparent)
        return pixmap
