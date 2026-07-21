"""m03_readability — Readability & Complexity Scoring (deck slide 17).

Scores every English SOP with three standard readability formulas from the
``textstat`` package — Flesch-Kincaid grade, Gunning fog index, and the
Coleman-Liau index — then averages them into a single U.S. grade level per SOP.
An SOP whose mean grade exceeds Grade 12 reads beyond a general operator level
and is flagged. The corpus here is seeded with long-sentence / nominalization
defects, so the flagged share runs high; the scores are computed directly from
the text (no manifest labelling), so the number reflects the real corpus.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

import textstat

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT
from sop_pipeline.core import viz

GRADE_THRESHOLD = 12.0  # end of general-audience (Grade 12) reading level


def _score(text: str) -> tuple[float, float, float]:
    """Return (Flesch-Kincaid grade, Gunning fog, Coleman-Liau) for ``text``."""
    return (
        float(textstat.flesch_kincaid_grade(text)),
        float(textstat.gunning_fog(text)),
        float(textstat.coleman_liau_index(text)),
    )


def _render(rows: list[dict], avg_grade: float, path: Path) -> str:
    """Horizontal bar chart of each SOP's mean grade, worst at top."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    n = len(rows)
    fig, ax = viz.new_fig(9.0, max(6.0, 0.28 * n + 1.6))
    ax.grid(axis="y", visible=False)  # keep only vertical gridlines for grades
    ax.set_axisbelow(True)            # gridlines sit behind the bars

    y = list(range(n))
    values = [r["mean_grade"] for r in rows]
    colors = [viz.BAD if r["flag"] == "above" else viz.GOOD for r in rows]
    ax.barh(y, values, color=colors, height=0.72, zorder=2)

    ax.set_yticks(y)
    ax.set_yticklabels([r["sop_id"] for r in rows])
    ax.invert_yaxis()  # rows are sorted descending → worst (highest) on top

    # Tight limits: just enough headroom for the longest bar's value label.
    ax.set_xlim(0, max(values) * 1.10)
    ax.set_ylim(n - 0.4, -0.8)

    # Reference lines: above the bars so the thresholds read clearly, but below
    # the value labels (which carry an opaque halo) so no digit is struck through.
    ax.axvline(GRADE_THRESHOLD, color=viz.INK, linestyle="--", linewidth=1.2, zorder=3)
    ax.axvline(avg_grade, color=viz.ACCENT, linestyle=":", linewidth=1.6, zorder=3)

    # Value labels at each bar end, on an opaque white patch so the reference
    # lines never cross the digits.
    for yi, v in zip(y, values):
        ax.text(v + 0.30, yi, f"{v:.1f}", va="center", ha="left",
                fontsize=7, color=viz.INK, zorder=5,
                bbox=dict(boxstyle="square,pad=0.15", facecolor=viz.BG,
                          edgecolor="none"))

    # Both reference-line captions use one convention: centred on the line and
    # parked in the margin above the plot area, clear of the lines themselves.
    cap = dict(xycoords=("data", "axes fraction"), textcoords="offset points",
               xytext=(0, 6), fontsize=8, fontweight="bold",
               ha="center", va="bottom", annotation_clip=False)
    ax.annotate("Grade 12", xy=(GRADE_THRESHOLD, 1.0), color=viz.INK, **cap)
    ax.annotate(f"avg {avg_grade:.1f}", xy=(avg_grade, 1.0), color=viz.ACCENT, **cap)

    # Explicit key for the bar colour encoding and the two reference lines,
    # placed in the empty lower-right region so it covers no bar or label.
    handles = [
        Patch(facecolor=viz.GOOD, label="At or below Grade 12"),
        Patch(facecolor=viz.BAD, label="Above Grade 12"),
        Line2D([0], [0], color=viz.INK, linestyle="--", linewidth=1.2,
               label="Grade 12 threshold"),
        Line2D([0], [0], color=viz.ACCENT, linestyle=":", linewidth=1.6,
               label="Corpus average"),
    ]
    leg = ax.legend(handles=handles, loc="lower right", fontsize=8,
                    frameon=True, facecolor=viz.BG, edgecolor=viz.GRID,
                    framealpha=1.0, borderpad=0.8, labelspacing=0.55,
                    handlelength=1.8, borderaxespad=0.8,
                    title="Reading level vs. Grade 12")
    leg.get_title().set_fontsize(8)
    leg.get_title().set_fontweight("bold")
    leg.get_title().set_color(viz.INK)
    leg.set_zorder(6)

    ax.set_xlabel("Mean U.S. reading grade level  (FK / Gunning fog / Coleman-Liau)")
    ax.set_ylabel("SOP")
    ax.set_title("SOP Readability & Complexity — mean grade level per SOP", pad=22)
    viz.finish(ax)
    return viz.save(fig, path)


def run(corpus: Corpus, outdir: Path) -> dict:
    outdir = Path(outdir)

    rows: list[dict] = []
    for sop in corpus.english():  # exclude -ES variants from EN readability scoring
        fk, gf, cl = _score(sop.full_text)
        mean = (fk + gf + cl) / 3.0
        rows.append({
            "sop_id": sop.sop_id,
            "flesch_kincaid": round(fk, 1),
            "gunning_fog": round(gf, 1),
            "coleman_liau": round(cl, 1),
            "mean_grade": round(mean, 1),
            "flag": "above" if mean > GRADE_THRESHOLD else "ok",
        })
    rows.sort(key=lambda r: r["mean_grade"], reverse=True)

    n = len(rows)
    avg_grade = round(statistics.mean(r["mean_grade"] for r in rows), 1)
    avg_fk = round(statistics.mean(r["flesch_kincaid"] for r in rows), 1)
    avg_gf = round(statistics.mean(r["gunning_fog"] for r in rows), 1)
    avg_cl = round(statistics.mean(r["coleman_liau"] for r in rows), 1)
    n_above = sum(1 for r in rows if r["flag"] == "above")
    pct_above = round(100.0 * n_above / n, 1)
    worst = rows[0]["sop_id"]
    best = rows[-1]["sop_id"]

    # --- scores.csv (all SOPs) ---
    csv_path = outdir / "scores.csv"
    fieldnames = ["sop_id", "flesch_kincaid", "gunning_fog", "coleman_liau", "mean_grade", "flag"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # --- chart ---
    png_path = outdir / "readability.png"
    _render(rows, avg_grade, png_path)

    rel_png = str(png_path.relative_to(PROJECT_ROOT))
    rel_csv = str(csv_path.relative_to(PROJECT_ROOT))

    return {
        "module": "m03_readability",
        "title": "Readability & Complexity Scoring",
        "slide": 17,
        "summary": {
            "avg_grade": avg_grade,
            "pct_above_grade12": pct_above,
            "worst_sop": worst,
        },
        "key_findings": [
            f"{n_above}/{n} SOPs ({pct_above}%) read above Grade 12 — beyond a general operator level",
            f"Corpus mean reading grade is {avg_grade} (FK {avg_fk} / fog {avg_gf} / CLI {avg_cl})",
            f"Least readable: {worst} at mean Grade {rows[0]['mean_grade']}",
            f"Most readable: {best} at mean Grade {rows[-1]['mean_grade']}",
            "High grades are driven by long, nominalized sentences (seeded readability defects)",
        ],
        "artifacts": [rel_png, rel_csv],
        "table": rows,
        "table_columns": fieldnames,
    }
