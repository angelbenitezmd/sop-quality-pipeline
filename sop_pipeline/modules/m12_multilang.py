"""m12_multilang — Multi-Language Harmonization (deck slide 26).

Pairs every Spanish (``language == 'es'``) SOP with its English parent and audits
the translation for harmonization defects across three categories:

  value      numeric quantities with units (%/min/ml/degrees) that disagree
  format     decimal-separator drift ('0,5' comma style vs '0.5' point style)
  structure  section-count mismatch and/or a missing safety/warning section

Every verdict is computed from the parsed SOP text (not read off the manifest),
then rendered as a compact stacked bar of discrepancies per pair by category,
paired with an annotated EN-vs-ES detail panel, plus a flat issue table.
Deterministic: no randomness, stable id-sorted ordering.

Scope is ``per_sop``: alongside the corpus rollup, every English SOP gets its own
entry in ``per_sop``. Documents with a translated variant carry that pair's
discrepancy table, concrete findings and a comparison card in ``outdir/sops/``;
documents without one are reported explicitly as ``n/a`` rather than omitted, so
a reviewer can tell "checked, no variant" apart from "never checked".
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

from sop_pipeline.core.corpus import Corpus, SOP, PROJECT_ROOT
from sop_pipeline.core import viz

CATEGORIES = ["value", "format", "structure"]
CAT_COLORS = {"value": viz.PRIMARY, "format": viz.ACCENT, "structure": viz.BAD}
CAT_LABELS = {"value": "Value", "format": "Format", "structure": "Structure"}
# readable text colour for a count sitting *on top of* each category fill
CAT_ONFILL = {"value": "#FFFFFF", "format": viz.INK, "structure": "#FFFFFF"}

# number (point- or comma-decimal) directly followed by a known unit token
_NUM_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(%|ml|minutes|minutos|min|degrees|grados|°)",
    re.IGNORECASE,
)
_COMMA_DECIMAL_RE = re.compile(r"\d,\d")
_SAFETY_KEYS = ("safety", "warning", "hazard", "caution",
                "seguridad", "advertencia", "precaucion", "peligro")


# --------------------------------------------------------------------------- #
# Small text helpers
# --------------------------------------------------------------------------- #
def _strip_accents(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def _canon_unit(unit: str) -> str:
    u = unit.lower()
    if u.startswith("min"):
        return "min"
    if u in ("degrees", "grados", "°"):
        return "deg"
    return u  # "%" or "ml"


def _unit_label(unit: str) -> str:
    return {"%": "%", "min": " min", "ml": " ml", "deg": "°"}.get(unit, unit)


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _values_by_unit(text: str) -> dict[str, set]:
    """Map each canonical unit -> set of numeric values found with that unit."""
    out: dict[str, set] = {}
    for num, unit in _NUM_UNIT_RE.findall(text):
        out.setdefault(_canon_unit(unit), set()).add(round(float(num.replace(",", ".")), 3))
    return out


def _safety_headings(sop: SOP) -> list[str]:
    """Headings that look like a safety/warning section, numbering stripped."""
    return [
        re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", sec.heading).strip()
        for sec in sop.sections
        if any(key in _strip_accents(sec.heading) for key in _SAFETY_KEYS)
    ]


def _has_safety_section(sop: SOP) -> bool:
    return bool(_safety_headings(sop))


# --------------------------------------------------------------------------- #
# Per-pair comparison
# --------------------------------------------------------------------------- #
def _analyze_pair(en: SOP, es: SOP) -> tuple[list[dict], bool]:
    """Return (discrepancy rows, missing_section flag) for one EN/ES pair."""
    rows: list[dict] = []

    # -- value: units present in either doc whose value-sets disagree ------- #
    en_vals, es_vals = _values_by_unit(en.full_text), _values_by_unit(es.full_text)
    for unit in sorted(set(en_vals) | set(es_vals)):
        ev, sv = en_vals.get(unit, set()), es_vals.get(unit, set())
        if ev != sv:
            lab = _unit_label(unit)
            rows.append({
                "category": "value",
                "en_value": ", ".join(_fmt(v) + lab for v in sorted(ev)) or "—",
                "es_value": ", ".join(_fmt(v) + lab for v in sorted(sv)) or "—",
                "issue": f"Numeric value differs for unit '{unit}' between EN and ES",
            })

    # -- format: decimal-separator convention drift ------------------------ #
    en_comma = bool(_COMMA_DECIMAL_RE.search(en.full_text))
    es_comma = bool(_COMMA_DECIMAL_RE.search(es.full_text))
    if en_comma != es_comma:
        rows.append({
            "category": "format",
            "en_value": "comma decimals (0,5)" if en_comma else "point decimals (0.5)",
            "es_value": "comma decimals (0,5)" if es_comma else "point decimals (0.5)",
            "issue": "Decimal-separator convention differs (comma vs point)",
        })

    # -- structure: section count + safety section presence ---------------- #
    n_en, n_es = len(en.sections), len(es.sections)
    if n_en != n_es:
        rows.append({
            "category": "structure",
            "en_value": f"{n_en} sections",
            "es_value": f"{n_es} sections",
            "issue": f"Section-count mismatch ({n_en} EN vs {n_es} ES)",
        })
    safe_en, safe_es = _has_safety_section(en), _has_safety_section(es)
    missing_section = safe_en and not safe_es
    if safe_en != safe_es:
        rows.append({
            "category": "structure",
            "en_value": "Safety/Warnings section present" if safe_en else "(none)",
            "es_value": "Safety/Warnings section present" if safe_es else "(missing)",
            "issue": "Safety/Warnings section present in one language only",
        })
    return rows, missing_section


# --------------------------------------------------------------------------- #
# Chart
# --------------------------------------------------------------------------- #
def _clip(text: str, limit: int = 34) -> str:
    """Keep cell text inside its column width."""
    text = str(text)
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _plot(pairs: list[str], counts: dict[str, dict[str, int]],
          rows: list[dict], path: Path) -> str:
    """Compact stacked bar (per pair, per category) + an EN-vs-ES detail panel.

    The audit legitimately produces only a handful of findings, so the figure is
    built to make a small result look deliberate: no empty category slots, and
    every discrepancy spelled out with the actual English/Spanish values.
    """
    from matplotlib.patches import Patch, Rectangle

    present = [c for c in CATEGORIES if sum(counts[p][c] for p in pairs) > 0]
    n_rows = len(rows)
    n_pairs = len(pairs)

    fig, ax0 = viz.new_fig(9.8, 5.3)
    ax0.remove()  # replace the default single axes with a 2-panel layout
    ax = fig.add_subplot(
        fig.add_gridspec(1, 1, left=0.155, right=0.795, top=0.875, bottom=0.635)[0])
    axt = fig.add_subplot(
        fig.add_gridspec(1, 1, left=0.045, right=0.985, top=0.515, bottom=0.03)[0])

    # ---------------- panel 1: stacked bar, non-zero segments only --------- #
    for y, pair in enumerate(pairs):
        left = 0.0
        for cat in present:
            v = counts[pair][cat]
            if not v:
                continue
            ax.barh(y, v, left=left, height=0.5, color=CAT_COLORS[cat], zorder=3)
            ax.text(left + v / 2.0, y, str(v), ha="center", va="center",
                    fontsize=9, fontweight="bold", color=CAT_ONFILL[cat], zorder=4)
            left += v

    top = max([sum(counts[p][c] for c in CATEGORIES) for p in pairs] + [1])
    ax.set_xlim(0, top + 0.16)
    ax.set_xticks(range(top + 1))
    ax.set_ylim(n_pairs - 0.5, -0.5)          # first pair on top, no dead space
    ax.set_yticks(range(n_pairs))
    ax.set_yticklabels(pairs, fontsize=8.5)
    ax.set_xlabel("Discrepancies detected")
    ax.set_ylabel("SOP pair (EN vs ES)")
    ax.grid(False)
    ax.grid(True, axis="x", color=viz.GRID, linewidth=0.7)
    ax.set_axisbelow(True)                    # gridlines behind the bars
    ax.tick_params(axis="y", length=0)

    handles = [Patch(facecolor=CAT_COLORS[c], label=CAT_LABELS[c]) for c in present]
    leg = ax.legend(handles=handles, title="Category", loc="upper left",
                    bbox_to_anchor=(1.03, 1.04), frameon=True, fontsize=8.5,
                    borderpad=0.6, labelspacing=0.5, handlelength=1.2,
                    handleheight=0.95, borderaxespad=0.0)
    frame = leg.get_frame()
    frame.set_facecolor(viz.BG)
    frame.set_edgecolor(viz.GRID)
    frame.set_linewidth(0.9)
    leg.get_title().set_fontsize(8.5)
    leg.get_title().set_fontweight("bold")
    leg.get_title().set_color(viz.INK)
    viz.finish(ax)

    fig.suptitle("Multi-Language Harmonization — EN/ES discrepancies by category",
                 fontsize=13, fontweight="bold", color=viz.INK, y=0.975)

    # ---------------- panel 2: what actually differs ----------------------- #
    axt.set_axis_off()
    axt.set_xlim(0, 1)
    axt.set_ylim(0, n_rows + 1.3)
    cx = (0.014, 0.040, 0.200, 0.340, 0.650)
    heads = ("SOP pair", "Category", "English (EN)", "Spanish (ES)")

    axt.text(0.0, n_rows + 0.92,
             f"What differs — all {n_rows} discrepancies",
             ha="left", va="center", fontsize=10.5, fontweight="bold",
             color=viz.INK)
    for x, head in zip(cx[1:], heads):
        axt.text(x, n_rows + 0.34, head, ha="left", va="center",
                 fontsize=8.5, fontweight="bold", color=viz.INK)
    axt.plot([0, 1], [n_rows + 0.03] * 2, color=viz.MUTED, lw=0.9,
             solid_capstyle="butt", clip_on=False, zorder=1)

    for i, r in enumerate(rows):
        yc = n_rows - 0.5 - i
        if i % 2 == 0:
            axt.add_patch(Rectangle((0, yc - 0.5), 1, 1, facecolor=viz.PANEL,
                                    edgecolor="none", zorder=0))
        cat = r["category"]
        axt.plot([cx[0]], [yc], marker="s", markersize=6.5, linestyle="none",
                 color=CAT_COLORS[cat], zorder=2, clip_on=False)
        cells = (
            (cx[1], r["pair"].split(" / ")[0], viz.INK),
            (cx[2], CAT_LABELS.get(cat, cat.capitalize()), viz.INK),
            (cx[3], _clip(r["en_value"]), viz.INK),
            (cx[4], _clip(r["es_value"]), viz.BAD),
        )
        for x, txt, colour in cells:
            axt.text(x, yc, txt, ha="left", va="center", fontsize=8.5,
                     color=colour, zorder=2)

    return viz.save(fig, path)


# --------------------------------------------------------------------------- #
# Per-SOP assessment
# --------------------------------------------------------------------------- #
def _row_finding(row: dict, en: SOP, es: SOP) -> str:
    """Spell one discrepancy row out as a concrete, reviewer-facing sentence."""
    cat = row["category"]
    if cat == "value":
        return (f"Value mismatch: EN specifies {row['en_value']} where ES specifies "
                f"{row['es_value']} — reconcile against the approved master.")
    if cat == "format":
        return (f"Number-format drift: EN uses {row['en_value']} while ES uses "
                f"{row['es_value']}.")
    if row["issue"].startswith("Section-count"):
        return (f"Structure: {row['en_value']} in EN vs {row['es_value']} in ES — "
                "one section was dropped in translation.")
    # safety/warning section present on one side only
    lacking, holder = (es, en) if row["es_value"] == "(missing)" else (en, es)
    names = ", ".join(f"'{h}'" for h in _safety_headings(holder)) or "safety/warning content"
    return (f"Missing section in {lacking.sop_id}: {names} exists in "
            f"{holder.sop_id} only — re-translate before release.")


def _plot_pair(en: SOP, es: SOP, rows: list[dict], by_cat: dict[str, int],
               path: Path) -> str:
    """One comparison card per translated pair: EN value vs ES value, per issue."""
    from matplotlib.patches import Rectangle

    n = max(len(rows), 1)
    fig, ax0 = viz.new_fig(8.2, 1.45 + 0.62 * n)
    ax0.remove()
    ax = fig.add_subplot(fig.add_gridspec(1, 1, left=0.03, right=0.985,
                                          top=0.80, bottom=0.04)[0])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, n + 0.9)

    verdict = "FAIL" if rows else "PASS"
    fig.suptitle(f"{en.sop_id} vs {es.sop_id} — translation harmonization",
                 fontsize=12.5, fontweight="bold", color=viz.INK, y=0.975)
    noun = "discrepancy" if len(rows) == 1 else "discrepancies"
    ax.text(0.0, n + 0.62,
            f"{len(rows)} {noun} — value {by_cat['value']}, "
            f"format {by_cat['format']}, structure {by_cat['structure']}",
            ha="left", va="center", fontsize=9, color=viz.MUTED)
    ax.text(1.0, n + 0.62, verdict, ha="right", va="center", fontsize=10,
            fontweight="bold", color=viz.BAD if rows else viz.GOOD)
    ax.plot([0, 1], [n + 0.3] * 2, color=viz.MUTED, lw=0.9,
            solid_capstyle="butt", clip_on=False, zorder=1)

    if not rows:
        ax.text(0.5, n / 2.0, "No discrepancies detected between EN and ES.",
                ha="center", va="center", fontsize=10, color=viz.GOOD)
        return viz.save(fig, path)

    for i, r in enumerate(rows):
        yc = n - 0.5 - i
        if i % 2 == 0:
            ax.add_patch(Rectangle((0, yc - 0.5), 1, 1, facecolor=viz.PANEL,
                                   edgecolor="none", zorder=0))
        cat = r["category"]
        ax.plot([0.012], [yc + 0.2], marker="s", markersize=6.5, linestyle="none",
                color=CAT_COLORS[cat], zorder=2, clip_on=False)
        ax.text(0.038, yc + 0.2, CAT_LABELS.get(cat, cat.capitalize()), ha="left",
                va="center", fontsize=9, fontweight="bold", color=viz.INK, zorder=2)
        ax.text(0.20, yc + 0.2, "EN  " + _clip(r["en_value"]), ha="left",
                va="center", fontsize=9, color=viz.INK, zorder=2)
        ax.text(0.545, yc + 0.2, "ES  " + _clip(r["es_value"]), ha="left",
                va="center", fontsize=9, color=viz.BAD, zorder=2)
        ax.text(0.038, yc - 0.24, _clip(r["issue"], 105), ha="left", va="center",
                fontsize=8, color=viz.MUTED, zorder=2)

    return viz.save(fig, path)


def _per_sop(corpus: Corpus, outdir: Path,
             pair_rows: dict[str, list[dict]]) -> dict[str, dict]:
    """One assessment per English SOP — translated or explicitly n/a."""
    sops_dir = outdir / "sops"
    sops_dir.mkdir(parents=True, exist_ok=True)

    variants: dict[str, SOP] = {}
    for s in sorted(corpus, key=lambda s: s.sop_id):
        if s.language != "en" and s.parent_id and corpus.get(s.parent_id) is not None:
            variants.setdefault(s.parent_id, s)

    out: dict[str, dict] = {}
    for en in sorted(corpus.english(), key=lambda s: s.sop_id):
        es = variants.get(en.sop_id)
        if es is None:
            out[en.sop_id] = {
                "summary": {
                    "variant_id": None,
                    "sections_en": len(en.sections),
                    "sections_es": 0,
                    "value_discrepancies": 0,
                    "format_discrepancies": 0,
                    "structure_discrepancies": 0,
                },
                "findings": ["No translated variant in the corpus — nothing to harmonize."],
                "artifacts": [],
                "table": [],
                "status": "n/a",
            }
            continue

        rows = pair_rows.get(en.sop_id, [])
        by_cat = {c: sum(1 for r in rows if r["category"] == c) for c in CATEGORIES}
        png = _plot_pair(en, es, rows, by_cat, sops_dir / f"{en.sop_id}.png")
        findings = [_row_finding(r, en, es) for r in rows] or [
            f"No discrepancies detected against {es.sop_id} — translation is harmonized."
        ]
        out[en.sop_id] = {
            "summary": {
                "variant_id": es.sop_id,
                "sections_en": len(en.sections),
                "sections_es": len(es.sections),
                "value_discrepancies": by_cat["value"],
                "format_discrepancies": by_cat["format"],
                "structure_discrepancies": by_cat["structure"],
            },
            "findings": findings,
            "artifacts": [str(Path(png).relative_to(PROJECT_ROOT))],
            "table": rows,
            "status": "fail" if rows else "pass",
        }
    return out


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def run(corpus: Corpus, outdir: Path) -> dict:
    outdir = Path(outdir)

    es_sops = sorted(
        (s for s in corpus if s.language == "es" and s.parent_id),
        key=lambda s: s.sop_id,
    )

    table: list[dict] = []
    counts: dict[str, dict[str, int]] = {}
    pair_labels: list[str] = []
    pair_rows: dict[str, list[dict]] = {}   # EN id -> that pair's discrepancy rows
    pairs_with_missing = 0

    for es in es_sops:
        en = corpus.get(es.parent_id)
        if en is None:
            continue
        label = en.sop_id  # x-axis tick; full pair spelled out in the table
        pair_name = f"{en.sop_id} / {es.sop_id}"
        pair_labels.append(label)
        counts[label] = {c: 0 for c in CATEGORIES}

        rows, missing = _analyze_pair(en, es)
        pair_rows[en.sop_id] = rows
        pairs_with_missing += int(missing)
        for r in rows:
            counts[label][r["category"]] += 1
            table.append({"pair": pair_name, **r})

    png = _plot(pair_labels, counts, table, outdir / "multilang.png") if pair_labels else ""

    # optional machine-readable dump of the issue table
    csv_path = outdir / "discrepancies.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["pair", "category", "en_value", "es_value", "issue"])
        w.writeheader()
        w.writerows(table)

    by_cat = {c: sum(1 for r in table if r["category"] == c) for c in CATEGORIES}

    # findings derived from the detected rows (not hardcoded verdicts)
    findings = [
        f"{len(pair_labels)} EN/ES pair(s) audited; {len(table)} discrepancies "
        f"(value {by_cat['value']}, format {by_cat['format']}, structure {by_cat['structure']}).",
    ]
    for label in pair_labels:
        issues = [r["issue"] for r in table if r["pair"].startswith(label + " ")]
        if issues:
            findings.append(f"{label}: " + "; ".join(issues))
    findings.append(
        f"{pairs_with_missing} of {len(pair_labels)} pair(s) missing a section "
        f"present in the EN parent — re-translation required before use."
    )

    per_sop = _per_sop(corpus, outdir, pair_rows)
    n_na = sum(1 for v in per_sop.values() if v["status"] == "n/a")
    findings.append(
        f"{n_na} of {len(per_sop)} EN SOPs have no translated variant — each is "
        f"reported as 'n/a' (checked, nothing to harmonize), never skipped."
    )

    artifacts = [str(Path(p).relative_to(PROJECT_ROOT)) for p in (png, csv_path) if p]

    return {
        "module": "m12_multilang",
        "title": "Multi-Language Harmonization",
        "slide": 26,
        "summary": {
            "pairs_checked": len(pair_labels),
            "total_discrepancies": len(table),
            "pairs_with_missing_sections": pairs_with_missing,
        },
        "key_findings": findings[:6],
        "artifacts": artifacts,
        "table": table,
        "table_columns": ["pair", "category", "en_value", "es_value", "issue"],
        "scope": "per_sop",
        "per_sop": per_sop,
    }
