"""m11_style — Style & Structure Standardization (deck slide 25).

Every department writes its SOPs in a different house dialect: Cleaning shouts in
ALL-CAPS and says "shall", QC buries steps in Roman-numeral academic prose, MFG
narrates "the operator will...", Packaging bullets everything as "responsible for".
Only ENV/DOC use the actual house standard (markdown headings, numbered verb-first
steps, the obligation word "must").

For each EN SOP this module DETECTS the observed style from the text — heading
style, dominant modal, verb-first step %, and passive rate — then flags deviation
from the house standard. The manifest's ``style_profile`` is carried only as a
ground-truth validation label; every number below is computed from the prose.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
from matplotlib.patches import Rectangle

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT
from sop_pipeline.core import lexicon, viz

# Numbered / "Step N:" / bulleted list lines — the "step lines" whose first word
# we test for a strong imperative. The leading marker is stripped (group "txt").
STEP_RE = re.compile(r"^\s*(?:step\s+\d+\s*[:.\)]|\d+[.\)]|[-*•])\s+(?P<txt>.+\S)\s*$", re.IGNORECASE)

MODALS = ["must", "shall", "should", "will", "responsible for"]  # "must" = house
VERB_FIRST_MIN = 15.0   # house SOPs floor ~15% verb-first steps
PASSIVE_MAX = 1.5       # house SOPs stay well under 1 passive/100 words

# House target pulled from the lexicon so this module never re-hardcodes it.
_HOUSE = lexicon.STYLE_PROFILES[lexicon.HOUSE_STYLE]
HOUSE_HEADING = _HOUSE["heading_style"]   # "markdown"
HOUSE_MODAL = _HOUSE["modal"]             # "must"


def _observe(sop) -> dict:
    """Measure one SOP's observed style straight from its text."""
    # Real section headings (drop the synthetic "Preamble" placeholder so that an
    # SOP whose headers the markdown splitter can't see -> "none", a real signal).
    headings = [sec.heading for sec in sop.sections if sec.heading != "Preamble"]
    heading_style = lexicon.detect_heading_style(headings)

    counts = lexicon.modal_counts(sop.full_text)
    modal = max(MODALS, key=lambda m: counts[m]) if any(counts.values()) else "none"

    steps = [m.group("txt") for line in sop.body.splitlines()
             if (m := STEP_RE.match(line))]
    vf = sum(lexicon.sentence_starts_with_verb(s) for s in steps)
    verb_first_pct = round(100 * vf / len(steps), 1) if steps else 0.0

    passive_per_100w = round(100 * lexicon.count_passive(sop.body) / max(1, len(sop.words)), 2)

    deviations = []
    if heading_style != HOUSE_HEADING:
        deviations.append("heading")
    if modal != HOUSE_MODAL:
        deviations.append("modal")
    if verb_first_pct < VERB_FIRST_MIN:
        deviations.append("verb-first")
    if passive_per_100w > PASSIVE_MAX:
        deviations.append("passive")

    return {
        "sop_id": sop.sop_id,
        "dept": sop.department,
        "heading_style": heading_style,
        "dominant_modal": modal,
        "verb_first_pct": verb_first_pct,
        "passive_per_100w": passive_per_100w,
        "modal_counts": counts,
        "observed_style": f"{heading_style} / {modal}",
        "house_profile": sop.frontmatter.get("style_profile", ""),  # ground-truth label
        "conforms": not deviations,
        "deviates_on": ",".join(deviations) if deviations else "-",
        # -- raw counts, used only by the per-SOP assessment (not by the CSV/table) --
        "dept_name": sop.department_name,
        "deviations": deviations,
        "n_headings": len(headings),
        "n_steps": len(steps),
        "n_verb_first": vf,
        "modal_top_count": counts.get(modal, 0),
        "passive_count": lexicon.count_passive(sop.body),
        "word_count": len(sop.words),
    }


# One colour per obligation word so the strip reads categorically, with the
# house standard ("must") carrying the pass-green of the shared design system.
WORD_COLORS = {
    "must": viz.GOOD,
    "shall": viz.PRIMARY,
    "should": viz.SECONDARY,
    "will": viz.ACCENT,
    "responsible for": "#9C6DAF",
}


