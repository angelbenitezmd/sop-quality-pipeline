"""m10_visual_aids — deck slide 24, "AI-Generated Visual Aids".

Takes a dense, numbered SOP procedure and auto-generates a top-down flowchart:
a wall of prose steps becomes rounded process boxes plus an amber decision
diamond for any conditional ("If ... , ..."). Two artifacts are emitted — a
rendered matplotlib PNG and portable Mermaid source (``flowchart TD``) that a
QMS/wiki can embed directly. The demonstrated value: one visual aid replaces
several pages of procedure text an operator would otherwise read line by line.
"""

from __future__ import annotations

import math
import random
import re
import textwrap
from pathlib import Path

import matplotlib.patches as mpatches

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT
from sop_pipeline.core import viz

random.seed(42)  # determinism (rule 2) — no stochastic paths, but seed anyway.

# A numbered step line: "1. text" / "  2. text".
_NUM_RE = re.compile(r"^(\s*)(\d+)\.\s+(.*)")
# Conditional / branch cues that make a step a decision point.
_DECISION_RE = re.compile(r"\b(if|when|unless|whenever|in the event|should any)\b", re.I)
# Split "If <cond>, <action>" or "If <cond> then <action>".
_COND_RE = re.compile(r"^\s*(?:if|when|whenever|unless)\s+(.*?)(?:\s*,\s*|\s+then\s+)(.+)$", re.I)


# ---------------------------------------------------------------------------
# Parsing: pull the best numbered procedure block out of an SOP body.
# ---------------------------------------------------------------------------
def _numbered_blocks(body: str) -> list[tuple[str, list[tuple[int, str]]]]:
    """Return (preceding_heading, [(n, text), ...]) for each numbered list block.

    Works on raw body text so it handles markdown, ALL-CAPS and Roman-numeral
    headings alike (the shared Section splitter misses Roman headings)."""
    lines = body.splitlines()
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    cur: list[tuple[int, str]] = []
    head = ""
    for i, ln in enumerate(lines):
        m = _NUM_RE.match(ln)
        if m:
            if not cur:  # first item — remember the nearest heading above it
                j = i - 1
                while j >= 0 and not lines[j].strip():
                    j -= 1
                head = lines[j].strip() if j >= 0 else ""
            cur.append((int(m.group(2)), m.group(3).strip()))
        elif ln.strip() and cur:
            if ln.startswith((" ", "\t")):  # wrapped continuation of last step
                n, t = cur[-1]
                cur[-1] = (n, f"{t} {ln.strip()}".strip())
            else:  # unindented prose ends the block
                blocks.append((head, cur))
                cur = []
        elif not ln.strip() and cur:  # blank line: continue only if a number follows
            k = i + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            if not (k < len(lines) and _NUM_RE.match(lines[k])):
                blocks.append((head, cur))
                cur = []
    if cur:
        blocks.append((head, cur))
    return blocks


def _best_procedure(sop) -> tuple[str, list[tuple[int, str]]]:
    """The longest numbered block in an SOP (its procedure), or ("", [])."""
    blocks = _numbered_blocks(sop.body)
    if not blocks:
        return "", []
    return max(blocks, key=lambda b: len(b[1]))


def _select_target(corpus: Corpus):
    """Deterministically pick the EN SOP whose numbered procedure best shows a
    flowchart: most steps that also contains at least one decision point."""
    ranked = []
    for sop in corpus.english():
        head, steps = _best_procedure(sop)
        if len(steps) < 3:
            continue
        decisions = sum(1 for _, t in steps if _DECISION_RE.search(t))
        # sort key: prefer a real decision, then more steps, then id for stability
        ranked.append(((decisions > 0, len(steps), sop.sop_id), sop, head, steps))
    ranked.sort(key=lambda r: (r[0][0], r[0][1], [-ord(c) for c in r[0][2]]), reverse=True)
    _, sop, head, steps = ranked[0]
    return sop, head, steps


# ---------------------------------------------------------------------------
# Text shaping for nodes.
# ---------------------------------------------------------------------------
def _condense(text: str, max_chars: int = 80) -> str:
    clause = re.split(r"(?<=[.;])\s", text, 1)[0].rstrip(" ;,")
    if len(clause) > max_chars:
        clause = clause[:max_chars].rsplit(" ", 1)[0] + "…"
    return clause.strip()


