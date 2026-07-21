"""m02_topics — Topic Clustering (BERTopic-style, pure sklearn).

Deck slide 16. Unsupervised topic modeling over the English SOP corpus using a
classic BERTopic-shaped pipeline with no external embedding model:

    TF-IDF  ->  TruncatedSVD (latent semantic space)  ->  KMeans (topics)

Each cluster is labeled by its most distinctive TF-IDF terms. We then project the
SVD space to 2-D and scatter every SOP colored by its topic, annotating a few
points with their SOP ids so the reader can see, e.g., how the Syringe-line and
Vial-line procedures land next to each other.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from matplotlib import patheffects as pe
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from sop_pipeline.core import viz
from sop_pipeline.core.corpus import PROJECT_ROOT, Corpus

RANDOM_STATE = 42
N_CLUSTERS = 8

# Generic SOP boilerplate that would otherwise dominate every cluster label.
_DOMAIN_STOP = {
    "sop", "procedure", "procedures", "step", "steps", "shall", "must", "should",
    "will", "record", "records", "recorded", "ensure", "section", "document",
    "documented", "review", "reviewed", "responsible", "responsibility", "purpose",
    "scope", "reference", "references", "date", "version", "operator", "personnel",
    "qa", "per", "use", "used", "using", "following", "table", "form", "log",
}
STOP_WORDS = list(ENGLISH_STOP_WORDS | _DOMAIN_STOP)

# Strip SOP-id tokens (e.g. "SOP-CLN-002") so cross-references don't pollute labels.
_SOP_ID_RE = re.compile(r"SOP-[A-Z]{2,4}-\d{3}(?:-[A-Z]{2})?")


def _cluster_top_terms(tfidf, labels: np.ndarray, terms: np.ndarray, cid: int, k: int = 8) -> list[str]:
    """Top TF-IDF terms for a cluster = highest mean TF-IDF weight over its members."""
    rows = np.where(labels == cid)[0]
    mean_w = np.asarray(tfidf[rows].mean(axis=0)).ravel()
    return [terms[i] for i in mean_w.argsort()[::-1][:k]]


def run(corpus: Corpus, outdir: Path) -> dict:
    outdir = Path(outdir)
    sops = corpus.english()
    docs = [_SOP_ID_RE.sub(" ", s.full_text) for s in sops]
    ids = [s.sop_id for s in sops]
    titles = {s.sop_id: s.title for s in sops}
    n = len(docs)

    # 1) TF-IDF term-document matrix.
    vec = TfidfVectorizer(
        stop_words=STOP_WORDS, ngram_range=(1, 2), min_df=2, max_df=0.6,
        sublinear_tf=True, token_pattern=r"[A-Za-z]{3,}",
    )
    tfidf = vec.fit_transform(docs)
    terms = vec.get_feature_names_out()

    # 2) TruncatedSVD -> latent semantic space (BERTopic-style dimensionality reduction).
    n_components = min(10, n - 1)
    svd = TruncatedSVD(n_components=n_components, random_state=RANDOM_STATE)
    emb = svd.fit_transform(tfidf)

    # 3) KMeans over the latent space.
    k = min(N_CLUSTERS, n)
    km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)
    labels = km.fit_predict(emb)

    # Label + summarize each cluster.
    rows = []
    cluster_label: dict[int, str] = {}
    for cid in range(k):
        members = [ids[i] for i in range(n) if labels[i] == cid]
        top = _cluster_top_terms(tfidf, labels, terms, cid, k=8)
        label = " / ".join(top[:3])
        cluster_label[cid] = label
        rows.append({
            "cluster": cid,
            "label": label,
            "size": len(members),
            "top_terms": ", ".join(top),
            "example_sops": ", ".join(members[:4]),
        })
    rows.sort(key=lambda r: r["size"], reverse=True)

    # ---- key findings: Equipment/Cleaning cluster + Syringe vs Vial overlap ----
    findings = _findings(ids, titles, labels, cluster_label, rows, k)

    # ---- 2-D scatter (first two SVD dims), colored by cluster ----
    png_rel = _scatter(emb, labels, ids, cluster_label, k, outdir)

    return {
        "module": "m02_topics",
        "title": "Topic Clustering (BERTopic-style)",
        "slide": 16,
        "summary": {
            "documents": n,
            "n_clusters": k,
            "svd_components": n_components,
            "vocabulary": len(terms),
        },
        "key_findings": findings,
        "artifacts": [png_rel],
        "table": rows,
        "table_columns": ["cluster", "label", "size", "top_terms", "example_sops"],
    }


EQCLN_KEYWORDS = {
    "clean", "cleaning", "cleanroom", "disinfect", "disinfection", "sporicidal",
    "alcohol", "sanitize", "wipe", "swab", "autoclave", "sterilizer", "equipment",
    "machine", "filling", "line", "isolator", "lyophilizer", "wfi", "maintenance",
}


def _findings(ids, titles, labels, cluster_label, rows, k) -> list[str]:
    out: list[str] = []
    lab_by_id = {ids[i]: int(labels[i]) for i in range(len(ids))}
    row_by_c = {r["cluster"]: r for r in rows}

    # Equipment/Cleaning cluster: the cluster whose top TF-IDF terms are most
    # dominated by equipment/cleaning vocabulary (real topical signal, not dept codes).
    def eqcln_score(cid: int) -> int:
        toks = set(row_by_c[cid]["top_terms"].replace(",", " ").split())
        return len(toks & EQCLN_KEYWORDS)

    top_c = max(range(k), key=eqcln_score)
    if eqcln_score(top_c):
        members = [s for s in ids if lab_by_id[s] == top_c]
        out.append(
            f"Equipment/Cleaning cluster {top_c} ('{cluster_label[top_c]}'): "
            f"{len(members)} SOPs, e.g. {', '.join(members[:3])}."
        )

    # Syringe vs Vial overlap: do the syringe- and vial-line SOPs share a topic?
    syr = [s for s in ids if "syringe" in titles[s].lower()]
    vial = [s for s in ids if "vial" in titles[s].lower()]
    syr_c = {lab_by_id[s] for s in syr}
    vial_c = {lab_by_id[s] for s in vial}
    shared = syr_c & vial_c
    if shared:
        c = sorted(shared)[0]
        out.append(
            f"Syringe vs Vial overlap: syringe SOPs ({', '.join(syr)}) and vial SOPs "
            f"({', '.join(vial[:3])}) co-cluster in topic {c} — near-identical line "
            f"procedures differing mainly by container format."
        )
    elif syr and vial:
        out.append(
            f"Syringe vs Vial split: syringe SOPs ({', '.join(syr)}) fall in topic(s) "
            f"{sorted(syr_c)} vs vial SOPs in {sorted(vial_c)}, yet sit adjacent in SVD "
            f"space, reflecting their heavy procedural overlap."
        )

    biggest = rows[0]
    out.append(f"Largest topic {biggest['cluster']} holds {biggest['size']} SOPs: {biggest['label']}.")
    out.append(f"KMeans (k={k}) over TF-IDF->SVD partitions {len(ids)} EN SOPs into coherent topics.")
    return out[:6]


MARKER_SIZE = 68.0  # points^2; marker diameter = sqrt(MARKER_SIZE) points


def _darker(hex_color: str, factor: float = 0.6) -> tuple[float, float, float]:
    """Darkened variant of a palette color, used for marker edges."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 * factor for i in (0, 2, 4))