def _readable_on(fill: str) -> str:
    """Pick INK or white for label text so it always contrasts with the fill."""
    chans = []
    for i in (1, 3, 5):
        c = int(fill[i:i + 2], 16) / 255
        chans.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    lum = 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]
    return viz.INK if lum > 0.25 else viz.BG


def _obligation_strip(ax, depts, dept_shares, dept_dominant) -> None:
    """Categorical strip: the single obligation word each department uses."""
    n = len(depts)
    words = [dept_dominant[d][1] for d in depts]
    shares = [dept_shares[d][MODALS.index(w)] if w in MODALS else 0.0
              for d, w in zip(depts, words)]

    ax.set_xlim(0, 0.86)                # tight: nothing is drawn past ~0.80
    ax.set_ylim(n - 0.5, -0.5)          # row 0 on top -> same order as the bars
    ax.grid(False)
    ax.set_axisbelow(True)
    for side in ax.spines:
        ax.spines[side].set_visible(False)
    ax.set_xticks([])
    ax.set_yticks(range(n), depts)
    ax.tick_params(axis="y", length=0)

    for i, (word, share) in enumerate(zip(words, shares)):
        if i % 2 == 0:                   # quiet zebra banding for row tracking
            ax.add_patch(Rectangle((0, i - 0.5), 0.86, 1, facecolor=viz.PANEL,
                                   edgecolor="none", zorder=0))
        fill = WORD_COLORS.get(word, viz.MUTED)
        txt = _readable_on(fill)
        ax.add_patch(Rectangle((0.04, i - 0.31), 0.54, 0.62, facecolor=fill,
                               edgecolor="none", zorder=2))
        ax.text(0.09, i, f'"{word}"', ha="left", va="center", zorder=3,
                fontsize=9.5, fontweight="bold", color=txt)
        ax.text(0.545, i, f"{share:.0%}", ha="right", va="center", zorder=3,
                fontsize=8, color=txt, alpha=0.85)
        house = word == HOUSE_MODAL
        ax.text(0.62, i, "house standard" if house else "off-standard",
                ha="left", va="center", fontsize=8, zorder=3,
                fontweight="bold" if house else "normal",
                color=viz.GOOD if house else viz.BAD)

    one_hot = all(s >= 0.999 for s in shares)
    ax.set_title("Each department uses exactly one obligation word" if one_hot
                 else "Dominant obligation word by department",
                 fontsize=11.5, pad=8)
    ax.set_ylabel("department")
    ax.set_xlabel("obligation word used (share of that dept's obligation words)",
                  fontsize=9)
    off = sum(1 for w in words if w != HOUSE_MODAL)
    ax.text(0.5, -0.115, f"Green = \"{HOUSE_MODAL}\", the house standard; "
                         f"{off} of {n} departments use a different word.",
            transform=ax.transAxes, ha="center", va="top",
            fontsize=8, color=viz.INK)