def _decision_parts(text: str) -> tuple[str, str]:
    """('reading is out of tolerance', 'remove ... notify ...') → (condition, action)."""
    m = _COND_RE.match(text)
    if m:
        return m.group(1).strip().rstrip("."), m.group(2).strip().rstrip(".")
    return _condense(text, 60), ""


def _mermaid_clean(text: str) -> str:
    return text.replace('"', "'").replace("±", "+/-").replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------
ARROW_Z = 1.5  # arrows sit *behind* node faces (boxes are zorder 2)


def _draw_box(ax, cx, cy, w, h, text, fc, *, rounded=True, tc="white"):
    style = "round,pad=0.02,rounding_size=0.14" if rounded else "square,pad=0.02"
    ax.add_patch(mpatches.FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h, boxstyle=style,
        linewidth=1.2, edgecolor=viz.INK, facecolor=fc, zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", color=tc,
            fontsize=8, fontweight="bold", zorder=3)


def _draw_diamond(ax, cx, cy, w, h, text, fc, *, tc=viz.INK):
    """Amber decision diamond. Text defaults to dark ink: white on amber is the
    weakest contrast pair in the palette (~2.6:1), ink on amber is ~5.9:1."""
    pts = [(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)]
    ax.add_patch(mpatches.Polygon(pts, closed=True, linewidth=1.2,
                                  edgecolor=viz.INK, facecolor=fc, zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", color=tc,
            fontsize=8, fontweight="bold", zorder=3)


def _edge_label(ax, x, y, label, *, ha="center", va="center"):
    ax.text(x, y, label, fontsize=8, color=viz.INK, ha=ha, va=va,
            bbox=dict(boxstyle="round,pad=0.16", fc="white", ec=viz.GRID, lw=0.6),
            zorder=4)


def _arrow(ax, xy_from, xy_to, *, shrink_a=1.0, shrink_b=1.0):
    ax.annotate("", xy=xy_to, xytext=xy_from, zorder=ARROW_Z,
                arrowprops=dict(arrowstyle="-|>", color=viz.MUTED, lw=1.6,
                                shrinkA=shrink_a, shrinkB=shrink_b))


def _elbow_arrow(ax, pts):
    """Orthogonally routed edge through explicit way-points; head on the last leg."""
    xs = [p[0] for p in pts[:-1]]
    ys = [p[1] for p in pts[:-1]]
    ax.plot(xs, ys, color=viz.MUTED, lw=1.6, solid_capstyle="round",
            solid_joinstyle="miter", zorder=ARROW_Z)
    _arrow(ax, pts[-2], pts[-1], shrink_a=0.0)


def _render(sop, head, steps, path: Path) -> str:
    SPINE_X, OUT_X = 3.05, 8.05
    BOX_W, BOX_H = 4.90, 1.00
    DIA_W, DIA_H = 4.00, 1.34
    TERM_W, TERM_H = 3.70, 0.80
    OUT_W, OUT_H = 4.35, 1.08
    slot = 1.45          # row pitch
    dec_extra = 0.20     # extra clearance below a diamond (room for the 'No' label)
    X_MIN, X_MAX = 0.32, 10.52   # content spans 0.60 .. 10.22 -> even side margins
    PAD_Y = 0.30

    # spine = Start terminator, one node per step, End terminator.
    spine = ["start"] + list(range(len(steps))) + ["end"]

    def _is_dec(node) -> bool:
        return isinstance(node, int) and bool(_DECISION_RE.search(steps[node][1]))

    # Row centres, top-down from y=0 (a decision row gets a little extra room below).
    ys, y = [], 0.0
    for k, node in enumerate(spine):
        if k:
            y -= slot + (dec_extra if _is_dec(spine[k - 1]) else 0.0)
        ys.append(y)

    # Limits hug the drawn content on all four sides — no dead canvas.
    top_edge = ys[0] + TERM_H / 2 + PAD_Y
    bot_edge = ys[-1] - TERM_H / 2 - PAD_Y
    fig, ax = viz.new_fig(9.9, (top_edge - bot_edge) * 0.63)
    ax.set_xlim(X_MIN, X_MAX)
    ax.set_ylim(bot_edge, top_edge)
    ax.set_axisbelow(True)
    ax.axis("off")
    ax.grid(False)

    geom = {}  # node -> (cy, half_height, half_width)
    for k, node in enumerate(spine):
        cy = ys[k]
        if node == "start":
            _draw_box(ax, SPINE_X, cy, TERM_W, TERM_H,
                      "START\nDaily verification", viz.SECONDARY)
            geom[node] = (cy, TERM_H / 2, TERM_W / 2)
        elif node == "end":
            _draw_box(ax, SPINE_X, cy, TERM_W, TERM_H,
                      "END\nVerification complete", viz.GOOD)
            geom[node] = (cy, TERM_H / 2, TERM_W / 2)
        elif _is_dec(node):
            n, text = steps[node]
            cond, action = _decision_parts(text)
            q = textwrap.fill(cond[:1].upper() + cond[1:] + "?", 18)
            _draw_diamond(ax, SPINE_X, cy, DIA_W, DIA_H, q, viz.ACCENT)
            geom[node] = (cy, DIA_H / 2, DIA_W / 2)
            # Yes branch -> exception/outcome box to the right (out-of-spec action).
            out_text = (action or text).strip()
            out_text = out_text[:1].upper() + out_text[1:]
            _draw_box(ax, OUT_X, cy, OUT_W, OUT_H,
                      textwrap.fill(out_text, 30), viz.BAD)
            x_a, x_b = SPINE_X + DIA_W / 2, OUT_X - OUT_W / 2
            _arrow(ax, (x_a, cy), (x_b, cy))
            # label sits *above* the connector, centred in the gap: clear of both nodes
            _edge_label(ax, (x_a + x_b) / 2, cy + 0.14, "Yes", va="bottom")
            geom[("out", node)] = (cy, OUT_H / 2, OUT_W / 2)
        else:
            n, text = steps[node]
            label = textwrap.fill(f"{n}. {_condense(text)}", 30)
            _draw_box(ax, SPINE_X, cy, BOX_W, BOX_H, label, viz.PRIMARY)
            geom[node] = (cy, BOX_H / 2, BOX_W / 2)

    # Sequential arrows down the spine; decisions branch "No" onward + rejoin "Yes".
    for a, b in zip(spine, spine[1:]):
        ay, ah, _ = geom[a]
        by, bh, bw = geom[b]
        _arrow(ax, (SPINE_X, ay - ah), (SPINE_X, by + bh))
        if _is_dec(a):
            _edge_label(ax, SPINE_X + 0.20, (ay - ah + by + bh) / 2, "No", ha="left")
            # Outcome box rejoins the flow: down its own column, then straight into
            # the right-hand edge of the next node (defined connection points).
            oy, oh, _ = geom[("out", a)]
            _elbow_arrow(ax, [(OUT_X, oy - oh), (OUT_X, by), (SPINE_X + bw, by)])

    handles = [
        mpatches.Patch(facecolor=viz.PRIMARY, edgecolor=viz.INK, lw=0.8,
                       label="Process step"),
        mpatches.Patch(facecolor=viz.ACCENT, edgecolor=viz.INK, lw=0.8,
                       label="Decision point"),
        mpatches.Patch(facecolor=viz.BAD, edgecolor=viz.INK, lw=0.8,
                       label="Out-of-spec action"),
        mpatches.Patch(facecolor=viz.SECONDARY, edgecolor=viz.INK, lw=0.8,
                       label="Start terminator"),
        mpatches.Patch(facecolor=viz.GOOD, edgecolor=viz.INK, lw=0.8,
                       label="End terminator"),
    ]
    # Park the key in the middle of the otherwise-empty branch column so the
    # composition is balanced instead of hugging the left edge.
    out_rows = [v[0] + v[1] for k, v in geom.items() if isinstance(k, tuple)]
    key_y = (top_edge + (max(out_rows) if out_rows else bot_edge)) / 2
    leg = ax.legend(handles=handles, loc="center", bbox_to_anchor=(OUT_X, key_y),
                    bbox_transform=ax.transData, fontsize=8.5, title="Key",
                    frameon=True, facecolor="white", edgecolor=viz.GRID,
                    framealpha=1.0, borderpad=0.8, labelspacing=0.75,
                    handlelength=1.6, handleheight=1.0)
    leg.get_title().set_fontweight("bold")
    leg.get_title().set_fontsize(9)
    leg.set_zorder(5)
    sect = re.sub(r"^[#IVXLC0-9.\s]+", "", head).strip() or "Procedure"
    ax.set_title(f"{sop.sop_id}  —  {sop.title}\n"
                 f"Auto-generated flowchart from '{sect}' ({len(steps)} numbered steps)",
                 fontsize=12, fontweight="bold")
    return viz.save(fig, path)


def _mermaid(sop, head, steps) -> str:
    lines = ["flowchart TD",
             f'    START(["START: {_mermaid_clean(sop.title)}"])']
    prev = "START"
    for i, (n, text) in enumerate(steps):
        nid = f"S{n}"
        if _DECISION_RE.search(text):
            cond, action = _decision_parts(text)
            did = f"D{n}"
            act = (action or text).strip()
            lines.append(f'    {did}{{"{_mermaid_clean(cond[:1].upper() + cond[1:])}?"}}')
            lines.append(f'    O{n}["{_mermaid_clean(act[:1].upper() + act[1:])}"]')
            lines.append(f"    {prev} --> {did}")
            lines.append(f"    {did} -- Yes --> O{n}")
            prev = did  # 'No' branch carries the main flow forward
            lines.append(f"    O{n} --> ENDN")
        else:
            lines.append(f'    {nid}["{n}. {_mermaid_clean(text)}"]')
            lines.append(f"    {prev} --> {nid}")
            prev = nid
    lines.append('    ENDN(["END: verification complete"])')
    lines.append(f"    {prev} -- No --> ENDN" if prev.startswith("D") else f"    {prev} --> ENDN")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------
def run(corpus: Corpus, outdir: Path) -> dict:
    outdir = Path(outdir)
    sop, head, steps = _select_target(corpus)
    decisions = [(n, t) for n, t in steps if _DECISION_RE.search(t)]

    png = _render(sop, head, steps, outdir / "flowchart.png")
    mmd_path = outdir / "flowchart.mmd"
    mmd_path.write_text(_mermaid(sop, head, steps), encoding="utf-8")

    # Pages replaced: legacy text procedures run ~4 numbered steps per printed
    # page once cautions, acceptance lines and sign-offs are included; branches
    # cost extra prose, so decisions bump the count.
    pages = max(1, math.ceil((len(steps) + len(decisions)) / 4))

    table = []
    for n, t in steps:
        kind = "decision" if _DECISION_RE.search(t) else "process"
        table.append({"step": n, "type": kind, "text": _condense(t, 90)})

    rel_png = str(Path(png).resolve().relative_to(PROJECT_ROOT))
    rel_mmd = str(mmd_path.resolve().relative_to(PROJECT_ROOT))
    dec_desc = f"step {decisions[0][0]} (“If {_decision_parts(decisions[0][1])[0]}…”)" \
        if decisions else "none"

    return {
        "module": "m10_visual_aids",
        "title": "AI-Generated Visual Aids",
        "slide": 24,
        "summary": {
            "sop_id": sop.sop_id,
            "steps": len(steps),
            "decisions": len(decisions),
            "pages_replaced_est": pages,
        },
        "key_findings": [
            f"Converted {sop.sop_id} '{re.sub(r'^[#IVXLC0-9.\\s]+', '', head).strip()}' "
            f"— {len(steps)} numbered text steps rendered as one top-down flowchart.",
            f"Detected {len(decisions)} decision point ({dec_desc}); drawn as an amber "
            f"diamond with Yes/No branches to an out-of-spec action.",
            f"Estimated ~{pages} page(s) of dense procedure text replaced by a single "
            f"visual aid (assumes ~4 steps per printed page).",
            "Dual output: matplotlib PNG plus portable Mermaid 'flowchart TD' source "
            "for direct embedding in a QMS or wiki.",
            "Target chosen corpus-wide and deterministically: the numbered procedure "
            "pairing the most steps with a real decision point.",
        ],
        "artifacts": [rel_png, rel_mmd],
        "table": table,
        "table_columns": ["step", "type", "text"],
    }