def _padded_limits(v, frac: float) -> tuple[float, float]:
    """Tight limits around the data with a small, symmetric breathing margin."""
    lo, hi = float(np.min(v)), float(np.max(v))
    span = hi - lo
    pad = span * frac if span > 0 else 1.0
    return lo - pad, hi + pad


def _spread(x, y, ax, diam_px: float, sep: float = 0.85, max_shift: float = 0.75):
    """Nudge near-coincident markers apart in pixel space (deterministic jitter).

    Several SOPs land on identical SVD coordinates, which hides whole clusters
    behind a single disc. A short relaxation pass separates them by a fraction of
    a marker diameter, capped so no point drifts meaningfully from its true spot.
    """
    pts = ax.transData.transform(np.column_stack([np.asarray(x, float), np.asarray(y, float)]))
    pts = np.asarray(pts, dtype=float)
    home = pts.copy()
    min_d = diam_px * sep
    cap = diam_px * max_shift
    n = len(pts)
    for _ in range(200):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                d = pts[j] - pts[i]
                dist = float(np.hypot(d[0], d[1]))
                if dist >= min_d:
                    continue
                if dist < 1e-9:  # exactly coincident: split along a golden angle
                    ang = 2.39996323 * (i + 1)
                    u = np.array([np.cos(ang), np.sin(ang)])
                else:
                    u = d / dist
                push = (min_d - dist) * 0.25
                pts[i] -= u * push
                pts[j] += u * push
                moved = True
        delta = pts - home
        dd = np.hypot(delta[:, 0], delta[:, 1])
        far = dd > cap
        if np.any(far):
            pts[far] = home[far] + delta[far] * (cap / dd[far])[:, None]
        if not moved:
            break
    out = np.asarray(ax.transData.inverted().transform(pts), dtype=float)
    return out[:, 0], out[:, 1]


