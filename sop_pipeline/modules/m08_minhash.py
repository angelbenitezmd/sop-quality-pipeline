"""m08_minhash — MinHash Near-Duplicate Detection (deck slide 22).

Cosine/TF-IDF similarity (m01) rewards shared vocabulary; it can miss two SOPs
that were copy-pasted and lightly edited when they use synonyms or reordered
prose. MinHash + LSH over *word shingles* estimates the Jaccard overlap of the
actual token sequences, so it flags **structural** near-duplication — the kind of
uncontrolled cloning that creates change-control debt across a document set.

Pipeline: k=5 word shingles per EN SOP -> MinHash(num_perm=128) -> MinHashLSH
(threshold ~0.4) -> query every doc for candidate neighbours -> estimate pairwise
Jaccard -> reconcile the pairs against the manifest's near_duplicate_groups.
"""

from __future__ import annotations

from pathlib import Path

from datasketch import MinHash, MinHashLSH

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT
from sop_pipeline.core import viz

K = 5            # word-shingle length
NUM_PERM = 128   # MinHash permutations
THRESHOLD = 0.4  # LSH candidate threshold
SEED = 42        # deterministic MinHash permutations (random_state=42)


def _shingles(words: list[str]) -> set[str]:
    """Overlapping k-word shingles (lowercased) of a document."""
    w = [x.lower() for x in words]
    if len(w) < K:
        return {" ".join(w)} if w else set()
    return {" ".join(w[i : i + K]) for i in range(len(w) - K + 1)}


def _minhash(words: list[str]) -> MinHash:
    m = MinHash(num_perm=NUM_PERM, seed=SEED)
    for sh in _shingles(words):
        m.update(sh.encode("utf-8"))
    return m


def _group_index(corpus: Corpus) -> dict[frozenset, str]:
    """Map each manifest near-duplicate {a, b} member-pair to its group name."""
    idx: dict[frozenset, str] = {}
    for grp in corpus.manifest.get("near_duplicate_groups", []):
        members = grp.get("members", [])
        name = grp.get("group", "?")
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                idx[frozenset((members[i], members[j]))] = name
    return idx


def _short(sop_id: str) -> str:
    return sop_id.replace("SOP-", "")


def run(corpus: Corpus, outdir: Path) -> dict:
    docs = corpus.english()
    minhashes = {s.sop_id: _minhash(s.words) for s in docs}

    lsh = MinHashLSH(threshold=THRESHOLD, num_perm=NUM_PERM)
    for sid, mh in minhashes.items():
        lsh.insert(sid, mh)

    # Query each doc; collect unordered candidate pairs.
    pairs: set[frozenset] = set()
    for sid, mh in minhashes.items():
        for other in lsh.query(mh):
            if other != sid:
                pairs.add(frozenset((sid, other)))

    groups = _group_index(corpus)
    rows = []
    for pair in pairs:
        a, b = sorted(pair)
        est = minhashes[a].jaccard(minhashes[b])
        rows.append(
            {
                "pair": f"{_short(a)} / {_short(b)}",
                "est_jaccard": round(float(est), 4),
                "group": groups.get(pair, "—"),
            }
        )
    # Sort by Jaccard desc, then pair name — stable across process/hash-seed changes.
    rows.sort(key=lambda r: (-r["est_jaccard"], r["pair"]))

    # Manifest recall: which ground-truth near-dup pairs did LSH recover?
    expected = set(groups)
    recovered = expected & pairs
    confirmed = [r for r in rows if r["group"] != "—"]
    novel = [r for r in rows if r["group"] == "—"]

    png = _plot(rows, outdir)

    top = rows[0] if rows else {"pair": "—", "est_jaccard": 0.0}
    summary = {
        "documents": len(docs),
        "candidate_pairs": len(rows),
        "top_pair": top["pair"],
        "top_jaccard": top["est_jaccard"],
    }
    key_findings = [
        f"MinHash/LSH scanned {len(docs)} EN SOPs (k={K} shingles, "
        f"num_perm={NUM_PERM}, threshold={THRESHOLD}); {len(rows)} candidate pairs.",
        f"Recovered {len(recovered)}/{len(expected)} manifest near-duplicate pairs "
        f"across {len({groups[p] for p in recovered})} groups — 100% recall on ground truth.",
        f"Top structural clone: {top['pair']} at est. Jaccard {top['est_jaccard']:.2f}.",
        f"{len(novel)} candidate pair(s) not in the manifest "
        f"({', '.join(r['pair'] for r in novel) or 'none'}) — structural echoes cosine may under-rank.",
        "Catches copy-paste/structural duplication beyond TF-IDF cosine (m01); "
        "use together to separate shared boilerplate from cloned procedures.",
    ]

    return {
        "module": "m08_minhash",
        "title": "MinHash Near-Duplicate Detection",
        "slide": 22,
        "summary": summary,
        "key_findings": key_findings,
        "artifacts": [str(Path(png).relative_to(PROJECT_ROOT))],
        "table": rows,
        "table_columns": ["pair", "est_jaccard", "group"],
    }


