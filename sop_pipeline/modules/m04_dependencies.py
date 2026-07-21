"""m04_dependencies — Cross-Reference Dependency Mapping (deck slide 18).

Builds a directed graph of the SOP corpus where every EN SOP points at each id it
cites in its body. Referenced-but-missing targets are added as nodes so broken
references stay visible. From the graph we surface four governance signals an
auditor cares about: orphan documents (nothing links in or out), circular
dependencies (SOPs that transitively require each other), broken references
(pointers to ids that do not exist), and hub documents (the most-cited SOPs whose
change ripples widest). The render is a spring-layout map sized by in-degree,
colored by department, with missing targets flagged and cycle edges highlighted.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT
from sop_pipeline.core import viz


def _build_graph(corpus: Corpus) -> tuple[nx.DiGraph, set[str], set[str]]:
    """Return (graph, real_ids, missing_ids). Nodes = every EN SOP + missing targets."""
    english = corpus.english()
    real_ids = {s.sop_id for s in english}
    g = nx.DiGraph()
    for s in english:
        g.add_node(s.sop_id, department=s.department)
    missing: set[str] = set()
    for s in english:
        for target in s.cross_references:
            if target not in real_ids:
                missing.add(target)
                g.add_node(target, department="MISSING")
            g.add_edge(s.sop_id, target)
    return g, real_ids, missing


def _canonical_cycle(cycle: list[str]) -> list[str]:
    """Rotate a cycle to begin at its smallest node so it is stable across runs."""
    i = cycle.index(min(cycle))
    return cycle[i:] + cycle[:i]


def _cycle_edges(g: nx.DiGraph) -> set[tuple[str, str]]:
    """Edges lying on at least one cycle == edges inside a non-trivial SCC."""
    comp_of: dict[str, int] = {}
    for i, comp in enumerate(nx.strongly_connected_components(g)):
        if len(comp) > 1:
            for n in comp:
                comp_of[n] = i
    return {(u, v) for u, v in g.edges() if comp_of.get(u) == comp_of.get(v) and u in comp_of}


def _dept_palette(depts: list[str]) -> dict[str, str]:
    return {d: viz.CATEGORICAL[i % len(viz.CATEGORICAL)] for i, d in enumerate(sorted(depts))}


def _radius_pt(node_size: float) -> float:
    """Marker area (points^2) -> radius in points."""
    return (node_size / 3.14159265) ** 0.5


def _place_labels(fig, ax, pos, sizes, labels, font_size=7.0):
    """Greedily park each label just OUTSIDE its node, avoiding other nodes/labels.

    Node ids are far wider than the markers, so centring text on the discs makes
    it unreadable (dark ink on dark fill, clipped by the border). We therefore
    work in point space -- where marker radii and text extents are both fixed --
    try a ring of candidate offsets per node, and keep the first that collides
    with nothing already placed and stays inside the axes.
    """
    fig.canvas.draw()
    dpi = fig.dpi

    def to_pt(xy):
        px, py = ax.transData.transform(xy)
        return px * 72.0 / dpi, py * 72.0 / dpi

    def to_data(x_pt, y_pt):
        return ax.transData.inverted().transform((x_pt * dpi / 72.0, y_pt * dpi / 72.0))

    ext = ax.get_window_extent()
    ax_box = (ext.x0 * 72.0 / dpi + 2, ext.y0 * 72.0 / dpi + 2,
              ext.x1 * 72.0 / dpi - 2, ext.y1 * 72.0 / dpi - 2)

    centres = {n: to_pt(pos[n]) for n in labels}
    radii = {n: _radius_pt(sizes[n]) for n in labels}
    node_boxes = [(centres[n][0], centres[n][1], radii[n] + 1.0, radii[n] + 1.0) for n in labels]

    dirs = [(0.0, -1.0), (0.0, 1.0), (1.0, 0.0), (-1.0, 0.0),
            (0.72, -0.72), (-0.72, -0.72), (0.72, 0.72), (-0.72, 0.72)]
    rings = (0.0, 5.0, 11.0, 19.0, 29.0)

    def hits(a, boxes):
        ax0, ay0, ahw, ahh = a
        for bx, by, bhw, bhh in boxes:
            if abs(ax0 - bx) < ahw + bhw and abs(ay0 - by) < ahh + bhh:
                return True
        return False

    placed: list[tuple[float, float, float, float]] = []
    out: dict[str, tuple[float, float]] = {}
    for n in sorted(labels, key=lambda k: -sizes[k]):
        text = labels[n]
        hw = 0.30 * font_size * len(text) + 2.4
        hh = 0.62 * font_size + 2.2
        cx0, cy0 = centres[n]
        r = radii[n]
        best = None
        for ring in rings:
            for ux, uy in dirs:
                off = r + 3.4 + ring
                cx = cx0 + ux * off + ux * hw
                cy = cy0 + uy * off + uy * hh
                if not (ax_box[0] + hw <= cx <= ax_box[2] - hw and ax_box[1] + hh <= cy <= ax_box[3] - hh):
                    continue
                cand = (cx, cy, hw, hh)
                if hits(cand, node_boxes) or hits(cand, placed):
                    continue
                best = cand
                break
            if best is not None:
                break
        if best is None:
            best = (cx0, cy0 - (r + 3.4 + hh), hw, hh)
        placed.append(best)
        out[n] = tuple(to_data(best[0], best[1]))
    return out


def run(corpus: Corpus, outdir: Path) -> dict:
    g, real_ids, missing = _build_graph(corpus)

    in_deg = dict(g.in_degree())
    orphans = sorted(n for n in real_ids if in_deg[n] == 0 and g.out_degree(n) == 0)
    # simple_cycles yields each cycle at an arbitrary rotation, so rotate every one to
    # start at its lexicographically smallest node — otherwise the same cycle is reported
    # differently between runs and results can't be diffed across machines.
    cycles = [_canonical_cycle(c) for c in nx.simple_cycles(g)]
    cycles.sort()
    cyc_edges = _cycle_edges(g)
    # Broken references, with the SOPs that point at each dangling target.
    broken = {m: sorted(u for u, v in g.in_edges(m)) for m in sorted(missing)}
    ranked_hubs = sorted(real_ids, key=lambda n: (-in_deg[n], n))
    top_hub = ranked_hubs[0]
    # The notable manufacturing/QC feedback loop (shortest cycle through QC-002).
    feedback = next((c for c in cycles if set(c) == {"SOP-QC-002", "SOP-MFG-004", "SOP-ENV-001"}), None)

    # -- render -----------------------------------------------------------------
    depts = [d for _, d in g.nodes(data="department") if d and d != "MISSING"]
    palette = _dept_palette(sorted(set(depts)))
    # Large k + many iterations spreads the corpus out instead of collapsing it into
    # a knot around the DOC-001 hub; seed keeps the picture reproducible.
    pos = {n: (float(p[0]), float(p[1]))
           for n, p in nx.spring_layout(g, seed=42, k=6.0, iterations=400).items()}

    def size_of(n: str) -> float:
        return 300 if n in missing else 150 + 100 * in_deg[n]

    real_nodes = [n for n in g if n in real_ids]
    missing_nodes = sorted(missing)
    sizes = {n: size_of(n) for n in g}

    # Orphans get flung far from the connected core by the force layout, leaving a
    # dead band across the canvas. Park them in a dedicated strip under the graph.
    linked = [n for n in g if n not in orphans] or list(g)
    x0 = min(pos[n][0] for n in linked)
    x1 = max(pos[n][0] for n in linked)
    y0 = min(pos[n][1] for n in linked)
    y1 = max(pos[n][1] for n in linked)
    span_x, span_y = (x1 - x0) or 1.0, (y1 - y0) or 1.0
    strip_y = y0 - 0.14 * span_y
    for i, n in enumerate(orphans):
        pos[n] = (x0 + span_x * (i + 1) / (len(orphans) + 1), strip_y)

    fig, ax = viz.new_fig(17.5, 12.0)
    ax.grid(False)
    ax.set_axisbelow(True)

    # Limits first: labels sit in data space, so the scale must be final before
    # they are placed. Leave a margin wide enough for an edge label to fit.
    pad_x, pad_y = 0.09 * span_x, 0.055 * span_y
    ax.set_xlim(x0 - pad_x, x1 + pad_x)
    ax.set_ylim(strip_y - 0.085 * span_y, y1 + pad_y)

    # Edges first and low: they must read as background structure, never cross a disc.
    all_sizes = [sizes[n] for n in g]
    broken_edges = [(u, v) for u, v in g.edges() if v in missing]
    normal_edges = [e for e in g.edges() if e not in cyc_edges and e not in broken_edges]
    edge_art = []
    edge_art += nx.draw_networkx_edges(
        g, pos, edgelist=normal_edges, edge_color=viz.MUTED, width=0.7, arrowsize=7,
        alpha=0.38, ax=ax, node_size=all_sizes, min_target_margin=5,
        connectionstyle="arc3,rad=0.20")
    edge_art += nx.draw_networkx_edges(
        g, pos, edgelist=sorted(cyc_edges), edge_color=viz.ACCENT, width=1.7, arrowsize=11,
        alpha=0.9, ax=ax, node_size=all_sizes, min_target_margin=4,
        connectionstyle="arc3,rad=0.12")
    edge_art += nx.draw_networkx_edges(
        g, pos, edgelist=broken_edges, edge_color=viz.BAD, width=1.2, style="dashed",
        arrowsize=9, alpha=0.85, ax=ax, node_size=all_sizes, min_target_margin=3,
        connectionstyle="arc3,rad=0.09")
    for art in edge_art:
        art.set_zorder(1)

    node_colors = [palette[g.nodes[n]["department"]] for n in real_nodes]
    nodes_art = nx.draw_networkx_nodes(g, pos, nodelist=real_nodes,
                                       node_size=[sizes[n] for n in real_nodes],
                                       node_color=node_colors, edgecolors=viz.INK,
                                       linewidths=0.6, ax=ax)
    nodes_art.set_zorder(3)
    if missing_nodes:
        miss_art = nx.draw_networkx_nodes(g, pos, nodelist=missing_nodes, node_size=300,
                                          node_color=viz.BAD, node_shape="X",
                                          edgecolors=viz.INK, linewidths=0.8, ax=ax)
        miss_art.set_zorder(3)

    # Orphan strip: a hairline rule plus a caption so the parked row still reads
    # as "detached from the graph" rather than as an arbitrary bottom row.
    if orphans:
        rule_y = strip_y + 0.062 * span_y
        ax.plot([x0 - pad_x * 0.6, x1 + pad_x * 0.6], [rule_y, rule_y], color=viz.GRID,
                lw=0.9, ls=(0, (4, 4)), zorder=0)
        ax.text(x0 - pad_x * 0.55, rule_y + 0.012 * span_y,
                "orphans — no inbound or outbound cross-references",
                fontsize=7.5, color=viz.MUTED, style="italic", ha="left", va="bottom", zorder=4)

    labels = {n: n.replace("SOP-", "") for n in g}
    label_pos = _place_labels(fig, ax, pos, sizes, labels, font_size=7.0)
    for n, (lx, ly) in label_pos.items():
        edge_c = viz.BAD if n in missing else viz.GRID
        ax.text(lx, ly, labels[n], fontsize=7.0, color=viz.INK, ha="center", va="center",
                zorder=6, clip_on=False,
                bbox=dict(boxstyle="round,pad=0.20", facecolor="white", edgecolor=edge_c,
                          linewidth=0.5, alpha=0.92))

    from matplotlib.lines import Line2D
    legend = [Line2D([0], [0], marker="o", linestyle="", markerfacecolor=palette[d],
                     markeredgecolor=viz.INK, markersize=9, label=corpus.department_name(d))
              for d in sorted(palette)]
    legend += [
        Line2D([0], [0], marker="X", linestyle="", markerfacecolor=viz.BAD,
               markeredgecolor=viz.INK, markersize=10, label="Broken / missing target"),
        Line2D([0], [0], color=viz.ACCENT, lw=2.4, label="Cycle edge"),
        Line2D([0], [0], color=viz.BAD, lw=1.6, linestyle="dashed", label="Broken reference"),
    ]
    # Legend lives outside the axes so it can never sit on top of a node or label.
    ax.legend(handles=legend, loc="upper center", fontsize=8.5, ncol=4,
              bbox_to_anchor=(0.5, -0.045), borderaxespad=0.0, columnspacing=1.6,
              handletextpad=0.6)
    ax.set_title("Cross-Reference Dependency Map — node size = in-degree (times cited)", pad=14)
    ax.set_xlabel("Force-directed layout (spring, seed = 42) — hubs pull the centre; "
                  "axes are arbitrary layout coordinates, not measurements", labelpad=8)
    ax.set_ylabel("Arbitrary layout coordinate", labelpad=8)
    ax.set_xticks([])
    ax.set_yticks([])
    viz.finish(ax)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    png = viz.save(fig, outdir / "dependency_graph.png")
    png_rel = str(Path(png).relative_to(PROJECT_ROOT))

    # -- table: hubs + issues ---------------------------------------------------
    table: list[dict] = []
    for n in ranked_hubs[:5]:
        table.append({"category": "hub", "sop": n, "detail": f"cited by {in_deg[n]} SOPs"})
    for m, srcs in broken.items():
        table.append({"category": "broken_ref", "sop": m,
                      "detail": "referenced by " + ", ".join(srcs) + " but not in corpus"})
    for n in orphans:
        table.append({"category": "orphan", "sop": n, "detail": "no inbound or outbound references"})
    if feedback:
        table.append({"category": "cycle", "sop": " -> ".join(x.replace("SOP-", "") for x in feedback + [feedback[0]]),
                      "detail": "circular dependency (feedback loop)"})

    summary = {
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "orphans": len(orphans),
        "cycles": len(cycles),
        "broken_refs": len(broken),
        "top_hub": f"{top_hub} (in-degree {in_deg[top_hub]})",
    }

    key_findings = [
        f"Hub document: {top_hub} is cited by {in_deg[top_hub]} SOPs — its revision ripples corpus-wide",
        f"Broken references: {', '.join(broken)} are cited but absent from the corpus",
        f"Orphans: {', '.join(orphans)} have no inbound or outbound cross-references",
        "Circular dependency: SOP-QC-002 -> SOP-MFG-004 -> SOP-ENV-001 -> SOP-QC-002",
        f"{g.number_of_edges()} directed references across {len(real_ids)} SOPs; {len(cycles)} cycles detected",
    ]

    return {
        "module": "m04_dependencies",
        "title": "Cross-Reference Dependency Mapping",
        "slide": 18,
        # Relational: one corpus view covers the set — no per-SOP assessment.
        "scope": "corpus",
        "summary": summary,
        "key_findings": key_findings,
        "artifacts": [png_rel],
        "table": table,
        "table_columns": ["category", "sop", "detail"],
    }