def _dept_bars(ax, depts, vf_by_dept, pass_by_dept) -> None:
    """Verb-first% and passive/100w per department vs house targets."""
    from matplotlib.lines import Line2D

    y = np.arange(len(depts))
    h = 0.38
    vf = [vf_by_dept[d] for d in depts]
    pw = [pass_by_dept[d] for d in depts]

    ax.set_axisbelow(True)
    ax.grid(True, axis="x")
    ax.grid(False, axis="y")

    b_vf = ax.barh(y - h / 2, vf, height=h, color=viz.SECONDARY, zorder=2,
                   label="verb-first steps %")
    b_pw = ax.barh(y + h / 2, pw, height=h, color=viz.ACCENT, zorder=2,
                   label="passive / 100 words")

    xmax = max(vf + pw)
    ax.set_xlim(0, xmax * 1.16)
    pad = xmax * 0.012
    # White halo keeps a value legible where a target line runs behind it.
    halo = dict(boxstyle="square,pad=0.15", facecolor=viz.BG, edgecolor="none")
    for rect, v in zip(b_vf, vf):
        ax.text(v + pad, rect.get_y() + rect.get_height() / 2, f"{v:.0f}%",
                va="center", ha="left", fontsize=7, color=viz.INK, zorder=4,
                bbox=halo)
    for rect, v in zip(b_pw, pw):
        ax.text(v + pad, rect.get_y() + rect.get_height() / 2, f"{v:.1f}",
                va="center", ha="left", fontsize=7, color=viz.INK, zorder=4,
                bbox=halo)

    l_vf = ax.axvline(VERB_FIRST_MIN, color=viz.SECONDARY, ls="--", lw=1.1, zorder=3)
    l_pw = ax.axvline(PASSIVE_MAX, color=viz.ACCENT, ls="--", lw=1.1, zorder=3)

    ax.set_yticks(y, depts)
    ax.set_ylim(len(depts) - 0.5, -0.5)  # same top-to-bottom order as the strip
    ax.tick_params(axis="y", length=0)
    ax.set_ylabel("department")
    ax.set_xlabel("verb-first steps (%)  /  passive constructions per 100 words")
    ax.set_title("Verb-first vs passive by department", fontsize=11.5, pad=8)

    handles = [
        b_vf,
        Line2D([], [], color=viz.SECONDARY, ls="--", lw=1.1),
        b_pw,
        Line2D([], [], color=viz.ACCENT, ls="--", lw=1.1),
    ]
    labels = [
        "verb-first steps %",
        f"house target: verb-first >= {VERB_FIRST_MIN:.0f}%",
        "passive / 100 words",
        f"house target: passive <= {PASSIVE_MAX:.1f} / 100w",
    ]
    ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.145),
              ncol=2, fontsize=8, frameon=False, handlelength=1.9,
              columnspacing=2.0, borderpad=0.0, handletextpad=0.8)
    viz.finish(ax)


# ---------------------------------------------------------------------------
# Per-SOP assessment — one scorecard per document, because a reviewer remediates
# a single SOP at a time and needs to know exactly which of the four house-style
# attributes THAT document breaks and what the edit is.
# ---------------------------------------------------------------------------

ATTR_LABELS = {
    "heading": "heading style",
    "modal": "obligation word",
    "verb-first": "verb-first steps",
    "passive": "passive voice",
}


def _remediation(r: dict, attr: str) -> str:
    """One line: the deviation on `attr` plus the concrete edit that fixes it."""
    if attr == "heading":
        if r["heading_style"] == "none":
            return (f"Heading style deviates: no parseable section headings at all, house "
                    f"standard is '{HOUSE_HEADING}' — add markdown '## N. Title' headers so "
                    f"the document has addressable sections.")
        return (f"Heading style deviates: headings are '{r['heading_style']}', house standard "
                f"is '{HOUSE_HEADING}' — convert all {r['n_headings']} section header(s) to "
                f"markdown '## N. Title'.")
    if attr == "modal":
        return (f"Obligation word deviates: '{r['dominant_modal']}' is dominant "
                f"({r['modal_top_count']} uses), house standard is '{HOUSE_MODAL}' — "
                f"replace those {r['modal_top_count']} occurrence(s) with '{HOUSE_MODAL}'.")
    if attr == "verb-first":
        need = max(0, math.ceil(VERB_FIRST_MIN / 100 * r["n_steps"]) - r["n_verb_first"])
        return (f"Verb-first steps deviate: {r['verb_first_pct']:.1f}% of {r['n_steps']} step "
                f"lines open with a strong imperative, house floor is {VERB_FIRST_MIN:.0f}% — "
                f"reword {need} step(s) to start with the action verb.")
    excess = max(1, r["passive_count"] - int(PASSIVE_MAX / 100 * r["word_count"]))
    return (f"Passive voice deviates: {r['passive_per_100w']:.2f} per 100 words "
            f"({r['passive_count']} constructions in {r['word_count']} words), house ceiling is "
            f"{PASSIVE_MAX:.1f} — recast ~{excess} passive clause(s) into active imperatives.")


