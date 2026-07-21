"""m01_similarity — TF-IDF + cosine similarity across the SOP corpus (deck slide 15).

Builds a TF-IDF matrix over every English SOP's ``full_text`` (unigrams + bigrams,
English stop-words removed), computes pairwise cosine similarity, renders an ordered
heatmap with rows grouped by department so near-duplicate procedures sit together on
the diagonal, and reports the high-overlap pairs (cosine >= 0.75) that flag redundant
SOPs. Detection is real TF-IDF; the manifest's near_duplicate_groups only label pairs.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from sop_pipeline.core import viz
from sop_pipeline.core.corpus import PROJECT_ROOT, Corpus

HIGH_OVERLAP = 0.75  # cosine at/above this flags a redundant pair

# --- display-only constants (do not affect any computed/reported value) -------
# The self-similarity diagonal is 1.0 by construction and saturates the colour
# ramp, pushing ~99% of the real off-diagonal signal into the palest 15% of the
# scale. For rendering we mask the diagonal and clip the ramp just above the
# 99th percentile of off-diagonal similarity so genuine clusters read clearly.
DISPLAY_VMAX = 0.80
DIAGONAL_FILL = "#C8CFD4"  # neutral grey => "masked, not data"


def _short(sop_id: str) -> str:
    """SOP-CLN-003 -> CLN-003 for compact axis labels."""
    return sop_id[4:] if sop_id.startswith("SOP-") else sop_id


def _dup_groups(corpus: Corpus) -> dict[str, str]:
    """Map each SOP id to its manifest near-duplicate group name (for labelling only)."""
    out: dict[str, str] = {}
    for grp in corpus.manifest.get("near_duplicate_groups", []):
        for member in grp.get("members", []):
            out[member] = grp.get("group", "")
    return out


def _interpret(a: str, b: str, dept: dict[str, str], groups: dict[str, str]) -> str:
    if a in groups and groups[a] == groups.get(b):
        return f"Near-duplicate ({groups[a]})"
    if dept[a] == dept[b]:
        return "Same-department overlap"
    return "Cross-department overlap"


def _cluster(pairs: list[tuple[str, str]]) -> list[list[str]]:
    """Connected components of the high-overlap graph (union-find)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)
    comps: dict[str, list[str]] = {}
    for node in parent:
        comps.setdefault(find(node), []).append(node)
    return [sorted(c) for c in comps.values() if len(c) > 1]


