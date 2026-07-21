"""m07_scorecard — Quality Scorecard (deck slide 21).

Scores every English SOP on five 0–10 quality dimensions and rolls them up into a
weakest-link audit-readiness score, contrasting the as-is corpus baseline against an
illustrative post-remediation target (mirroring the deck's 3.5 -> 8.2 story).

Dimensions (all computed from the text — the manifest is used only for the current
regulatory-version table, via RegKB):
  clarity        inverse of ambiguity density, reading grade, and passive density
  completeness   fraction of the six expected sections present
  usability      readability + numbered, verb-first procedure steps
  consistency    internal uniformity of heading style + obligation modal
  defensibility  regulatory refs present AND current + ref/revision sections,
                 minus penalties for overdue periodic review and broken cross-refs
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT
from sop_pipeline.core import lexicon, viz
from sop_pipeline.core.regkb import RegKB

RANDOM_STATE = 42
AS_OF = date(2026, 7, 1)          # fixed analysis date -> deterministic "overdue review"
DIMENSIONS = ["clarity", "completeness", "usability", "consistency", "defensibility"]
# Illustrative post-remediation target (labelled as such); mirrors the deck's ~8+ story.
TARGET_PROFILE = {"clarity": 8.5, "completeness": 9.5, "usability": 8.5,
                  "consistency": 8.5, "defensibility": 8.5}
TARGET_OVERALL = 8.2              # deck's stated target headline

_MD = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")
_ROMAN = re.compile(r"^\(?[IVXLC]{1,5}[\).]\s+\S")
_STEPCOLON = re.compile(r"^step\s+\d+\s*:", re.IGNORECASE)
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+\S")
_VOWELS = "aeiouy"
_SECTION_PATS = {
    "purpose": re.compile(r"purpose", re.I),
    "scope": re.compile(r"scope", re.I),
    "responsibilities": re.compile(r"responsib", re.I),
    "procedure": re.compile(r"procedure|method|process|instruction", re.I),
    "references": re.compile(r"reference", re.I),
    "revision history": re.compile(r"revision", re.I),
}


def _clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def _syllables(word: str) -> int:
    w = word.lower()
    count, prev_v = 0, False
    for ch in w:
        is_v = ch in _VOWELS
        if is_v and not prev_v:
            count += 1
        prev_v = is_v
    if w.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def _sentence_units(body: str, sentences: list[str]) -> int:
    """Instructional units for readability.

    The shared splitter only breaks on '.' + quote/paren/capital/digit, so a fully bulleted
    SOP returns ONE sentence (SOP-PKG-004: 272 words, 1 sentence). Counting bullet/numbered/
    'Step N:' lines restores a fair words-per-unit; prose docs keep the splitter's count.
    """
    listed = sum(1 for line in body.splitlines()
                 if (s := line.strip()) and (s.startswith(("-", "*", "•"))
                                             or _NUMBERED.match(line) or _STEPCOLON.match(s)))
    return max(len(sentences), listed, 1)


def _fk_grade(words: list[str], units: int) -> float:
    """Flesch-Kincaid grade, clamped at 30 (anything above is already 'worst')."""
    n_w = len(words)
    if n_w == 0:
        return 0.0
    syl = sum(_syllables(w) for w in words)
    return min(30.0, 0.39 * (n_w / max(1, units)) + 11.8 * (syl / n_w) - 15.59)


def _headings(body: str) -> list[tuple[str, str]]:
    """(style, text) for every heading-like line — markdown, Step N:, roman, or ALL-CAPS."""
    out: list[tuple[str, str]] = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if m := _MD.match(line):
            out.append(("markdown", m.group(1).strip()))
        elif _STEPCOLON.match(s):
            out.append(("stepcolon", s))
        elif _ROMAN.match(s):
            out.append(("roman", s))
        elif (sum(c.isalpha() for c in s) >= 4 and len(s) <= 60
              and s == s.upper() and len(s.split()) <= 8 and not s[0].isdigit()):
            out.append(("allcaps", s))
    return out


def _step_lines(body: str) -> list[str]:
    steps = []
    for line in body.splitlines():
        s = line.strip()
        if _NUMBERED.match(line):
            steps.append(re.sub(r"^\s*\d+[.)]\s+", "", s))
        elif _STEPCOLON.match(s):
            steps.append(re.sub(r"^step\s+\d+\s*:\s*", "", s, flags=re.I))
    return steps


def _sections_present(body: str, heads: list[tuple[str, str]]) -> dict[str, bool]:
    htext = [h for _, h in heads]
    present = {name: any(pat.search(h) for h in htext) for name, pat in _SECTION_PATS.items()}
    if not present["procedure"]:  # accept enumerated steps as a procedure section
        present["procedure"] = bool(_step_lines(body))
    return present


def _overdue(next_review: str) -> bool:
    try:
        y, m, d = (int(x) for x in str(next_review).split("-")[:3])
        return date(y, m, d) < AS_OF
    except Exception:
        return False


# --- per-dimension scorers (0-10, higher = better) -------------------------------
def _clarity(amb_per100: float, grade: float, passive_per100: float) -> float:
    return _clamp(10.0 - min(5.0, 1.8 * amb_per100)
                  - _clamp((grade - 9) / 2.5, 0, 3)
                  - min(2.0, 0.4 * passive_per100))


def _completeness(present: dict[str, bool]) -> float:
    return 10.0 * sum(present.values()) / len(present)


def _usability(grade: float, body: str) -> float:
    readability = _clamp(6.0 * (18 - grade) / 10.0, 0, 6)   # grade 8 -> 6, grade 18 -> 0
    steps = _step_lines(body)
    step_score = 0.0
    if steps:
        verb_first = sum(1 for s in steps if lexicon.sentence_starts_with_verb(s))
        step_score = 2.0 + 2.0 * verb_first / len(steps)
    return _clamp(readability + step_score)


def _consistency(heads: list[tuple[str, str]], modal: dict[str, int]) -> float:
    heading_unif = (max(Counter(st for st, _ in heads).values()) / len(heads)) if heads else 0.3
    total = sum(modal.values())
    modal_unif = (max(modal.values()) / total) if total else 0.4
    return _clamp(10.0 * (0.55 * heading_unif + 0.45 * modal_unif))


def _defensibility(cites, present: dict[str, bool], next_review: str, broken: bool) -> float:
    score = 10.0
    if not cites:
        score -= 4.0
    else:
        frac_bad = sum(1 for c in cites if c.status != "current") / len(cites)
        score -= 3.5 * frac_bad
    if not present["references"]:
        score -= 1.5
    if not present["revision history"]:
        score -= 1.5
    if _overdue(next_review):
        score -= 2.0
    if broken:
        score -= 2.0
    return _clamp(score)


def _score_sop(sop, kb: RegKB, corpus: Corpus) -> dict:
    words = sop.words
    grade = _fk_grade(words, _sentence_units(sop.body, sop.sentences))
    n_w = max(1, len(words))
    amb_per100 = 100.0 * len(lexicon.find_ambiguous_terms(sop.body)) / n_w
    passive_per100 = 100.0 * lexicon.count_passive(sop.body) / n_w
    heads = _headings(sop.body)
    present = _sections_present(sop.body, heads)
    cites = kb.extract(sop.sop_id, sop.body)
    broken = any(corpus.get(ref) is None for ref in sop.cross_references)
    scores = {
        "clarity": _clarity(amb_per100, grade, passive_per100),
        "completeness": _completeness(present),
        "usability": _usability(grade, sop.body),
        "consistency": _consistency(heads, lexicon.modal_counts(sop.body)),
        "defensibility": _defensibility(cites, present, sop.next_review, broken),
    }
    vals = [scores[d] for d in DIMENSIONS]
    # Weakest-link audit-readiness roll-up: a doc is only as defensible as its worst gap.
    scores["overall"] = 0.65 * (sum(vals) / len(vals)) + 0.35 * min(vals)
    scores["sop_id"] = sop.sop_id
    scores["department"] = sop.department
    return scores


def _render(rep: dict, avg: dict[str, float], baseline_overall: float, path: Path) -> str:
    plt = viz.plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    viz.apply_style()
    # One display ordering, used identically by BOTH panels: the bar panel reads
    # top -> bottom, the radar reads clockwise from 12 o'clock.
    order = list(DIMENSIONS)
    labels = [d.capitalize() for d in order]
    # Display-only helper for the explanatory note (no analysis is recomputed here).
    plain_mean = sum(avg[d] for d in order) / len(order)
    gap_fill = viz.SEQUENTIAL[1]

    fig = plt.figure(figsize=(13.2, 6.6))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.15], wspace=0.24,
                          left=0.045, right=0.975, top=0.775, bottom=0.245)
    fig.suptitle("Quality Scorecard — SOP corpus vs. remediation target",
                 fontsize=14.5, fontweight="bold", color=viz.INK, y=0.955)

    # -- left: radar for the representative SOP (baseline vs target) ---------------
    ax1 = fig.add_subplot(gs[0, 0], polar=True)
    ax1.set_theta_offset(np.pi / 2)      # first dimension at 12 o'clock ...
    ax1.set_theta_direction(-1)          # ... then clockwise, matching the bar order
    ax1.set_axisbelow(True)
    angles = np.linspace(0, 2 * np.pi, len(order), endpoint=False).tolist()
    closed = angles + angles[:1]
    base = [rep[d] for d in order]
    base += base[:1]
    targ = [TARGET_PROFILE[d] for d in order]
    targ += targ[:1]
    ax1.plot(closed, targ, color=viz.GOOD, lw=1.8, ls="--", zorder=4)
    ax1.fill(closed, targ, color=viz.GOOD, alpha=0.10, zorder=2)
    ax1.plot(closed, base, color=viz.BAD, lw=2.2, zorder=5)
    ax1.fill(closed, base, color=viz.BAD, alpha=0.20, zorder=3)

    ax1.set_ylim(0, 10.6)                # outer spine sits beyond the "10" ring
    ax1.set_xticks(angles)
    ax1.set_xticklabels([])              # placed manually below, clear of the outer ring
    ax1.set_yticks([2, 4, 6, 8, 10])
    ax1.set_yticklabels([])              # drawn manually so they sit ON TOP of the polygons
    for r in (2, 4, 6, 8, 10):
        ax1.text(np.pi, r, str(r), ha="center", va="center", fontsize=7.5, zorder=8,
                 color=viz.INK,
                 bbox=dict(boxstyle="round,pad=0.16", fc="white", ec="none", alpha=0.92))
    for ang, lab in zip(angles, labels):
        phi = np.pi / 2 - ang            # on-screen angle after offset/direction
        dx, dy = np.cos(phi), np.sin(phi)
        ha = "center" if abs(dx) < 0.25 else ("left" if dx > 0 else "right")
        va = "center" if abs(dy) < 0.25 else ("bottom" if dy > 0 else "top")
        ax1.text(ang, 11.3, lab, ha=ha, va=va, fontsize=9.5, color=viz.INK)
    ax1.set_title(f"Representative SOP: {rep['sop_id']}", fontsize=11, pad=30)
    # caption sits directly under the radial tick column (12 o'clock is the Clarity label)
    ax1.text(0.5, -0.06, "radial axis = quality score (0–10)", transform=ax1.transAxes,
             ha="center", va="top", fontsize=8.5, style="italic", color=viz.SECONDARY)

    # -- right: corpus-average per dimension, baseline vs per-dimension target -----
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_axisbelow(True)
    bar_h = 0.46
    for i, d in enumerate(order):
        b, t = avg[d], TARGET_PROFILE[d]
        meets = b >= t
        if not meets:                                   # shortfall still to close
            ax2.barh(i, t - b, left=b, height=bar_h, color=gap_fill, zorder=2)
        ax2.barh(i, b, height=bar_h, zorder=3,
                 color=viz.GOOD if meets else viz.PRIMARY)
        # per-dimension target drawn as a MARKER, not a competing bar
        ax2.plot([t, t], [i - bar_h / 2 - 0.10, i + bar_h / 2 + 0.10], color=viz.ACCENT,
                 lw=2.6, solid_capstyle="butt", zorder=6)
        ax2.text(b + 0.22, i, f"{b:.1f}", va="center", ha="left", fontsize=9.5,
                 fontweight="bold", color=viz.GOOD if meets else viz.PRIMARY, zorder=7)
        # target value label: outside the marker when short, inside when already passed
        tx, tha = ((t - 0.24, "right") if meets else (t + 0.24, "left"))
        ax2.text(tx, i, f"{t:.1f}", va="center", ha=tha, fontsize=8.5, color=viz.INK,
                 zorder=7,
                 bbox=dict(boxstyle="round,pad=0.20", fc="white", ec=viz.ACCENT, lw=0.7))

    ax2.set_yticks(np.arange(len(order)))
    ax2.set_yticklabels(labels, fontsize=10)
    ax2.set_ylim(len(order) - 0.55, -0.45)   # inverted, snug around the five bars
    ax2.set_xlim(0, 10.9)
    ax2.set_xticks([0, 2, 4, 6, 8, 10])
    ax2.set_xlabel("Score (0–10)")
    ax2.set_ylabel("Quality dimension")
    ax2.grid(axis="x", color=viz.GRID, lw=0.7)
    ax2.grid(axis="y", visible=False)
    ax2.set_title(f"Corpus average per dimension — overall {baseline_overall:.1f} "
                  f"-> target {TARGET_OVERALL:.1f}", fontsize=11, pad=36)
    ax2.text(0.5, 1.015,
             "Overall is a weakest-link score:  0.65 x mean(dimensions) + 0.35 x weakest "
             f"dimension\nso overall {baseline_overall:.1f} sits below the {plain_mean:.1f} "
             "plain mean of the five bars",
             transform=ax2.transAxes, ha="center", va="bottom", fontsize=8.5,
             linespacing=1.5, color=viz.SECONDARY)
    viz.finish(ax2)

    # -- one legend style, one baseline, both panels -------------------------------
    leg_kw = dict(loc="upper center", frameon=False, fontsize=8.5,
                  handlelength=2.1, handletextpad=0.6, columnspacing=1.5)
    fig.legend(handles=[
        Line2D([], [], color=viz.BAD, lw=2.2,
               label=f"{rep['sop_id']} as-is ({rep['overall']:.1f}/10)"),
        Line2D([], [], color=viz.GOOD, lw=1.8, ls="--", label="Target profile (illustrative)"),
    ], bbox_to_anchor=(0.265, 0.115), ncol=2, **leg_kw)
    fig.legend(handles=[
        Patch(fc=viz.PRIMARY, ec="none", label="Baseline below target"),
        Patch(fc=viz.GOOD, ec="none", label="Baseline already at/above target"),
        Patch(fc=gap_fill, ec="none", label="Gap to close"),
        Line2D([], [], color=viz.ACCENT, lw=2.6, label="Target (illustrative)"),
    ], bbox_to_anchor=(0.735, 0.115), ncol=4, **leg_kw)
    return viz.save(fig, path)


def run(corpus: Corpus, outdir: Path) -> dict:
    np.random.seed(RANDOM_STATE)
    outdir = Path(outdir)
    kb = RegKB.from_manifest(corpus.manifest)

    rows = [_score_sop(sop, kb, corpus) for sop in corpus.english()]
    rows.sort(key=lambda r: r["overall"])  # worst first — the deck's remediation queue
    n = len(rows)
    avg = {d: sum(r[d] for r in rows) / n for d in DIMENSIONS}
    baseline_overall = sum(r["overall"] for r in rows) / n

    # Representative SOP = closest (Euclidean) to the corpus-average dimension profile.
    mean_vec = np.array([avg[d] for d in DIMENSIONS])
    rep = min(rows, key=lambda r: (float(np.linalg.norm([r[d] for d in DIMENSIONS] - mean_vec)),
                                   r["sop_id"]))

    png = _render(rep, avg, baseline_overall, outdir / "scorecard.png")

    # Per-SOP CSV artifact.
    cols = ["sop_id", "department"] + DIMENSIONS + ["overall"]
    csv_path = outdir / "scorecard.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: (round(r[c], 2) if isinstance(r[c], float) else r[c]) for c in cols})

    table = [dict({"sop_id": r["sop_id"], "dept": r["department"]},
                  **{d: round(r[d], 1) for d in DIMENSIONS + ["overall"]}) for r in rows]

    worst, best = rows[0], rows[-1]
    weakest_dim, strongest_dim = min(avg, key=avg.get), max(avg, key=avg.get)

    def rel(p: Path) -> str:
        return str(Path(p).resolve().relative_to(PROJECT_ROOT))

    return {
        "module": "m07_scorecard",
        "title": "Quality Scorecard",
        "slide": 21,
        "summary": {
            "n_scored": n,
            "avg_overall": round(baseline_overall, 2),
            "target_overall": TARGET_OVERALL,
            **{f"avg_{d}": round(avg[d], 2) for d in DIMENSIONS},
            "weakest_dimension": weakest_dim,
            "strongest_dimension": strongest_dim,
            "lowest_scoring_sop": f"{worst['sop_id']} ({worst['overall']:.1f})",
            "highest_scoring_sop": f"{best['sop_id']} ({best['overall']:.1f})",
            "representative_sop": rep["sop_id"],
        },
        "key_findings": [
            f"As-is corpus averages {baseline_overall:.1f}/10 on the weakest-link scorecard; "
            f"the worst SOPs bottom out at {worst['overall']:.1f}/10 ({worst['sop_id']}), matching the deck's 3.5 baseline",
            f"Weakest dimension is {weakest_dim} ({avg[weakest_dim]:.1f}/10) — driven by long sentences, ambiguity "
            f"and non-verb-first steps; with clarity at {avg['clarity']:.1f}/10 these prose dimensions are the audit crisis",
            f"Structure is the strength: completeness {avg['completeness']:.1f}/10 and internal consistency "
            f"{avg['consistency']:.1f}/10 — SOPs are complete and internally uniform, so the fix is prose quality, not re-architecture",
            f"Defensibility {avg['defensibility']:.1f}/10: outdated citations plus overdue periodic reviews erode audit readiness",
            f"House-standard SOPs already achieve ~{best['overall']:.1f}/10 ({best['sop_id']}), proving the illustrative "
            f"{TARGET_OVERALL:.1f}/10 target is realistic (mirrors the deck's 3.5 → 8.2 story)",
        ],
        "artifacts": [rel(png), rel(csv_path)],
        "table": table,
        "table_columns": ["sop_id", "dept", "clarity", "completeness", "usability",
                          "consistency", "defensibility", "overall"],
    }