def _attr_table(r: dict) -> list[dict]:
    """Four-row observed-vs-house comparison scoped to this SOP."""
    spec = [
        ("heading", "heading style", r["heading_style"], HOUSE_HEADING),
        ("modal", "obligation word", r["dominant_modal"], f"'{HOUSE_MODAL}'"),
        ("verb-first", "verb-first steps", f"{r['verb_first_pct']:.1f}%",
         f">= {VERB_FIRST_MIN:.0f}%"),
        ("passive", "passive / 100 words", f"{r['passive_per_100w']:.2f}",
         f"<= {PASSIVE_MAX:.1f}"),
    ]
    return [{"attribute": label, "observed": obs, "house_standard": house,
             "verdict": "deviates" if key in r["deviations"] else "conforms"}
            for key, label, obs, house in spec]


def _write_note(r: dict, status: str, findings: list[str], sopdir: Path) -> Path:
    """Small per-SOP markdown remediation note (no image — corpus panels cover
    the visual story, and 40 renders would not earn their runtime)."""
    lines = [
        f"# {r['sop_id']} — style & structure conformance note",
        "",
        f"- Department: {r['dept']} ({r['dept_name']})",
        f"- House standard: {HOUSE_HEADING} headings, '{HOUSE_MODAL}', "
        f">= {VERB_FIRST_MIN:.0f}% verb-first steps, <= {PASSIVE_MAX:.1f} passive/100w",
        f"- Assessment: **{status.upper()}** — deviates on "
        f"{len(r['deviations'])} of {len(ATTR_LABELS)} attributes",
        "",
        "| attribute | observed | house standard | verdict |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {t['attribute']} | {t['observed']} | {t['house_standard']} | {t['verdict']} |"
              for t in _attr_table(r)]
    lines += ["", "## Findings"] + [f"{i}. {f}" for i, f in enumerate(findings, 1)] + [""]
    path = sopdir / f"{r['sop_id']}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _assess_one(r: dict, sopdir: Path) -> dict:
    """Build the per_sop entry for a single EN SOP."""
    measurable = r["word_count"] > 0 and (r["n_headings"] or r["n_steps"])
    devs = r["deviations"]
    if not measurable:
        status = "n/a"
        findings = [f"{r['sop_id']} has no measurable prose (no headings, no step lines, "
                    f"{r['word_count']} words) — style conformance cannot be assessed."]
    else:
        status = "pass" if not devs else ("warn" if len(devs) == 1 else "fail")
        findings = [_remediation(r, a) for a in devs] or [
            f"Conforms on all {len(ATTR_LABELS)} house-style attributes: "
            f"{HOUSE_HEADING} headings, '{HOUSE_MODAL}', "
            f"{r['verb_first_pct']:.1f}% verb-first steps, "
            f"{r['passive_per_100w']:.2f} passive/100w — no rewrite needed."
        ]
    note = _write_note(r, status, findings, sopdir)
    return {
        "summary": {
            "department": r["dept"],
            "observed_heading_style": r["heading_style"],
            "house_heading_style": HOUSE_HEADING,
            "dominant_modal": r["dominant_modal"],
            "house_modal": HOUSE_MODAL,
            "verb_first_pct": r["verb_first_pct"],
            "house_verb_first_min_pct": VERB_FIRST_MIN,
            "passive_per_100w": r["passive_per_100w"],
            "house_passive_max_per_100w": PASSIVE_MAX,
            "observed_style": r["observed_style"],
            "attributes_deviating": len(devs) if measurable else 0,
            "deviates_on": r["deviates_on"] if measurable else "-",
            "manifest_style_profile": r["house_profile"],  # ground-truth label only
        },
        "findings": findings,
        "artifacts": [str(note.relative_to(PROJECT_ROOT))],
        "table": _attr_table(r),
        "status": status,
    }


