"""Shared matplotlib styling so every module's chart reads as one design system.

Palette is a clinical/quality theme: deep teal primary, amber accent, and a
pass/warn/fail traffic set for status displays. Import and use these helpers
instead of styling each chart from scratch.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless: never try to open a window
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

# ---------------------------------------------------------------------------
# Palette (hex without '#')
# ---------------------------------------------------------------------------
INK = "#16232E"
PRIMARY = "#0B3C5D"      # deep navy-teal
SECONDARY = "#1C7293"    # teal
TERTIARY = "#5AA9C6"     # light teal
ACCENT = "#E8833A"       # amber
GOOD = "#2E7D5B"         # green  (current / pass)
WARN = "#E0A93B"         # amber  (review)
BAD = "#C1442E"          # red    (outdated / fail)
MUTED = "#8A9BA8"
GRID = "#DCE4E9"
BG = "#FFFFFF"
PANEL = "#F4F7F9"

# A sequential ramp (light -> deep teal) for heatmaps.
SEQUENTIAL = ["#EAF2F6", "#C4DCE7", "#8FBFD4", "#5AA9C6", "#2E85AA", "#1C7293", "#0B3C5D"]
# Categorical series for topic/cluster charts.
CATEGORICAL = [
    "#0B3C5D", "#1C7293", "#5AA9C6", "#E8833A", "#2E7D5B",
    "#9C6DAF", "#C1442E", "#E0A93B", "#4C6C8C", "#7DAF9C",
]

STATUS_COLORS = {
    "current": GOOD, "pass": GOOD, "good": GOOD, "ok": GOOD,
    "review": WARN, "warn": WARN, "warning": WARN,
    "outdated": BAD, "fail": BAD, "bad": BAD, "broken": BAD, "error": BAD,
    "unknown": MUTED, "n/a": MUTED,
}


def apply_style() -> None:
    """Apply global rcParams. Call once at the top of a plotting function."""
    plt.rcParams.update({
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "savefig.facecolor": BG,
        "axes.edgecolor": MUTED,
        "axes.linewidth": 0.8,
        "axes.labelcolor": INK,
        "axes.titlecolor": INK,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.7,
        "xtick.color": INK,
        "ytick.color": INK,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "text.color": INK,
        "font.size": 10,
        "figure.dpi": 130,
        "legend.frameon": False,
    })
    # Prefer a clean sans; fall back silently if unavailable.
    for fam in ("Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"):
        if any(fam in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break


def new_fig(w: float = 8.0, h: float = 4.5):
    """Return (fig, ax) with the house style applied."""
    apply_style()
    fig, ax = plt.subplots(figsize=(w, h))
    return fig, ax


def finish(ax) -> None:
    """Trim chartjunk: drop top/right spines, soften remaining ones."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)


def save(fig, path, pad: float = 0.3) -> str:
    """Save a figure and return the path as a string."""
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p, bbox_inches="tight", pad_inches=pad)
    plt.close(fig)
    return str(p)


def status_color(status: str) -> str:
    return STATUS_COLORS.get(str(status).strip().lower(), MUTED)