def run(corpus: Corpus, outdir: Path) -> dict:
    outdir = Path(outdir)

    # Order documents by department so clusters land contiguously on the diagonal.
    sops = sorted(corpus.english(), key=lambda s: (s.department, s.sop_id))
    ids = [s.sop_id for s in sops]
    labels = [_short(i) for i in ids]
    dept = {s.sop_id: s.department for s in sops}
    groups = _dup_groups(corpus)

    # TF-IDF (unigrams+bigrams, English stop-words) -> cosine similarity. Deterministic.
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
    tfidf = vectorizer.fit_transform([s.full_text for s in sops])
    sim = cosine_similarity(tfidf)
    np.fill_diagonal(sim, 1.0)

    # High-overlap pairs (upper triangle, off-diagonal).
    n = len(ids)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append((sim[i, j], ids[i], ids[j]))
    pairs.sort(reverse=True)
    high = [(a, b) for s, a, b in pairs if s >= HIGH_OVERLAP]
    off_diag_max = max((s for s, _, _ in pairs), default=0.0)

    # --- similarity_matrix.csv ------------------------------------------------
    csv_path = outdir / "similarity_matrix.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sop_id"] + labels)
        for i, lab in enumerate(labels):
            w.writerow([lab] + [f"{sim[i, j]:.4f}" for j in range(n)])

    # --- heatmap.png ----------------------------------------------------------
    cmap = LinearSegmentedColormap.from_list("sop_sequential", viz.SEQUENTIAL).copy()
    cmap.set_bad(DIAGONAL_FILL)  # masked diagonal renders neutral grey

    # Display copy only — `sim` (CSV, pairs, reported numbers) is untouched.
    disp = np.ma.masked_invalid(np.array(sim, dtype=float))
    disp[np.arange(n), np.arange(n)] = np.ma.masked

    fig, ax = viz.new_fig(10.0, 9.0)
    ax.grid(False)
    ax.set_axisbelow(True)
    im = ax.imshow(disp, cmap=cmap, vmin=0.0, vmax=DISPLAY_VMAX, aspect="equal")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=90, fontsize=6.5)
    ax.set_yticklabels(labels, fontsize=6.5)
    ax.tick_params(length=2, width=0.6, pad=2)
    # White separators where the department changes (rows are dept-ordered).
    for k in range(1, n):
        if sops[k].department != sops[k - 1].department:
            ax.axhline(k - 0.5, color=viz.BG, lw=1.0, zorder=3)
            ax.axvline(k - 0.5, color=viz.BG, lw=1.0, zorder=3)

    ax.set_title("SOP Similarity Analysis — TF-IDF Cosine (English corpus)", pad=20)
    ax.text(
        0.5, 1.012,
        f"Self-similarity diagonal masked (grey); colour scale clipped at {DISPLAY_VMAX:.2f} "
        f"— amber mark on the bar is the {HIGH_OVERLAP:.2f} redundancy flag",
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=8, color=viz.INK, alpha=0.72,
    )
    ax.set_xlabel("SOP (ordered by department)")
    ax.set_ylabel("SOP (ordered by department)")

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03, extend="max")
    cbar.set_label("Cosine similarity (off-diagonal)")
    cbar.set_ticks([0.0, 0.2, 0.4, 0.6, 0.8])
    cbar.ax.axhline(HIGH_OVERLAP, color=viz.ACCENT, lw=1.6)
    cbar.outline.set_edgecolor(viz.MUTED)
    cbar.outline.set_linewidth(0.6)
    heatmap_path = viz.save(fig, outdir / "heatmap.png")

    # --- top pairs table ------------------------------------------------------
    table = [
        {
            "pair": f"{_short(a)} / {_short(b)}",
            "similarity": round(float(s), 3),
            "interpretation": _interpret(a, b, dept, groups),
        }
        for s, a, b in pairs[:12]
    ]

    # --- clusters -> key findings --------------------------------------------
    key_findings = [
        f"{len(ids)} English SOPs compared via TF-IDF cosine (unigrams + bigrams).",
        f"{len(high)} high-overlap pairs at cosine >= {HIGH_OVERLAP:.2f}; "
        f"max off-diagonal similarity {off_diag_max:.2f}.",
    ]
    for members in sorted(_cluster(high), key=len, reverse=True):
        within = [sim[ids.index(x), ids.index(y)]
                  for a, x in enumerate(members) for y in members[a + 1:]]
        lo, hi = min(within), max(within)
        gname = groups.get(members[0], "")
        tag = f"{gname} cluster" if gname and all(groups.get(m) == gname for m in members) else "Overlap cluster"
        key_findings.append(
            f"{tag} ({lo:.2f}-{hi:.2f}): " + " / ".join(_short(m) for m in members)
        )

    return {
        "module": "m01_similarity",
        "title": "SOP Similarity Analysis",
        "slide": 15,
        "summary": {
            "documents_analyzed": len(ids),
            "high_overlap_pairs": len(high),
            "max_similarity": round(float(off_diag_max), 3),
        },
        "key_findings": key_findings[:6],
        "artifacts": [
            str(Path(heatmap_path).relative_to(PROJECT_ROOT)),
            str(csv_path.relative_to(PROJECT_ROOT)),
        ],
        "table": table,
        "table_columns": ["pair", "similarity", "interpretation"],
    }
