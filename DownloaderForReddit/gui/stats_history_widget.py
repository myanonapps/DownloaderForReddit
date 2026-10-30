"""Statistics strip: a pinned "Cumulative" column plus the last N runs, newest first.

Stats only exist once a run has finished, so a run column is added when the run ends
(add_run) and nothing is shown for a run while it is in progress.

Layout (row labels and the Cumulative column never scroll; the runs scroll sideways):

    | Row labels | Cumulative || Last run | Run before last | ... |
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from DownloaderForReddit.core.download_runner_stats import DownloadRunnerStats
from DownloaderForReddit.persistence.settings_manager import SettingsManager
from DownloaderForReddit.utils import injector

# (key, row label)
STAT_ROWS = [
    ("download_count", "Content Count/Error"),
    ("downloaded_users", "Downloaded Users"),
    ("downloaded_subreddits", "Downloaded Subreddits"),
    ("post_count", "Post Count/Error"),
    ("comment_count", "Comment Count/Error"),
    ("rate_limit", "Rate Limit"),
    ("run_time", "Run Time"),
]

# Shown in the Cumulative column at startup and after clear().
DEFAULT_VALUES = {
    "run_time": "0 for 0 secs",
    "rate_limit": "0 for 0 secs",
    "download_count": "0 / 0",
    "downloaded_users": "0",
    "downloaded_subreddits": "0",
    "post_count": "0 / 0",
    "comment_count": "0 / 0",
}

ROW_HEIGHT = 26
HEADER_HEIGHT = 30
COLUMN_WIDTH = 130
FLAG_GLYPH = "\u26A0"
FLAG_COLOR = "#b45f06"

# Row and column captions (the header cells): fill, divider lines and padding.
HEADER_BG = "#dfe7f1"
HEADER_BORDER = "#c3cfdd"
HEADER_PADDING = 8
CELL_BORDER = "#e1e6ed"      # thin line under every data cell
TABLE_STYLE = f"""
QTableWidget::item {{
    border: none;
    border-bottom: 1px solid {CELL_BORDER};
    padding: 0px {HEADER_PADDING}px;
}}
QHeaderView::section {{
    background-color: {HEADER_BG};
    border: none;
    border-right: 1px solid {HEADER_BORDER};
    border-bottom: 1px solid {HEADER_BORDER};
    padding: 0px {HEADER_PADDING}px;
}}
QTableCornerButton::section {{
    background-color: {HEADER_BG};
    border: none;
    border-right: 1px solid {HEADER_BORDER};
    border-bottom: 1px solid {HEADER_BORDER};
}}
"""


def format_stats(stats: DownloadRunnerStats, cumulative: bool) -> dict[str, str]:
    """Turn a stats object into display strings, using the same figures as to_output_string().

    In a single run's column the session count is always 1, so Run Time shows just the
    duration. In the Cumulative column it keeps the "N for duration" form.
    """
    duration = stats.get_session_duration_time()
    run_time = f"{stats.get_session_count()} for {duration}" if cumulative else str(duration)
    return {
        "run_time": run_time,
        "rate_limit": f"{stats.get_ratelimit_count()} for {stats.get_ratelimit_duration_time()}",
        "download_count": f"{str(stats.get_content_downloaded_count())} / {str(stats.get_content_error_count())}",
        "downloaded_users": str(stats.get_user_significant_count()),
        "downloaded_subreddits": str(stats.get_subreddit_significant_count()),
        "post_count": f"{str(stats.get_post_extracted_count())} / {str(stats.get_post_extraction_error_count())}",
        "comment_count": f"{str(stats.get_comment_extracted_count())} / {str(stats.get_comment_extraction_error_count())}",
    }


@dataclass
class StatsHistoryRun:
    ended: datetime
    values: dict[str, str] = field(default_factory=dict)   # snapshot taken when the run ended
    session_id: int | str = 0
    stopped: bool = False


class StatsHistoryWidget(QWidget):
    def __init__(self, parent: QWidget | None = None, max_runs: int = 10):
        super().__init__(parent)
        self._runs: deque[StatsHistoryRun] = deque(maxlen=max_runs)   # index 0 is the newest run
        self.settings_manager:SettingsManager = injector.get_settings_manager()
        
        self.cumulative_table = self._make_table()
        self.runs_table = self._make_table()

        # Pinned table: row labels (vertical header) plus the single Cumulative column.
        pinned = self.cumulative_table
        pinned.setColumnCount(1)
        pinned.setVerticalHeaderLabels([label for _, label in STAT_ROWS])
        pinned.setHorizontalHeaderLabels(["Cumulative"])
        pinned.horizontalHeader().setDefaultSectionSize(COLUMN_WIDTH)
        pinned.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        metrics = pinned.verticalHeader().fontMetrics()      # bold font, set in _make_table
        label_width = max(metrics.horizontalAdvance(label) for _, label in STAT_ROWS) + 2 * HEADER_PADDING + 4
        pinned.verticalHeader().setFixedWidth(label_width)
        body_height = HEADER_HEIGHT + ROW_HEIGHT * len(STAT_ROWS)
        pinned.setFixedSize(label_width + COLUMN_WIDTH, body_height)

        # Scrolling table: one column per run, no row labels of its own.
        runs = self.runs_table
        runs.verticalHeader().setVisible(False)
        runs.horizontalHeader().setDefaultSectionSize(COLUMN_WIDTH)
        runs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)   # reserved, so no height jump
        runs.setFixedHeight(body_height + runs.horizontalScrollBar().sizeHint().height())

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(pinned, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(divider)
        layout.addWidget(runs, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._show_cumulative(DEFAULT_VALUES)

    # ---- public API -------------------------------------------------------------

    def add_run(self, run: DownloadRunnerStats, cumulative: DownloadRunnerStats | None = None,
                ended_at: datetime | None = None) -> None:
        """Call once when a run finishes.

        run         - the finished run's stats object
        cumulative  - the updated cumulative stats object (omit to leave Cumulative as is)
        ended_at    - defaults to now; shown in the column header

        The values are copied into strings immediately, so later changes to (or a reset of)
        the stats objects do not alter what is already shown.
        """
        self._runs.appendleft(StatsHistoryRun(
            ended=ended_at or datetime.now(),
            values=format_stats(run, cumulative=False),
            session_id=run.get_id(),
            stopped=bool(run.is_stopped()),
        ))
        if cumulative is not None:
            self.set_cumulative(cumulative)
        self._render_runs()
        self.runs_table.horizontalScrollBar().setValue(0)

    def set_cumulative(self, stats: DownloadRunnerStats) -> None:
        """Show a cumulative stats object in the pinned column."""
        self._show_cumulative(format_stats(stats, cumulative=True))

    def clear(self, clear_runs: bool = True) -> None:
        """Reset Cumulative to zero; also forget the run history unless clear_runs is False."""
        self._show_cumulative(DEFAULT_VALUES)
        if clear_runs:
            self._runs.clear()
            self._render_runs()

    def set_max_runs(self, max_runs: int) -> None:
        """Change how many runs are kept (the oldest are dropped if the new limit is smaller)."""
        self._runs = deque(list(self._runs)[:max_runs], maxlen=max_runs)
        self._render_runs()

    # ---- internals --------------------------------------------------------------

    @staticmethod
    def _make_table() -> QTableWidget:
        table = QTableWidget()
        table.setAlternatingRowColors(True)
        table.setRowCount(len(STAT_ROWS))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setShowGrid(False)
        table.setFrameShape(QFrame.Shape.NoFrame)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.horizontalHeader().setFixedHeight(HEADER_HEIGHT)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setHighlightSections(False)
        table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.verticalHeader().setHighlightSections(False)

        for header in (table.horizontalHeader(), table.verticalHeader()):
            font = header.font()
            font.setBold(True)
            header.setFont(font)
        table.setStyleSheet(TABLE_STYLE)
        return table

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _show_cumulative(self, values: dict[str, str]) -> None:
        for row, (key, _) in enumerate(STAT_ROWS):
            self.cumulative_table.setItem(row, 0, self._cell(values.get(key, "")))

    def _render_runs(self) -> None:
        table = self.runs_table
        table.setColumnCount(len(self._runs))
        for col, run in enumerate(self._runs):
            title = f"{run.session_id}"
            if run.stopped:
                title += f" {FLAG_GLYPH}"
            header = QTableWidgetItem(title)

            if col == 0:
                tip = "Last run"
            elif col == 1:
                tip = "Run before the last"
            else:
                tip = f"{col} runs before the last"
            tip += f"\nEnded {run.ended.strftime(self.settings_manager.datetime_display_format)}"
            if run.stopped:
                tip += "\nThis run was stopped before it finished, so these counts may be incomplete."
                header.setForeground(QBrush(QColor(FLAG_COLOR)))
            header.setToolTip(tip)
            table.setHorizontalHeaderItem(col, header)

            for row, (key, _) in enumerate(STAT_ROWS):
                table.setItem(row, col, self._cell(run.values.get(key, "")))
