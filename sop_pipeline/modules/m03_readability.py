"""m03_readability — Readability & Complexity Scoring (deck slide 17).

Scores every English SOP with three standard readability formulas from the
``textstat`` package — Flesch-Kincaid grade, Gunning fog index, and the
Coleman-Liau index — then averages them into a single U.S. grade level per SOP.
An SOP whose mean grade exceeds Grade 12 reads beyond a general operator level
and is flagged. The corpus here is seeded with long-sentence / nominalization
defects, so the flagged share runs high; the scores are computed directly from
the text (no manifest labelling), so the number reflects the real corpus.

Scope is ``per_sop``: alongside the corpus rollup and bar chart, every English
SOP gets its own reading-grade assessment (``per_sop``) plus a small text
scorecard in ``outdir/sops/``. No per-SOP image is rendered — the corpus bar
chart already plots each document individually.
"""

from __future__ import annotations

import csv
import re
import statistics
from pathlib import Path

import textstat

from sop_pipeline.core.corpus import SOP, Corpus, PROJECT_ROOT
from sop_pipeline.core import viz

GRADE_THRESHOLD = 12.0  # end of general-audience (Grade 12) reading level
WARN_CEILING = 16.0     # 12 < grade <= 16 -> warn; above 16 -> fail
MIN_SCOREABLE_WORDS = 40  # below this a grade score is statistical noise

_METRIC_LABELS = {
    "flesch_kincaid": "Flesch-Kincaid grade",
    "gunning_fog": "Gunning fog index",
    "coleman_liau": "Coleman-Liau index",
}
# What an unusually high score on each formula points at, in remediation terms.
_METRIC_DRIVERS = {
    "flesch_kincaid": "long sentences carrying polysyllabic words",
    "gunning_fog": "long sentences packed with three-syllable+ terms",
    "coleman_liau": "long words and dense character-per-word load",
}


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


_TERMINAL_PUNCT_RE = re.compile(r"[.!?](?=\s|$)")


def _sentence_count(sop: SOP) -> int:
    """Sentence count that survives bullet-list SOPs.

    ``SOP.sentences`` only splits when the next fragment starts with a capital
    or quote, so an all-bullet document ("- Step one.\\n- Step two.") collapses
    to a single sentence. Fall back to counting terminal punctuation — the same
    signal textstat uses — and take whichever is larger.
    """
    return max(len(sop.sentences), len(_TERMINAL_PUNCT_RE.findall(sop.body)), 1)


def _band(mean_grade: float) -> tuple[str, str]:
    """Return (status, plain-language reading level) for a mean grade."""
    if mean_grade <= GRADE_THRESHOLD:
        return "pass", "high-school level or below"
    if mean_grade <= WARN_CEILING:
        return "warn", "college level"
    return "fail", "graduate level"


def _delta_phrase(delta: float) -> str:
    """'6.1 grades above' / '1.4 grades below' / 'exactly at' the floor."""
    if abs(delta) < 0.05:
        return "exactly at"
    return f"{abs(delta):.1f} grades {'above' if delta > 0 else 'below'}"


