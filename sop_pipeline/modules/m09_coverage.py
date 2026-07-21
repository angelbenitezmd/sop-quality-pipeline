"""m09_coverage — Coverage Gap Analysis (deck slide 23).

Compares the *actual* number of English SOPs the site maintains per regulatory
topic area against the *expected band* declared in
``manifest['coverage_requirements']['topics']``. Each topic is classified as:

    absent            actual == 0                (missing topic — e.g. Dispensing)
    over-documented   actual > expected_max      (redundant sprawl — e.g. Cleaning)
    under-documented  actual < expected_min      (thin coverage)
    adequate          expected_min <= actual <= expected_max

The chart is a diverging horizontal bar: one bar per topic for the actual count,
with the expected band drawn as a shaded reference region, colored by status.
"""

from __future__ import annotations

import csv
import random
from collections import Counter
from pathlib import Path

import matplotlib.patches as mpatches

from sop_pipeline.core.corpus import PROJECT_ROOT, Corpus
from sop_pipeline.core import viz

RANDOM_STATE = 42


def _classify(actual: int, exp_min: int, exp_max: int) -> str:
    """Bucket an actual count against its expected band. Absent wins over under."""
    if actual == 0:
        return "absent"
    if actual > exp_max:
        return "over-documented"
    if actual < exp_min:
        return "under-documented"
    return "adequate"


# Status -> bar color. Per spec: over=BAD, under/absent=WARN, adequate=GOOD.
_COLOR = {
    "over-documented": viz.BAD,
    "under-documented": viz.WARN,
    "absent": viz.WARN,
    "adequate": viz.GOOD,
}


def run(corpus: Corpus, outdir: Path) -> dict:
    random.seed(RANDOM_STATE)  # determinism guard (no stochastic step, but explicit)

    topics = corpus.manifest.get("coverage_requirements", {}).get("topics", [])

    # Actual EN SOPs per department (exclude -ES translated variants).
    counts = Counter(s.department for s in corpus.english())

    rows: list[dict] = []
    for t in topics:
        dept = t["dept"]
        actual = counts.get(dept, 0)
        exp_min, exp_max = int(t["expected_min"]), int(t["expected_max"])
        rows.append({
            "topic": t["topic"],
            "dept": dept,
            "actual": actual,
            "expected_min": exp_min,
            "expected_max": exp_max,
            "status": _classify(actual, exp_min, exp_max),
        })

    over = [r["topic"] for r in rows if r["status"] == "over-documented"]
    under = [r["topic"] for r in rows if r["status"] == "under-documented"]
    absent = [r["topic"] for r in rows if r["status"] == "absent"]
    adequate = [r["topic"] for r in rows if r["status"] == "adequate"]

    png_path = _plot(rows, outdir)

    # Extra machine-readable artifact.
    csv_path = outdir / "coverage.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["topic", "dept", "actual",
                                           "expected_min", "expected_max", "status"])
        w.writeheader()
        w.writerows(rows)

    rel = lambda p: str(Path(p).relative_to(PROJECT_ROOT))

    return {
        "module": "m09_coverage",
        "title": "Coverage Gap Analysis",
        "slide": 23,
        "summary": {
            "topics_evaluated": len(rows),
            "english_sops": len(corpus.english()),
            "over_documented": over,
            "under_documented": under,
            "absent": absent,
            "adequate_count": len(adequate),
            "gaps_total": len(under) + len(absent),
        },
        "key_findings": _findings(rows, over, under, absent),
        "artifacts": [rel(png_path), rel(csv_path)],
        "table": rows,
        "table_columns": ["topic", "dept", "actual", "expected_min",
                          "expected_max", "status"],
    }


