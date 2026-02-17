"""SE Daily Flight Deck package."""

from .brief import render_brief
from .config import FlightDeckConfig, load_config
from .dashboard_services import derive_tasks_from_signals
from .models import Signal
from .normalizers import normalize_calendar, normalize_gmail, normalize_slack
from .scoring import score_and_sort
from .storage import Storage

__all__ = [
    "FlightDeckConfig",
    "Signal",
    "Storage",
    "derive_tasks_from_signals",
    "load_config",
    "normalize_calendar",
    "normalize_gmail",
    "normalize_slack",
    "render_brief",
    "score_and_sort",
]
