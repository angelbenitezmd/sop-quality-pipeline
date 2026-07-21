"""m10_visual_aids — deck slide 24, "AI-Generated Visual Aids".

Takes a dense, numbered SOP procedure and auto-generates a top-down flowchart:
a wall of prose steps becomes rounded process boxes plus an amber decision
diamond for any conditional ("If ... , ..."). Two artifacts are emitted per
document — a rendered matplotlib PNG and portable Mermaid source
(``flowchart TD``) that a QMS/wiki can embed directly. The demonstrated value:
one visual aid replaces several pages of procedure text an operator would
otherwise read line by line.

Scope is ``per_sop``: the corpus-level flagship flowchart is kept, and every EN
SOP additionally gets its own conversion attempt under ``outdir/sops/``.
Documents written as narrative prose or bullet lists have no step sequence to
draw, so they are reported as ``n/a`` rather than given an invented diagram.
"""

from __future__ import annotations

import math
import random
import re
import textwrap
from pathlib import Path

import matplotlib.patches as mpatches

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT, split_sentences
from sop_pipeline.core import viz

random.seed(42)  # determinism (rule 2) — no stochastic paths, but seed anyway.

MIN_STEPS = 3  # fewer steps than this is a note, not a procedure worth drawing.

# A numbered step line: "1. text", "  2. text", or "Step 3: text" (EQP house style).
_NUM_RE = re.compile(
    r"^(?P<indent>\s*)(?:[Ss]tep\s+(?P<sn>\d+)\s*[.:)]|(?P<n>\d+)\.)\s+(?P<text>.*)"
)
# Conditional / branch cues that make a step a decision point.
_DECISION_RE = re.compile(r"\b(if|when|unless|whenever|in the event|should any)\b", re.I)
# Split "If <cond>, <action>" or "If <cond> then <action>".
_COND_RE = re.compile(r"^\s*(?:if|when|whenever|unless)\s+(.*?)(?:\s*,\s*|\s+then\s+)(.+)$", re.I)
# A trailing coordinated clause that is commentary rather than the branch itself.
_COORD_RE = re.compile(r",\s+(?:and|but|so|then|because|since|which|although)\s+", re.I)
# Strip "## 4.", "V.", "6.2)" style numbering from a heading (never bare letters).
_SECT_PREFIX_RE = re.compile(r"^\s*#{0,6}\s*(?:\d+(?:\.\d+)*[.)]?|[IVXLC]{1,5}[.)])\s+")


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
            cur.append((int(m.group("sn") or m.group("n")), m.group("text").strip()))
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
    flowchart: an explicitly-written "If <cond>, <action>" branch (the cleanest
    thing to draw), then the most steps, then the lowest id."""
    ranked = []
    for sop in corpus.english():
        head, steps = _best_procedure(sop)
        if len(steps) < MIN_STEPS:
            continue
        explicit = any(_COND_RE.match(t) for _, t in steps)
        decisions = sum(1 for _, t in steps if _decision_parts(t))
        ranked.append(((explicit, decisions > 0, len(steps), sop.sop_id), sop, head, steps))
    ranked.sort(key=lambda r: (r[0][0], r[0][1], r[0][2], [-ord(c) for c in r[0][3]]),
                reverse=True)
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


def _clause(text: str, max_chars: int) -> str:
    """One clause of a conditional: drop trailing commentary, then condense."""
    s = _COORD_RE.split(text.strip(), 1)[0]
    s = re.sub(r"^(?:that|the event that)\s+", "", s.strip(), flags=re.I)
    return _condense(s, max_chars).rstrip(" .;,")


def _fit(text: str, width: int, max_lines: int) -> str:
    """Wrap to `width` and hard-cap the line count so text never spills a node."""
    lines = textwrap.wrap(text, width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;…") + "…"
    return "\n".join(lines)


def _substantive(clause: str) -> bool:
    """A cue word alone ("...when tested") is not a decision — require a real clause."""
    return len(clause) >= 12 and len(clause.split()) >= 3


def _decision_parts(text: str) -> tuple[str, str] | None:
    """Split a conditional step into (condition, action), or None when the step
    has no extractable branch — those are drawn as ordinary process steps."""
    m = _COND_RE.match(text)  # "If <cond>, <action>" — the house-style form
    if m:
        cond, action = _clause(m.group(1), 54), _clause(m.group(2), 72)
        return (cond, action) if _substantive(cond) and _substantive(action) else None
    for sent in split_sentences(text):
        cue = _DECISION_RE.search(sent)
        if not cue:
            continue
        m2 = _COND_RE.match(sent[cue.start():])  # "... , if <cond>, <action>"
        if m2:
            cond, action = _clause(m2.group(1), 54), _clause(m2.group(2), 72)
        else:  # "<action> whenever <cond>" — condition trails the governing action
            cond = _clause(sent[cue.end():], 54)
            action = _clause(_COORD_RE.split(sent[:cue.start()])[-1], 72)
        if _substantive(cond) and _substantive(action):
            return cond, action
    return None


_MINOR_WORDS = {"a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to", "with"}


def _section_label(head: str) -> str:
    """'## 5. Investigation Steps' / 'V. Procedure' / 'CLEANING PROCEDURE' -> title."""
    s = _SECT_PREFIX_RE.sub("", head or "").strip(" #:-")
    if s.isupper():  # ALL-CAPS heading -> title case, minor words left lowercase
        words = [w.capitalize() for w in s.split()]
        s = " ".join(w if i == 0 or w.lower() not in _MINOR_WORDS else w.lower()
                     for i, w in enumerate(words))
    return s or "Procedure"


def _mermaid_clean(text: str) -> str:
    return text.replace('"', "'").replace("±", "+/-").replace("\n", " ").strip()


def _pages_replaced(steps, decisions) -> int:
    """Legacy text procedures run ~4 numbered steps per printed page once cautions,
    acceptance lines and sign-offs are included; branches cost extra prose."""
    return max(1, math.ceil((len(steps) + len(decisions)) / 4))


def _rel(path) -> str:
    return str(Path(path).resolve().relative_to(PROJECT_ROOT))


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
    TERM_W, TERM_H = 3.70, 0.90
    OUT_W, OUT_H = 4.35, 1.08
    slot = 1.45          # row pitch
    dec_extra = 0.20     # extra clearance below a diamond (room for the 'No' label)
    X_MIN, X_MAX = 0.32, 10.52   # content spans 0.60 .. 10.22 -> even side margins
    PAD_Y = 0.30
    sect = _section_label(head)

    # spine = Start terminator, one node per step, End terminator.
    spine = ["start"] + list(range(len(steps))) + ["end"]

    def _is_dec(node) -> bool:
        return isinstance(node, int) and _decision_parts(steps[node][1]) is not None

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
                      "START\n" + _fit(sect, 30, 2), viz.SECONDARY)
            geom[node] = (cy, TERM_H / 2, TERM_W / 2)
        elif node == "end":
            _draw_box(ax, SPINE_X, cy, TERM_W, TERM_H,
                      "END\n" + _fit(f"{sect} complete", 30, 2), viz.GOOD)
            geom[node] = (cy, TERM_H / 2, TERM_W / 2)
        elif _is_dec(node):
            n, text = steps[node]
            cond, action = _decision_parts(text)
            q = _fit(cond[:1].upper() + cond[1:] + "?", 18, 4)
            _draw_diamond(ax, SPINE_X, cy, DIA_W, DIA_H, q, viz.ACCENT)
            geom[node] = (cy, DIA_H / 2, DIA_W / 2)
            # Yes branch -> exception/outcome box to the right (out-of-spec action).
            out_text = action[:1].upper() + action[1:]
            _draw_box(ax, OUT_X, cy, OUT_W, OUT_H, _fit(out_text, 30, 3), viz.BAD)
            x_a, x_b = SPINE_X + DIA_W / 2, OUT_X - OUT_W / 2
            _arrow(ax, (x_a, cy), (x_b, cy))
            # label sits *above* the connector, centred in the gap: clear of both nodes
            _edge_label(ax, (x_a + x_b) / 2, cy + 0.14, "Yes", va="bottom")
            geom[("out", node)] = (cy, OUT_H / 2, OUT_W / 2)
        else:
            n, text = steps[node]
            label = _fit(f"{n}. {_condense(text)}", 30, 3)
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

    # Key lists only the shapes actually drawn (straight-through procedures have
    # no diamond, so advertising one would misread the diagram).
    has_dec = any(_is_dec(node) for node in spine)
    handles = [mpatches.Patch(facecolor=viz.PRIMARY, edgecolor=viz.INK, lw=0.8,
                              label="Process step")]
    if has_dec:
        handles += [
            mpatches.Patch(facecolor=viz.ACCENT, edgecolor=viz.INK, lw=0.8,
                           label="Decision point"),
            mpatches.Patch(facecolor=viz.BAD, edgecolor=viz.INK, lw=0.8,
                           label="Out-of-spec action"),
        ]
    handles += [
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
    ax.set_title(f"{sop.sop_id}  —  {sop.title}\n"
                 f"Auto-generated flowchart from '{sect}' ({len(steps)} numbered steps)",
                 fontsize=12, fontweight="bold")
    return viz.save(fig, path)


def _mermaid(sop, head, steps) -> str:
    sect = _section_label(head)
    lines = ["flowchart TD",
             f'    START(["START: {_mermaid_clean(sop.title)}"])']
    prev = "START"
    for n, text in steps:
        nid = f"S{n}"
        parts = _decision_parts(text)
        if parts:
            cond, action = parts
            did = f"D{n}"
            lines.append(f'    {did}{{"{_mermaid_clean(cond[:1].upper() + cond[1:])}?"}}')
            lines.append(f'    O{n}["{_mermaid_clean(action[:1].upper() + action[1:])}"]')
            lines.append(f"    {prev} --> {did}")
            lines.append(f"    {did} -- Yes --> O{n}")
            prev = did  # 'No' branch carries the main flow forward
            lines.append(f"    O{n} --> ENDN")
        else:
            lines.append(f'    {nid}["{n}. {_mermaid_clean(text)}"]')
            lines.append(f"    {prev} --> {nid}")
            prev = nid
    lines.append(f'    ENDN(["END: {_mermaid_clean(sect.lower())} complete"])')
    lines.append(f"    {prev} -- No --> ENDN" if prev.startswith("D") else f"    {prev} --> ENDN")
    return "\n".join(lines) + "\n"


def _step_table(steps) -> list[dict]:
    return [{"step": n, "type": "decision" if _decision_parts(t) else "process",
             "text": _condense(t, 90)} for n, t in steps]


# ---------------------------------------------------------------------------
# Per-SOP assessment.
# ---------------------------------------------------------------------------
def _assess(sop, sops_dir: Path) -> dict:
    """Attempt a flowchart for one SOP. Never raises — a bad parse or render is
    downgraded to a warn/n-a entry so the corpus sweep always completes."""
    try:
        head, steps = _best_procedure(sop)
    except Exception as exc:  # defensive: a malformed body must not abort the sweep
        return {"summary": {"steps": 0, "decisions": 0, "pages_replaced_est": 0},
                "findings": [f"Procedure parse failed ({type(exc).__name__}: {exc})."],
                "artifacts": [], "status": "n/a"}

    sect = _section_label(head) if head else "—"
    if len(steps) < MIN_STEPS:
        why = (f"only {len(steps)} numbered step(s) could be parsed"
               if steps else
               "the document is written as narrative prose and bullet lists under topic "
               "headings, with no numbered step sequence")
        return {
            "summary": {"steps": len(steps), "decisions": 0, "pages_replaced_est": 0,
                        "procedure_section": "—"},
            "findings": [f"No step-wise procedure to convert — {why}; a flowchart would "
                         f"have to be invented rather than derived from the text."],
            "artifacts": [],
            "table": [],
            "status": "n/a",
        }

    decisions = [(n, t) for n, t in steps if _decision_parts(t)]
    pages = _pages_replaced(steps, decisions)
    artifacts, problems = [], []
    try:
        artifacts.append(_rel(_render(sop, head, steps, sops_dir / f"{sop.sop_id}.png")))
    except Exception as exc:
        problems.append(f"PNG render failed ({type(exc).__name__}: {exc})")
    try:
        mmd = sops_dir / f"{sop.sop_id}.mmd"
        mmd.write_text(_mermaid(sop, head, steps), encoding="utf-8")
        artifacts.append(_rel(mmd))
    except Exception as exc:
        problems.append(f"Mermaid export failed ({type(exc).__name__}: {exc})")

    if decisions:
        n0, t0 = decisions[0]
        cond = _decision_parts(t0)[0]
        dec_line = (f"{len(decisions)} decision point(s) drawn as amber diamond(s) with "
                    f"Yes/No branches — first at step {n0} (“{cond}?”).")
    else:
        dec_line = ("No conditional branches detected — the procedure is a straight-through "
                    "sequence, so the flowchart is a single spine.")
    findings = [
        f"Converted the '{sect}' section — {len(steps)} numbered text steps rendered as "
        f"one top-down flowchart plus portable Mermaid source.",
        dec_line,
        f"Estimated ~{pages} page(s) of dense procedure text replaced by a single visual "
        f"aid (assumes ~4 steps per printed page).",
    ]
    findings += [f"Partial output: {p}." for p in problems]

    return {
        "summary": {"steps": len(steps), "decisions": len(decisions),
                    "pages_replaced_est": pages, "procedure_section": sect},
        "findings": findings,
        "artifacts": artifacts,
        "table": _step_table(steps),
        "status": "pass" if len(artifacts) == 2 else "warn",
    }


def _coverage_chart(corpus: Corpus, per_sop: dict, path: Path) -> str:
    """Corpus rollup: how much of each department converts to a visual aid."""
    depts = sorted({s.department for s in corpus.english()})
    conv = [sum(1 for s in corpus.english()
                if s.department == d and per_sop[s.sop_id]["status"] != "n/a") for d in depts]
    na = [sum(1 for s in corpus.english()
              if s.department == d and per_sop[s.sop_id]["status"] == "n/a") for d in depts]

    fig, ax = viz.new_fig(9.0, 4.4)
    ax.bar(depts, conv, color=viz.PRIMARY, label="Flowchart generated", zorder=3)
    ax.bar(depts, na, bottom=conv, color=viz.MUTED, label="No numbered procedure (n/a)",
           zorder=3)
    for i, (c, n) in enumerate(zip(conv, na)):
        if c:
            ax.text(i, c / 2, str(c), ha="center", va="center", color="white",
                    fontsize=9, fontweight="bold", zorder=4)
        if n:
            ax.text(i, c + n / 2, str(n), ha="center", va="center", color="white",
                    fontsize=9, fontweight="bold", zorder=4)
    ax.set_xlabel("Department")
    ax.set_ylabel("EN SOPs")
    ax.set_title("Visual-aid coverage by department\n"
                 "SOPs whose numbered procedure converts to a flowchart")
    ax.legend(loc="upper right", frameon=False)
    ax.grid(axis="x", visible=False)
    viz.finish(ax)
    return viz.save(fig, path)


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------
def run(corpus: Corpus, outdir: Path) -> dict:
    outdir = Path(outdir)
    sops_dir = outdir / "sops"
    sops_dir.mkdir(parents=True, exist_ok=True)

    # -- corpus flagship (unchanged behaviour) -----------------------------
    sop, head, steps = _select_target(corpus)
    decisions = [(n, t) for n, t in steps if _decision_parts(t)]
    png = _render(sop, head, steps, outdir / "flowchart.png")
    mmd_path = outdir / "flowchart.mmd"
    mmd_path.write_text(_mermaid(sop, head, steps), encoding="utf-8")
    pages = _pages_replaced(steps, decisions)
    dec_desc = (f"step {decisions[0][0]} (“If {_decision_parts(decisions[0][1])[0]}…”)"
                if decisions else "none")

    # -- per-SOP sweep: every EN SOP, deterministic id order ---------------
    per_sop = {s.sop_id: _assess(s, sops_dir)
               for s in sorted(corpus.english(), key=lambda s: s.sop_id)}
    converted = [k for k, v in per_sop.items() if v["status"] != "n/a"]
    not_conv = [k for k, v in per_sop.items() if v["status"] == "n/a"]
    total_pages = sum(v["summary"]["pages_replaced_est"] for v in per_sop.values())
    total_dec = sum(v["summary"]["decisions"] for v in per_sop.values())
    cov_png = _coverage_chart(corpus, per_sop, outdir / "coverage.png")

    return {
        "module": "m10_visual_aids",
        "title": "AI-Generated Visual Aids",
        "slide": 24,
        "scope": "per_sop",
        "summary": {
            "sop_id": sop.sop_id,
            "steps": len(steps),
            "decisions": len(decisions),
            "pages_replaced_est": pages,
            "sops_assessed": len(per_sop),
            "flowcharts_generated": len(converted),
            "no_numbered_procedure": len(not_conv),
            "corpus_pages_replaced_est": total_pages,
        },
        "key_findings": [
            f"Converted {sop.sop_id} '{_section_label(head)}' "
            f"— {len(steps)} numbered text steps rendered as one top-down flowchart.",
            f"Detected {len(decisions)} decision point ({dec_desc}); drawn as an amber "
            f"diamond with Yes/No branches to an out-of-spec action.",
            f"Corpus sweep: {len(converted)}/{len(per_sop)} EN SOPs have a parseable "
            f"numbered procedure and now carry their own flowchart + Mermaid source; "
            f"{len(not_conv)} are prose/bullet documents with no step sequence to draw.",
            f"Across the corpus {total_dec} decision point(s) were recovered and ~"
            f"{total_pages} page(s) of procedure text replaced by visual aids.",
            "Dual output: matplotlib PNG plus portable Mermaid 'flowchart TD' source "
            "for direct embedding in a QMS or wiki.",
            "Flagship chosen corpus-wide and deterministically: the numbered procedure "
            "pairing an explicit 'If …, …' branch with the most steps.",
        ],
        "artifacts": [_rel(png), _rel(mmd_path), _rel(cov_png)],
        "table": _step_table(steps),
        "table_columns": ["step", "type", "text"],
        "per_sop": per_sop,
    }