def _plot(rows: list[dict], outdir: Path) -> str:
    """Horizontal actual-vs-band chart; bars colored by coverage status."""
    n = len(rows)
    fig, ax = viz.new_fig(9.5, 0.62 * n + 2.2)

    ys = list(range(n))
    # Tight x-limit: stop at the largest value actually drawn (plus a hair of
    # breathing room) instead of padding a whole empty unit onto the right.
    xdata = max([r["actual"] for r in rows] + [r["expected_max"] for r in rows])
    xmax = xdata + 0.12

    bar_h = 0.52  # band and bar share one height so the band reads as one strip

    for y, r in zip(ys, rows):
        # Expected band: a shaded reference strip at exactly the bar's height,
        # sitting behind the bar so the two read as a single continuous band.
        ax.barh(y, r["expected_max"] - r["expected_min"], left=r["expected_min"],
                height=bar_h, color=viz.GRID, edgecolor="none", zorder=1)
        # Actual count bar, colored by status.
        color = _COLOR[r["status"]]
        if r["actual"] > 0:
            ax.barh(y, r["actual"], height=bar_h, color=color, zorder=3)
        # Band outline drawn on top so the expected range stays legible even
        # where a long bar (e.g. an over-documented topic) covers it.
        ax.barh(y, r["expected_max"] - r["expected_min"], left=r["expected_min"],
                height=bar_h, facecolor="none", edgecolor=viz.MUTED,
                linewidth=0.9, zorder=5)
        # Absent topics have no bar at all — say so explicitly rather than
        # leaving a stray zero-width glyph at the origin.
        if r["actual"] == 0:
            ax.text(0.10, y, "0 — no SOP exists", va="center", ha="left",
                    fontsize=8, fontweight="bold", color=viz.BAD, zorder=6,
                    bbox=dict(boxstyle="round,pad=0.28", facecolor="#FAE8E4",
                              edgecolor=viz.BAD, linewidth=0.8))

    # Value + band annotations live in the right margin, OUTSIDE the axes, so
    # they can never be overlapped by the legend or by the bars themselves.
    for y, r in zip(ys, rows):
        ax.text(1.015, y, f"{r['actual']}   (band {r['expected_min']}–{r['expected_max']})",
                transform=ax.get_yaxis_transform(), va="center", ha="left",
                fontsize=8, color=viz.INK, clip_on=False)

    ax.set_yticks(ys)
    ax.set_yticklabels([f"{r['topic']}  ({r['dept']})" for r in rows], fontsize=8)
    ax.set_ylim(n - 0.5, -0.5)  # first manifest topic at the top, no dead space
    ax.set_xlim(0, xmax)
    ax.set_xticks(list(range(0, xdata + 1)))
    ax.set_xlabel("Number of English SOPs on file")
    ax.set_ylabel("Regulatory topic area  (department)", labelpad=10)
    ax.set_title("Coverage Gap Analysis — Actual SOPs vs. Expected Band (Slide 23)",
                 pad=34)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_axisbelow(True)  # gridlines behind the bars and bands

    legend = [
        mpatches.Patch(facecolor=viz.GRID, edgecolor=viz.MUTED, linewidth=0.9,
                       label="Expected band"),
        mpatches.Patch(color=viz.GOOD, label="Adequate"),
        mpatches.Patch(color=viz.WARN, label="Under-documented"),
        mpatches.Patch(color=viz.BAD, label="Over-documented"),
    ]
    ax.legend(handles=legend, loc="lower left", bbox_to_anchor=(0.0, 1.005),
              fontsize=8, ncol=4, columnspacing=1.4, handlelength=1.5,
              handletextpad=0.6, borderaxespad=0.0)

    viz.finish(ax)
    return viz.save(fig, outdir / "coverage.png")


def _findings(rows: list[dict], over: list[str], under: list[str],
              absent: list[str]) -> list[str]:
    out: list[str] = []
    by_topic = {r["topic"]: r for r in rows}
    for t in absent:
        r = by_topic[t]
        out.append(f"ABSENT: {t} ({r['dept']}) has 0 SOPs vs {r['expected_min']}–{r['expected_max']} expected — no documented procedure.")
    for t in over:
        r = by_topic[t]
        out.append(f"Over-documented: {t} ({r['dept']}) has {r['actual']} SOPs vs {r['expected_min']}–{r['expected_max']} expected — consolidation candidate.")
    for t in under:
        r = by_topic[t]
        out.append(f"Under-documented: {t} ({r['dept']}) has {r['actual']} SOPs vs {r['expected_min']}–{r['expected_max']} expected.")
    out.append(f"{len(absent) + len(under)} of {len(rows)} topics fall below their expected coverage band.")
    return out[:6]