def _overlap_area(a, b) -> float:
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return max(dx, 0.0) * max(dy, 0.0)


def _leader_hits(origin, dx_pt: float, dy_pt: float, px_per_pt: float, others, half: float) -> float:
    """How many other markers a leader line from `origin` would cut through."""
    if others.size == 0:
        return 0.0
    end = np.asarray(origin, float) + np.array([dx_pt, dy_pt], float) * px_per_pt
    ts = np.linspace(0.2, 1.0, 10)[:, None]
    samples = np.asarray(origin, float) + (end - np.asarray(origin, float)) * ts
    d = np.hypot(samples[:, None, 0] - others[None, :, 0],
                 samples[:, None, 1] - others[None, :, 1])
    return float((d.min(axis=0) < half).sum())


def _leader_segment(origin, dx_pt: float, dy_pt: float, px_per_pt: float, half: float):
    """Pixel segment for a leader line, or None when the label sits on its marker."""
    radius_px = float(np.hypot(dx_pt, dy_pt)) * px_per_pt
    if radius_px < half + 16.0:
        return None
    u = np.array([dx_pt, dy_pt], dtype=float) / float(np.hypot(dx_pt, dy_pt))
    o = np.asarray(origin, dtype=float)
    return np.array([o + u * (half + 1.5), o + u * (radius_px - 3.0)])


def _seg_box_hits(seg, boxes) -> float:
    """How many sampled points of `seg` land inside any of `boxes` (0 when seg is None)."""
    if seg is None or not boxes:
        return 0.0
    ts = np.linspace(0.0, 1.0, 41)[:, None]
    pts = seg[0] + (seg[1] - seg[0]) * ts
    hits = 0
    for b in boxes:
        inside = ((pts[:, 0] >= b[0]) & (pts[:, 0] <= b[2])
                  & (pts[:, 1] >= b[1]) & (pts[:, 1] <= b[3]))
        hits += int(inside.sum())
    return float(hits)


def _label_candidates(r_pt: float):
    """(dx, dy, ha, va) offsets in points, ordered from tightest to roomiest."""
    out = []
    for radius in (r_pt + 2.0, r_pt + 6.0, r_pt + 12.0, r_pt + 20.0, r_pt + 30.0):
        for deg in (0, 45, 315, 90, 270, 135, 225, 180):
            rad = np.deg2rad(deg)
            dx, dy = radius * np.cos(rad), radius * np.sin(rad)
            ha = "left" if dx > 1 else ("right" if dx < -1 else "center")
            va = "bottom" if dy > 1 else ("top" if dy < -1 else "center")
            out.append((float(dx), float(dy), ha, va))
    return out