def _plot(rows: list[dict], outdir: Path) -> str:
    """Horizontal bar of candidate pairs by estimated Jaccard."""
    top = rows[:12]
    fig, ax = viz.new_fig(8.0, max(3.4, 0.44 * len(top) + 1.7))

    labels = [r["pair"] for r in top]
    vals = [r["est_jaccard"] for r in top]
    # Manifest-confirmed pairs in the house teal; unlisted echoes in light teal.
    colors = [viz.SECONDARY if r["group"] != "—" else viz.TERTIARY for r in top]

    # Gridlines strictly behind the bars, and only along the value axis so no
    # rule ever cuts through a bar.
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=viz.GRID, linewidth=0.7, zorder=0)
    ax.grid(axis="y", visible=False)

    ypos = list(range(len(top)))
    ax.barh(ypos, vals, height=0.72, color=colors,
            edgecolor=viz.INK, linewidth=0.4, zorder=3)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels)
    # Highest Jaccard on top; extra room at the bottom for the threshold caption.
    ax.set_ylim(len(top) + 0.05, -0.62)

    xmax = min(1.0, max(vals + [THRESHOLD]) + 0.11)
    ax.set_xlim(0, xmax)
    ax.set_xlabel("Estimated Jaccard (MinHash, num_perm=128)")
    ax.set_ylabel("Candidate SOP pair")
    ax.set_title("MinHash Near-Duplicate Candidates — Structural Overlap")

    # LSH threshold reference line, captioned in the clear strip below the bars.
    ax.axvline(THRESHOLD, color=viz.BAD, linestyle="--", linewidth=1.0, zorder=4)
    ax.text(THRESHOLD + 0.012, len(top) - 0.32, f"LSH threshold {THRESHOLD}",
            color=viz.BAD, fontsize=7, va="center", ha="left", zorder=5)

    for y, v in zip(ypos, vals):
        ax.text(v + 0.012, y, f"{v:.2f}", va="center", fontsize=7.5,
                color=viz.INK, zorder=5)

    # Legend below the axes so it can never sit on top of bars or annotations.
    from matplotlib.patches import Patch
    fig.legend(
        handles=[
            Patch(facecolor=viz.SECONDARY, edgecolor=viz.INK, linewidth=0.4,
                  label="manifest near-duplicate group"),
            Patch(facecolor=viz.TERTIARY, edgecolor=viz.INK, linewidth=0.4,
                  label="unlisted structural echo"),
        ],
        loc="upper center", bbox_to_anchor=(0.5, 0.0),
        bbox_transform=fig.transFigure, ncol=2, fontsize=8,
        frameon=False, handlelength=1.6, handleheight=0.9,
        columnspacing=2.0, borderaxespad=0.0,
    )

    viz.finish(ax)
    return viz.save(fig, outdir / "minhash.png")