def _write_card(sop: SOP, entry: dict, n_sent: int, rank: int, n: int,
                avg_grade: float, path: Path) -> None:
    """Write this SOP's readability scorecard as a small markdown file."""
    s = entry["summary"]
    lines = [
        f"# {sop.sop_id} — {sop.title}",
        "",
        f"{sop.department_name} ({sop.department}) · version {sop.version or 'n/a'}",
        "Readability & Complexity Scoring (m03, deck slide 17)",
        "",
        f"**Status: {entry['status'].upper()}** — mean Grade {s['mean_grade']} "
        f"vs a Grade {GRADE_THRESHOLD:.0f} floor target",
        "",
        "| Metric | Grade | vs Grade 12 |",
        "| --- | --- | --- |",
    ]
    for r in entry["table"]:
        lines.append(f"| {r['metric']} | {r['grade']} | {r['vs_grade12']:+.1f} |")
    lines += [
        "",
        "## Findings",
        *[f"- {f}" for f in entry["findings"]],
        "",
        f"Corpus context: rank {rank} of {n} (least readable first); "
        f"corpus mean Grade {avg_grade}; "
        f"{s['words_per_sentence']} words per sentence across {n_sent} sentences.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _assess(sop: SOP, row: dict, rank: int, n: int, avg_grade: float,
            sops_dir: Path) -> dict:
    """Build one SOP's per_sop entry and write its scorecard artifact."""
    mean = row["mean_grade"]
    delta = round(mean - GRADE_THRESHOLD, 1)
    n_sent = _sentence_count(sop)
    wps = round(len(sop.words) / n_sent, 1)
    rel_card = str((sops_dir / f"{sop.sop_id}.md").relative_to(PROJECT_ROOT))

    summary = {
        "flesch_kincaid": row["flesch_kincaid"],
        "gunning_fog": row["gunning_fog"],
        "coleman_liau": row["coleman_liau"],
        "mean_grade": mean,
        "grades_vs_floor": delta,  # signed: + is above the Grade-12 floor
        "words_per_sentence": wps,
        "rank": f"{rank} of {n} (least readable first)",
    }
    table = [
        {"metric": _METRIC_LABELS[k], "grade": row[k],
         "vs_grade12": round(row[k] - GRADE_THRESHOLD, 1)}
        for k in ("flesch_kincaid", "gunning_fog", "coleman_liau")
    ]
    table.append({"metric": "Mean grade", "grade": mean, "vs_grade12": delta})

    # Too little prose to score meaningfully — still emit an entry (contract rule 1).
    if len(sop.words) < MIN_SCOREABLE_WORDS:
        summary["flag"] = "not scored — too little prose"
        entry = {
            "summary": summary,
            "findings": [
                f"{sop.sop_id} carries only {len(sop.words)} words of body text — "
                f"below the {MIN_SCOREABLE_WORDS}-word floor for a reliable "
                f"reading-grade score, so no readability judgement is made.",
            ],
            "artifacts": [rel_card],
            "table": table,
            "status": "n/a",
        }
        _write_card(sop, entry, n_sent, rank, n, avg_grade, sops_dir / f"{sop.sop_id}.md")
        return entry

    status, level = _band(mean)
    summary["flag"] = f"{_delta_phrase(delta)} Grade {GRADE_THRESHOLD:.0f}"

    implication = {
        "pass": (
            "An operator reading at a high-school level can execute this SOP as "
            "written — no readability remediation needed before floor use."
        ),
        "warn": (
            "On the floor this costs re-reads: steps at college reading level slow "
            "execution and invite paraphrasing. Splitting the "
            f"{wps}-word average sentence and swapping nominalizations for verbs "
            "would clear Grade 12."
            if wps >= 20 else
            "On the floor this costs re-reads: steps at college reading level slow "
            f"execution and invite paraphrasing. Sentences already average {wps} "
            "words, so the load is vocabulary rather than length — plain-word "
            "substitutions would clear Grade 12."
        ),
        "fail": (
            "At graduate reading level the document is effectively unusable at the "
            "point of use — operators will work from memory or a local cheat sheet "
            "instead of the controlled text, which is a deviation and data-integrity "
            "risk. Priority candidate for imperative-voice rewrite."
        ),
    }[status]

    # Which formula runs hottest tells the rewriter what to attack first.
    driver_key = max(_METRIC_LABELS, key=lambda k: row[k])
    findings = [
        f"{sop.sop_id} reads at mean Grade {mean} ({level}) — "
        f"{_delta_phrase(delta)} the Grade-12 floor target.",
        implication,
        f"Formula spread: FK {row['flesch_kincaid']} / fog {row['gunning_fog']} / "
        f"CLI {row['coleman_liau']}; {_METRIC_LABELS[driver_key]} runs highest, "
        f"pointing at {_METRIC_DRIVERS[driver_key]}.",
    ]

    entry = {
        "summary": summary,
        "findings": findings,
        "artifacts": [rel_card],
        "table": table,
        "status": status,
    }
    _write_card(sop, entry, n_sent, rank, n, avg_grade, sops_dir / f"{sop.sop_id}.md")
    return entry


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

    # --- per-SOP assessments (one entry per English SOP, none omitted) ---
    sops_dir = outdir / "sops"
    sops_dir.mkdir(parents=True, exist_ok=True)
    by_id = {r["sop_id"]: r for r in rows}
    rank_of = {r["sop_id"]: i + 1 for i, r in enumerate(rows)}  # rows are worst-first
    per_sop = {
        sid: _assess(corpus[sid], by_id[sid], rank_of[sid], n, avg_grade, sops_dir)
        for sid in sorted(by_id)  # stable, id-ordered keys
    }
    n_fail = sum(1 for e in per_sop.values() if e["status"] == "fail")
    n_warn = sum(1 for e in per_sop.values() if e["status"] == "warn")
    n_pass = sum(1 for e in per_sop.values() if e["status"] == "pass")

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
            f"Per-SOP verdicts: {n_pass} pass (<=12), {n_warn} warn (12-16), {n_fail} fail (>16)",
        ],
        "artifacts": [rel_png, rel_csv],
        "table": rows,
        "table_columns": fieldnames,
        "scope": "per_sop",
        "per_sop": per_sop,
    }