def run(corpus: Corpus, outdir: Path) -> dict:
    rows = [_observe(s) for s in corpus.english()]
    depts = sorted({r["dept"] for r in rows})

    # Per-department aggregates (deterministic: sorted, argmax w/ stable order).
    dept_shares, vf_by_dept, pass_by_dept, dept_dominant = {}, {}, {}, {}
    for d in depts:
        drows = [r for r in rows if r["dept"] == d]
        totals = Counter()
        for r in drows:
            totals.update(r["modal_counts"])
        grand = sum(totals[m] for m in MODALS) or 1
        dept_shares[d] = [totals[m] / grand for m in MODALS]
        vf_by_dept[d] = round(sum(r["verb_first_pct"] for r in drows) / len(drows), 1)
        pass_by_dept[d] = round(sum(r["passive_per_100w"] for r in drows) / len(drows), 2)
        top_modal = max(MODALS, key=lambda m: totals[m])
        top_heading = Counter(r["heading_style"] for r in drows).most_common(1)[0][0]
        dept_dominant[d] = (top_heading, top_modal)

    distinct_styles = sorted(set(dept_dominant.values()))
    n_styles = len(distinct_styles)
    non_house = sum(1 for sig in distinct_styles if sig != (HOUSE_HEADING, HOUSE_MODAL))
    conforming = [r for r in rows if r["conforms"]]
    deviating = [r for r in rows if not r["conforms"]]

    # -- figure ----------------------------------------------------------------
    import matplotlib.pyplot as plt
    viz.apply_style()  # house rcParams before creating the axes
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(12.5, 5.2), gridspec_kw={"width_ratios": [1.0, 1.2]})
    _obligation_strip(ax1, depts, dept_shares, dept_dominant)
    _dept_bars(ax2, depts, vf_by_dept, pass_by_dept)
    fig.suptitle(
        f"Style & Structure Standardization — {len(depts)} departments, "
        f"{n_styles} observed styles -> 1 house standard",
        fontsize=13, fontweight="bold", color=viz.INK, y=0.985,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    fig.subplots_adjust(wspace=0.28)
    png = viz.save(fig, outdir / "style.png")

    # -- CSV artifact ----------------------------------------------------------
    cols = ["sop_id", "dept", "heading_style", "dominant_modal", "verb_first_pct",
            "passive_per_100w", "observed_style", "house_profile", "conforms", "deviates_on"]
    csv_path = outdir / "style_by_sop.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r[c] for c in cols})

    # -- per-SOP assessments (additive; every EN SOP gets an entry) -------------
    sopdir = outdir / "sops"
    sopdir.mkdir(parents=True, exist_ok=True)
    per_sop = {r["sop_id"]: _assess_one(r, sopdir)
               for r in sorted(rows, key=lambda r: r["sop_id"])}
    status_mix = Counter(e["status"] for e in per_sop.values())

    dept_line = ", ".join(f"{d}={dept_dominant[d][1]}" for d in depts)
    return {
        "module": "m11_style",
        "title": "Style & Structure Standardization",
        "slide": 25,
        "summary": {
            "documents_analyzed": len(rows),
            "departments": len(depts),
            "n_styles_observed": n_styles,
            "non_house_styles": non_house,
            "house_conforming_count": len(conforming),
            "deviating_count": len(deviating),
            "house_standard": f"{HOUSE_HEADING} headings + '{HOUSE_MODAL}'",
        },
        "key_findings": [
            f"{len(depts)} departments write in {n_styles} distinct observed styles; "
            f"only ENV/DOC use the house standard ({HOUSE_HEADING} + '{HOUSE_MODAL}').",
            f"Only {len(conforming)} of {len(rows)} EN SOPs conform to house style; "
            f"{len(deviating)} deviate on heading, modal, verb-first, or passive voice.",
            f"Dominant modal splits cleanly by department: {dept_line}.",
            f"Cleaning SOPs average {pass_by_dept.get('CLN', 0):.1f} passive/100w with "
            f"ALL-CAPS headings vs {pass_by_dept.get('ENV', 0):.1f} in the house standard.",
            f"Verb-first steps average {vf_by_dept.get('ENV', 0):.0f}% (ENV) / "
            f"{vf_by_dept.get('DOC', 0):.0f}% (DOC) in the house standard but "
            f"{vf_by_dept.get('MFG', 0):.0f}% in Manufacturing.",
            f"Per-SOP verdicts: {status_mix['pass']} pass, {status_mix['warn']} warn "
            f"(one attribute off), {status_mix['fail']} fail (two or more) — "
            f"each SOP has its own remediation note under {sopdir.name}/.",
        ],
        "artifacts": [
            str(Path(png).relative_to(PROJECT_ROOT)),
            str(csv_path.relative_to(PROJECT_ROOT)),
        ],
        "table": [{c: r[c] for c in cols} for r in rows],
        "table_columns": cols,
        "scope": "per_sop",
        "per_sop": per_sop,
    }