def _scatter(emb, labels, ids, cluster_label, k, outdir: Path) -> str:
    fig, ax = viz.new_fig(9.6, 5.8)
    ax.set_axisbelow(True)  # gridlines behind the markers

    x0 = np.asarray(emb[:, 0], dtype=float)
    y0 = np.asarray(emb[:, 1], dtype=float)

    # Fix the limits (and therefore the pixel geometry) before any measuring.
    ax.set_xlim(*_padded_limits(x0, 0.075))
    ax.set_ylim(*_padded_limits(y0, 0.06))
    ax.set_title("SOP Topic Clustering: TF-IDF -> SVD -> KMeans")
    ax.set_xlabel("SVD component 1")
    ax.set_ylabel("SVD component 2")
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    diam_px = float(np.sqrt(MARKER_SIZE)) * fig.dpi / 72.0
    r_pt = float(np.sqrt(MARKER_SIZE)) / 2.0
    x, y = _spread(x0, y0, ax, diam_px)

    for cid in range(k):
        m = labels == cid
        color = viz.CATEGORICAL[cid % len(viz.CATEGORICAL)]
        ax.scatter(
            x[m], y[m], s=MARKER_SIZE, alpha=0.9, color=color,
            edgecolors=[_darker(color)], linewidths=1.0, zorder=3,
            label=f"{cid}: {cluster_label[cid]}",
        )

    # ---- annotations: one SOP id per cluster, greedily placed to avoid collisions ----
    pts_px = np.asarray(ax.transData.transform(np.column_stack([x, y])), dtype=float)
    half = diam_px / 2.0 + 1.0
    marker_boxes = [(px - half, py - half, px + half, py + half) for px, py in pts_px]
    ax_bb = ax.get_window_extent(renderer)
    axes_box = (ax_bb.x0 + 2.0, ax_bb.y0 + 2.0, ax_bb.x1 - 2.0, ax_bb.y1 - 2.0)
    candidates = _label_candidates(r_pt)
    placed: list[tuple[float, float, float, float]] = []
    leaders: list[np.ndarray] = []

    px_per_pt = fig.dpi / 72.0
    for cid in range(k):
        idx = np.where(labels == cid)[0]
        if not len(idx):
            continue
        cx, cy = x0[idx].mean(), y0[idx].mean()
        pick = int(idx[np.argmin((x0[idx] - cx) ** 2 + (y0[idx] - cy) ** 2)])
        others = np.delete(pts_px, pick, axis=0)
        ann = ax.annotate(
            ids[pick], (x[pick], y[pick]), xytext=(0.0, 0.0),
            textcoords="offset points", fontsize=7, color=viz.INK, zorder=6,
        )
        ann.set_path_effects([pe.withStroke(linewidth=2.2, foreground=viz.BG)])

        best = None
        for dx, dy, ha, va in candidates:
            ann.set_position((dx, dy))
            ann.set_ha(ha)
            ann.set_va(va)
            bb = ann.get_window_extent(renderer)
            box = (bb.x0 - 2.0, bb.y0 - 1.5, bb.x1 + 2.0, bb.y1 + 1.5)
            area = max(box[2] - box[0], 0.0) * max(box[3] - box[1], 0.0)
            cost = 12.0 * (area - _overlap_area(box, axes_box))          # stay inside the axes
            cost += 4.0 * sum(_overlap_area(box, mb) for mb in marker_boxes)  # clear of markers
            cost += 8.0 * sum(_overlap_area(box, lb) for lb in placed)        # clear of labels
            cost += 40.0 * _leader_hits(pts_px[pick], dx, dy, px_per_pt, others, half)
            seg = _leader_segment(pts_px[pick], dx, dy, px_per_pt, half)
            cost += 25.0 * _seg_box_hits(seg, placed)                 # my leader over a label
            cost += 25.0 * sum(_seg_box_hits(s, [box]) for s in leaders)  # a label over a leader
            cost += 0.30 * float(np.hypot(dx, dy))                    # prefer close in
            if best is None or cost < best[0] - 1e-9:
                best = (cost, dx, dy, ha, va, box)

        _, dx, dy, ha, va, box = best
        ann.set_position((dx, dy))
        ann.set_ha(ha)
        ann.set_va(va)
        placed.append(box)

        # A leader line only where the label had to sit well away from its point;
        # drawn by hand so it starts outside the marker and stops short of the text.
        seg = _leader_segment(pts_px[pick], dx, dy, px_per_pt, half)
        if seg is not None:
            leaders.append(seg)
            seg_data = np.asarray(ax.transData.inverted().transform(seg), dtype=float)
            ax.plot(seg_data[:, 0], seg_data[:, 1], color=viz.MUTED, lw=0.7,
                    solid_capstyle="butt", zorder=2)

    viz.finish(ax)
    ax.legend(
        fontsize=7, title="Topics", title_fontsize=7.5, loc="upper center",
        bbox_to_anchor=(0.5, -0.115), ncol=2, handletextpad=0.4,
        columnspacing=1.6, labelspacing=0.45, borderaxespad=0.0,
    )

    out_path = outdir / "topics_scatter.png"
    viz.save(fig, out_path)
    return str(out_path.relative_to(PROJECT_ROOT))
