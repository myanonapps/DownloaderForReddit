from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap, QPainter, QPen

STATES = ('disabled', 'inactive', 'new')  # in priority order: the first state that applies wins

DEFAULT_COLORS = {
    'disabled': (200, 60, 60),
    'inactive': (140, 140, 140),
    'new': (60, 160, 60)
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
        self._blank_icon = None

    def setting(self, name, default=None):
        return getattr(self.settings_manager, name, default)

    @staticmethod
    def has_state(reddit_object, state):
        if state == 'disabled':
            return not reddit_object.download_enabled
        if state == 'inactive':
            return not reddit_object.active
        return bool(reddit_object.new)

    def colorized(self, state):
        return bool(self.setting(f'colorize_{state}_reddit_objects', False))

    def iconized(self, state):
        return bool(self.setting(f'iconize_{state}_reddit_objects', False))

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
        shown = [state for state in STATES if self.iconized(state)]
        if not shown:
            return None
        for state in shown:
            if self.has_state(reddit_object, state):
                return self.state_icon(state)
        return self.blank()

    def reset(self):
        """Forgets the icons that were made.  Call this after the settings that affect them have changed."""
        self._icons.clear()
        self._blank_icon = None

    def state_icon(self, state):
        icon = self._icons.get(state)
        if icon is None:
            path = self.setting(f'{state}_reddit_object_icon')
            icon = QIcon(path) if path else self.draw_icon(state)
            self._icons[state] = icon
        return icon

    def blank(self):
        if self._blank_icon is None:
            self._blank_icon = QIcon(self.new_pixmap())
        return self._blank_icon

    def new_pixmap(self):
        pixmap = QPixmap(self.ICON_SIZE, self.ICON_SIZE)
        pixmap.fill(Qt.GlobalColor.transparent)
        return pixmap

    def draw_icon(self, state):
        """
        Draws the default icon of the state in its display color:  a ring with a slash for disabled, a plain ring for
        inactive and a solid dot for new.
        """
        size = self.ICON_SIZE
        margin = size // 5
        diameter = size - 2 * margin
        r, g, b = self.state_rgb(state)
        color = QColor(r, g, b, 255)

        pixmap = self.new_pixmap()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color)
        pen.setWidth(max(size // 8, 1))
        painter.setPen(pen)
        if state == 'new':
            painter.setBrush(color)
        painter.drawEllipse(margin, margin, diameter, diameter)
        if state == 'disabled':
            painter.drawLine(margin + diameter // 5, margin + diameter - diameter // 5,
                             margin + diameter - diameter // 5, margin + diameter // 5)
        painter.end()
        return QIcon(pixmap)
