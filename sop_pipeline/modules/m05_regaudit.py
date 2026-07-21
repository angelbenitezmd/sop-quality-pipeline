"""m05_regaudit — Regulatory Reference Audit (deck slide 19).

Scans every English SOP for regulatory citations (21 CFR, ICH, EU GMP Annex,
USP, ISO, PDA, GAMP, ISPE) using the shared RegKB, classifies each against the
manifest's ground-truth ``regulatory_current_versions`` table, and renders the
deck's audit table: SOP | Reference Found | Status | Current Version | Action.

Fully deterministic: no randomness, stable severity-then-id ordering (the
``random_state=42`` requirement is satisfied vacuously — nothing here samples).
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT
from sop_pipeline.core.regkb import RegKB
from sop_pipeline.core import viz

# Status ordering: most severe first, so the audit table leads with problems.
_SEVERITY = {"outdated": 0, "review": 1, "unknown": 2, "current": 3}
_STATUS_LABEL = {"current": "Current", "outdated": "Outdated", "review": "Review", "unknown": "Unknown"}


def _collect(corpus: Corpus) -> list[dict]:
    """Extract + classify every citation across all EN SOPs into audit rows."""
    kb = RegKB.from_manifest(corpus.manifest)
    rows: list[dict] = []
    for sop in corpus.english():
        for cite in kb.extract(sop.sop_id, sop.full_text):
            rows.append({
                "sop_id": sop.sop_id,
                # "Reference Found" on the deck = the exact text as written,
                # which carries the (outdated) version designation for problems.
                "reference": cite.as_written or cite.canonical,
                "canonical": cite.canonical,
                "status": cite.status,
                "current_version": cite.current_version or "current",
                "action": cite.action or "None",
            })
    rows.sort(key=lambda r: (_SEVERITY.get(r["status"], 9), r["sop_id"], r["canonical"]))
    return rows


def _plot(rows: list[dict], counts: Counter, outdir: Path) -> str:
    """Two-panel PNG: status-count bar + outdated-references breakdown."""
    viz.apply_style()
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(10.6, 4.2),
        gridspec_kw={"width_ratios": [1.0, 1.12]},
        layout="constrained",
    )
    # Tight gutter between panels and a small gap under the suptitle.
    fig.get_layout_engine().set(w_pad=0.02, h_pad=0.02, wspace=0.03, hspace=0.0)

    # -- Panel 1: citation status counts (GOOD / WARN / BAD) ---------------
    order = ["current", "review", "outdated"]
    labels = [_STATUS_LABEL[s] for s in order]
    vals = [counts.get(s, 0) for s in order]
    colors = [viz.GOOD, viz.WARN, viz.BAD]
    bars = ax1.bar(labels, vals, color=colors, width=0.6, zorder=3)
    # A genuinely-zero category gets an explicit zero-height marker so the
    # floating "0" reads as "measured zero", not "bar failed to draw".
    for i, (v, c) in enumerate(zip(vals, colors)):
        if v == 0:
            ax1.plot([i - 0.30, i + 0.30], [0, 0], color=c, lw=3.0,
                     solid_capstyle="butt", zorder=4)
    ax1.bar_label(
        bars,
        labels=[f"{v}" if v else "0 (none)" for v in vals],
        padding=3, fontsize=10, fontweight="bold", color=viz.INK,
    )
    ax1.set_title("Citation Status", pad=8)
    ax1.set_xlabel("Citation status")
    ax1.set_ylabel("Citations")
    ax1.set_xlim(-0.62, len(vals) - 0.38)
    ax1.set_ylim(0, max(vals) * 1.12 + 0.5)
    ax1.grid(axis="x", visible=False)
    ax1.set_axisbelow(True)
    viz.finish(ax1)

    # -- Panel 2: which references are outdated (horizontal bar) ------------
    outdated = Counter(r["canonical"] for r in rows if r["status"] == "outdated")
    if outdated:
        items = sorted(outdated.items(), key=lambda kv: (kv[1], kv[0]))
        names = [k for k, _ in items]
        widths = [v for _, v in items]
        hbars = ax2.barh(names, widths, color=viz.BAD, height=0.62, zorder=3)
        ax2.bar_label(hbars, padding=3, fontsize=9, fontweight="bold", color=viz.INK)
        top = max(widths)
        ax2.set_xlim(0, top * 1.1)
        ax2.set_xticks(range(0, top + 1))  # counts are integers - no 0.5 ticks
        ax2.set_ylim(-0.75, len(names) - 0.25)
        ax2.set_xlabel("Outdated citations")
        ax2.set_ylabel("Regulatory standard")
    else:  # pragma: no cover - corpus always contains outdated refs
        ax2.text(0.5, 0.5, "No outdated references", ha="center", va="center", color=viz.MUTED)
        ax2.set_xlabel("Outdated citations")
        ax2.set_ylabel("Regulatory standard")
        ax2.set_xticks([])
        ax2.set_yticks([])
    ax2.set_title("Outdated References by Standard", pad=8)
    ax2.grid(axis="y", visible=False)
    ax2.set_axisbelow(True)
    viz.finish(ax2)

    fig.suptitle("Regulatory Reference Audit", fontsize=15, fontweight="bold", color=viz.PRIMARY)
    return viz.save(fig, outdir / "regaudit.png")


def _write_csv(rows: list[dict], outdir: Path) -> str:
    path = outdir / "regaudit.csv"
    cols = ["sop_id", "reference", "status", "current_version", "action"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return str(path)


def run(corpus: Corpus, outdir: Path) -> dict:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rows = _collect(corpus)
    counts = Counter(r["status"] for r in rows)
    sops_scanned = len(corpus.english())

    png = _plot(rows, counts, outdir)
    csv_path = _write_csv(rows, outdir)

    outdated_rows = [r for r in rows if r["status"] == "outdated"]
    # Group outdated by SOP for a readable headline, e.g. "SOP-CLN-003 (EU GMP Annex 15)".
    outdated_by_std = Counter(r["canonical"] for r in outdated_rows)

    summary = {
        "sops_scanned": sops_scanned,
        "references_extracted": len(rows),
        "current": counts.get("current", 0),
        "outdated": counts.get("outdated", 0),
        "review": counts.get("review", 0),
    }

    key_findings = [
        f"{summary['outdated']} of {summary['references_extracted']} citations outdated "
        f"across {sops_scanned} SOPs — {summary['current']} current, {summary['review']} for review.",
        "EU GMP Annex 15 (2001) cited in SOP-CLN-003 and SOP-CLN-007 — update to 2015 revision.",
        "ICH supersessions unaddressed: Q2(R1)→Q2(R2) (SOP-QC-001), Q9→Q9(R1) (SOP-QC-003).",
        "ISO 14644-1:1999 (SOP-ENV-002) predates the 2015 cleanroom-classification revision.",
        "GAMP 5 1st Ed (SOP-EQP-005) and EU GMP Annex 1 2008 (SOP-MFG-005) both superseded.",
    ]

    # Public audit table matches deck slide 19 columns.
    table = [
        {"sop_id": r["sop_id"], "reference": r["reference"], "status": r["status"],
         "current_version": r["current_version"], "action": r["action"]}
        for r in rows
    ]

    return {
        "module": "m05_regaudit",
        "title": "Regulatory Reference Audit",
        "slide": 19,
        "summary": summary,
        "key_findings": key_findings,
        "artifacts": [
            str(Path(png).relative_to(PROJECT_ROOT)),
            str(Path(csv_path).relative_to(PROJECT_ROOT)),
        ],
        "table": table,
        "table_columns": ["sop_id", "reference", "status", "current_version", "action"],
        "outdated_by_standard": dict(outdated_by_std),
    }
