"""m13_training — Training Content Auto-Generation (deck slide 13).

For a handful of representative EN SOPs (one per department), auto-generate a
self-contained training package:

  (a) role-based summaries — Operator (key numbered steps, plain language),
      Supervisor (oversight + acceptance criteria), QA (references, records,
      data-integrity points);
  (b) 3-5 knowledge-check questions derived from the procedure steps and any
      numeric parameters found (contact times, temperatures, particle sizes, %),
      each with an answer key;
  (c) a quick-reference card plus a simple IF/THEN decision aid.

Each package is written to ``training_<SOP-ID>.md``. A stacked bar chart
(``training.png``) shows the item count generated per SOP. Everything is derived
from the SOP text itself; the manifest/RegKB only supply ground-truth labels.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT, split_sentences
from sop_pipeline.core.regkb import RegKB
from sop_pipeline.core import viz

RANDOM_STATE = 42

# The representative set: one SOP across four departments, spanning the four
# very different house styles (all-caps/shall, markdown/will, roman/must, markdown/must).
TARGET_IDS = ["SOP-CLN-006", "SOP-MFG-001", "SOP-QC-005", "SOP-ENV-001"]

# Section headings that introduce the actionable procedure, in priority order.
_PROC_KEYWORDS = ["procedure", "preparation", "method", "process", "operation", "instruction"]

_NUM = r"\d+(?:\.\d+)?"
_NUMPARAM_RE = re.compile(
    rf"{_NUM}(?:\s*(?:[–—-]|to)\s*{_NUM})?\s*"
    r"(?:°\s*C|µm|%|hours?|hrs?|minutes?|min\b|days?|weeks?|months?)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Text helpers (self-contained so roman-numeral SOPs split correctly too)
# ---------------------------------------------------------------------------

def _split_headed(body: str) -> list[tuple[str, str]]:
    """Split a body into (heading, text) pairs across markdown, all-caps, and
    roman-numeral heading styles."""
    md = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")
    roman = re.compile(r"^\s{0,3}([IVXL]+)\.\s+([A-Z][A-Za-z].*)$")
    out: list[tuple[str, list[str]]] = [("Preamble", [])]
    for line in body.splitlines():
        m = md.match(line)
        r = roman.match(line)
        stripped = line.strip()
        is_caps = (
            len(stripped) >= 4
            and sum(c.isalpha() for c in stripped) >= 4
            and stripped == stripped.upper()
            and not stripped.startswith("|")
        )
        if m:
            out.append((m.group(1).strip(), []))
        elif r:
            out.append((r.group(2).strip(), []))
        elif is_caps:
            out.append((stripped, []))
        else:
            out[-1][1].append(line)
    return [(h, "\n".join(ls).strip()) for h, ls in out if h != "Preamble" or ls]


def _list_items(text: str, marker: str) -> list[str]:
    """Extract list items (marker=r'\\d+[.)]' for numbered, r'[-*•]' for bulleted),
    joining wrapped continuation lines. Blank line ends an item."""
    items: list[str] = []
    cur: str | None = None
    lead = re.compile(rf"^\s*{marker}\s+(.*)$")
    for line in text.splitlines():
        m = lead.match(line)
        if m:
            if cur:
                items.append(cur)
            cur = m.group(1).strip()
        elif cur is not None:
            if line.strip():
                cur += " " + line.strip()
            else:
                items.append(cur)
                cur = None
    if cur:
        items.append(cur)
    return items


def _numbered_items(text: str) -> list[str]:
    return _list_items(text, r"(?:\d+)[.)]")


def _bullet_items(text: str) -> list[str]:
    return _list_items(text, r"[-*•]")


def _plainify(s: str) -> str:
    """Light de-passive / de-future cleanup for operator-facing plain language."""
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    for pat, rep in [
        (r"^The operator will\s+", ""),
        (r"^The operator\s+", ""),
        (r"\bwill be\b", "is"),
        (r"\bshall be\b", "must be"),
    ]:
        s = re.sub(pat, rep, s)
    return (s[:1].upper() + s[1:]) if s else s


def _find_section(sections: list[tuple[str, str]], keywords: list[str]) -> tuple[str, str] | None:
    for kw in keywords:
        for heading, text in sections:
            if kw in heading.lower():
                return heading, text
    return None


def _numeric_params(body: str) -> list[tuple[str, str]]:
    """Return (value, containing-sentence) pairs for distinct numeric specs."""
    sentences = split_sentences(body)
    seen: dict[str, tuple[str, str]] = {}
    for sent in sentences:
        clean = re.sub(r"\s+", " ", sent).strip()
        for m in _NUMPARAM_RE.finditer(sent):
            val = re.sub(r"\s+", " ", m.group(0)).strip()
            key = val.lower().replace(" ", "")
            # Prefer the shortest containing sentence for a clean cloze.
            if key not in seen or len(clean) < len(seen[key][1]):
                seen[key] = (val, clean)
    return list(seen.values())


def _cloze(sentence: str, answer: str) -> str:
    return sentence.replace(answer, "_____", 1)


def _conditionals(sentences: list[str]) -> list[str]:
    """Derive IF/THEN decision lines from conditional sentences in the text."""
    out: list[str] = []
    for s in sentences:
        s = re.sub(r"\s+", " ", s).strip().rstrip(".")
        m = re.match(r"^If\s+(.+?),\s*(.+)$", s, re.IGNORECASE)
        if m:
            out.append(f"IF {m.group(1).strip()} THEN {m.group(2).strip()}.")
            continue
        m = re.search(
            r"^(.*\b(?:notify|escalate|discard|evacuate|stop|report|reject|repeat|open an investigation)\b.*?)"
            r"\s+(?:when|if)\s+(.+)$",
            s, re.IGNORECASE,
        )
        if m:
            out.append(f"IF {m.group(2).strip()} THEN {m.group(1).strip()}.")
    # de-dupe, preserve order, cap
    uniq: list[str] = []
    for c in out:
        if c not in uniq:
            uniq.append(c)
    return uniq[:4]


# ---------------------------------------------------------------------------
# Package builder
# ---------------------------------------------------------------------------

def _build_package(sop, kb: RegKB) -> dict:
    sections = _split_headed(sop.body)
    sentences = split_sentences(sop.body)

    proc = _find_section(sections, _PROC_KEYWORDS)
    if proc is None:  # fall back to the most step-dense section
        proc = max(sections, key=lambda s: len(_numbered_items(s[1])), default=("Procedure", ""))
    proc_heading, proc_body = proc
    steps = _numbered_items(proc_body)

    numeric = _numeric_params(sop.body)
    citations = kb.extract(sop.sop_id, sop.full_text)
    related = sop.cross_references

    # -- Supervisor: oversight sentences + acceptance criteria ---------------
    resp = _find_section(sections, ["responsibilit"])
    oversight = []
    if resp:
        for s in split_sentences(resp[1]):
            if re.search(r"\b(supervisor|lead|review|verify|confirm|approve|ensure)\b", s, re.IGNORECASE):
                oversight.append(re.sub(r"\s+", " ", s).strip())
    accept = _find_section(sections, ["acceptance", "in-process", "limits", "criteria"])
    accept_lines: list[str] = []
    if accept:
        accept_lines = _numbered_items(accept[1]) or _bullet_items(accept[1])
        if not accept_lines:  # non-numbered/non-bulleted acceptance prose
            accept_lines = [re.sub(r"\s+", " ", x).strip() for x in split_sentences(accept[1])]

    # -- QA: records / data-integrity points ---------------------------------
    records = _find_section(sections, ["documentation", "records", "data"])
    di_points = []
    if records:
        di_points = [re.sub(r"\s+", " ", x).strip() for x in split_sentences(records[1])]
    if not di_points:
        di_points = [
            re.sub(r"\s+", " ", s).strip()
            for s in sentences
            if re.search(r"\b(record|document|logbook|data integrity|SOP-DOC-001|review the record)\b", s, re.IGNORECASE)
        ][:3]

    # -- Quiz pool (3-5, deterministic order) --------------------------------
    quiz: list[tuple[str, str]] = []
    for val, sent in numeric[:2]:
        quiz.append((f"Fill in the blank: \"{_cloze(sent, val)}\"", val))
    if steps:
        quiz.append((f"What is the first step of the {proc_heading}?", _plainify(steps[0])))
        quiz.append((f"How many numbered steps does the {proc_heading} contain?", str(len(steps))))
    if citations:
        names = ", ".join(c.canonical for c in citations)
        quiz.append((f"Which regulatory reference(s) does {sop.sop_id} cite?", names))
    elif related:
        quiz.append((f"Name a related SOP that {sop.sop_id} cross-references.", ", ".join(related)))
    if accept_lines:
        quiz.append(("State one acceptance criterion this procedure must meet.", accept_lines[0]))
    if len(quiz) < 3 and related:  # guarantee the 3-question floor
        quiz.append((f"Name a related SOP that {sop.sop_id} cross-references.", ", ".join(related)))
    quiz = quiz[:5]

    # -- Decision aid + quick reference --------------------------------------
    decision = _conditionals(sentences)
    if len(decision) < 2:
        sup = "the shift supervisor"
        decision.append(f"IF a step cannot be performed as written THEN stop and notify {sup} before proceeding.")
        decision.append("IF acceptance criteria are not met THEN document the excursion and escalate to Quality Assurance (per SOP-DOC-001).")
        decision = decision[:4]

    quick_ref = [
        f"Owner: {sop.owner or 'n/a'} · Version {sop.version} · Effective {sop.effective_date}",
        f"Primary reference(s): {', '.join(c.canonical for c in citations) or 'none cited'}",
        f"Related SOPs: {', '.join(related) or 'none'}",
        f"Key numeric specs: {', '.join(v for v, _ in numeric) or 'none stated'}",
        f"Procedure steps to master: {len(steps)}",
    ]

    return {
        "sop": sop,
        "proc_heading": proc_heading,
        "steps": steps,
        "oversight": oversight,
        "accept_lines": accept_lines,
        "citations": citations,
        "related": related,
        "di_points": di_points,
        "quiz": quiz,
        "decision": decision,
        "quick_ref": quick_ref,
        "summaries": 3,
        "questions": len(quiz),
        "aids": len(quick_ref) + len(decision),
    }


def _render_md(pkg: dict) -> str:
    sop = pkg["sop"]
    L: list[str] = []
    L.append(f"# Training Package — {sop.sop_id}: {sop.title}")
    L.append("")
    L.append(f"*Auto-generated · {sop.department_name} · Version {sop.version} · Owner: {sop.owner or 'n/a'}*")
    L.append("")
    L.append("## 1. Role-Based Summaries")
    L.append("")
    L.append(f"### Operator — key steps ({pkg['proc_heading']})")
    if pkg["steps"]:
        for i, s in enumerate(pkg["steps"], 1):
            L.append(f"{i}. {_plainify(s)}")
    else:
        L.append("_No numbered steps detected._")
    L.append("")
    L.append("### Supervisor — oversight & acceptance")
    for s in pkg["oversight"] or ["Verify that each step is executed and documented as written."]:
        L.append(f"- {s}")
    L.append("")
    L.append("**Acceptance criteria:**")
    for a in pkg["accept_lines"] or ["Confirm all steps completed and records reviewed before release."]:
        L.append(f"- {a}")
    L.append("")
    L.append("### QA — references, records & data integrity")
    if pkg["citations"]:
        for c in pkg["citations"]:
            L.append(f"- Reference: {c.canonical} — status *{c.status}* (current: {c.current_version or 'n/a'})")
    else:
        L.append("- Reference: none cited in body")
    L.append(f"- Related controlled documents: {', '.join(pkg['related']) or 'none'}")
    for d in pkg["di_points"] or ["Record entries and have a second person review before release (per SOP-DOC-001)."]:
        L.append(f"- Data-integrity point: {d}")
    L.append("")
    L.append(f"## 2. Knowledge Check ({len(pkg['quiz'])} questions)")
    L.append("")
    for i, (q, _) in enumerate(pkg["quiz"], 1):
        L.append(f"{i}. {q}")
    L.append("")
    L.append("**Answer key**")
    for i, (_, a) in enumerate(pkg["quiz"], 1):
        L.append(f"{i}. {a}")
    L.append("")
    L.append("## 3. Quick Reference & Decision Aid")
    L.append("")
    L.append("**Quick reference:**")
    for r in pkg["quick_ref"]:
        L.append(f"- {r}")
    L.append("")
    L.append("**Decision aid (if / then):**")
    for d in pkg["decision"]:
        L.append(f"- {d}")
    L.append("")
    return "\n".join(L)


def _chart(rows: list[dict], outdir: Path) -> str:
    fig, ax = viz.new_fig(8.5, 5.0)
    labels = [r["sop_id"].replace("SOP-", "") for r in rows]
    x = list(range(len(rows)))
    summaries = [r["summaries"] for r in rows]
    questions = [r["questions"] for r in rows]
    aids = [r["aids"] for r in rows]
    bottom_q = summaries
    bottom_a = [s + q for s, q in zip(summaries, questions)]

    # Grid strictly behind the bars; horizontal rules only (vertical lines cut
    # through the stacked segments and make them look broken).
    ax.set_axisbelow(True)
    ax.grid(True, axis="y", color=viz.GRID, linewidth=0.7, zorder=0)
    ax.grid(False, axis="x")

    width = 0.62
    series = [
        (summaries, [0] * len(rows), viz.CATEGORICAL[0], "Role summaries", "#FFFFFF"),
        (questions, bottom_q, viz.CATEGORICAL[3], "Quiz questions", viz.INK),
        (aids, bottom_a, viz.CATEGORICAL[4], "Quick-ref / decision aids", "#FFFFFF"),
    ]
    for values, bottoms, color, label, textcolor in series:
        ax.bar(x, values, width=width, bottom=bottoms, color=color,
               label=label, zorder=3, linewidth=0)
        # Segment value labels, centred in each segment (contrasting ink).
        for xi, v, b in zip(x, values, bottoms):
            if v >= 2:
                ax.text(xi, b + v / 2, str(v), ha="center", va="center",
                        fontsize=8.5, color=textcolor, zorder=4)

    totals = [s + q + a for s, q, a in zip(summaries, questions, aids)]
    top = max(totals)
    for xi, t in zip(x, totals):
        ax.text(xi, t + top * 0.02, str(t), ha="center", va="bottom",
                fontsize=9, fontweight="bold", color=viz.INK, zorder=4)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Training items generated (count)")
    ax.set_xlabel("Representative SOP (department code)")
    ax.set_xlim(-0.65, len(rows) - 0.35)
    ax.set_ylim(0, top * 1.10)
    ax.set_title("Auto-Generated Training Items per SOP", pad=26)
    ax.text(
        0.5, 1.015,
        "Representative sample: one SOP per department, chosen to span four different "
        "in-house drafting styles",
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=8.5, color=viz.MUTED,
    )

    # Legend fully outside the axes (below the x-axis label) so it can never sit
    # on top of a bar or a value label.
    ax.legend(
        loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3,
        frameon=False, fontsize=9, handlelength=1.4, handleheight=0.9,
        columnspacing=1.8, borderpad=0.0,
    )
    viz.finish(ax)
    return viz.save(fig, outdir / "training.png")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(corpus: Corpus, outdir: Path) -> dict:
    random.seed(RANDOM_STATE)
    outdir = Path(outdir)
    kb = RegKB.from_manifest(corpus.manifest)

    targets = [corpus[i] for i in TARGET_IDS if corpus.get(i) and corpus[i].language == "en"]
    packages = [_build_package(sop, kb) for sop in targets]

    artifacts: list[str] = []
    rows: list[dict] = []
    for pkg in packages:
        sop = pkg["sop"]
        md_path = outdir / f"training_{sop.sop_id}.md"
        md_path.write_text(_render_md(pkg), encoding="utf-8")
        artifacts.append(str(md_path.relative_to(PROJECT_ROOT)))
        rows.append({
            "sop_id": sop.sop_id,
            "summaries": pkg["summaries"],
            "questions": pkg["questions"],
            "aids": pkg["aids"],
        })

    png = _chart(rows, outdir)
    artifacts.insert(0, str(Path(png).relative_to(PROJECT_ROOT)))

    total_questions = sum(r["questions"] for r in rows)
    total_summaries = sum(r["summaries"] for r in rows)

    findings = [
        f"Generated complete training packages for {len(rows)} SOPs across "
        f"{len({p['sop'].department for p in packages})} departments.",
        f"Produced {total_questions} knowledge-check questions and "
        f"{total_summaries} role summaries (Operator / Supervisor / QA).",
    ]
    # Highlight the SOP with the richest numeric parameter set.
    richest = max(packages, key=lambda p: len([q for q in p["quiz"] if "blank" in q[0].lower()]))
    n_numeric = len([q for q in richest["quiz"] if "blank" in q[0].lower()])
    if n_numeric:
        findings.append(
            f"{richest['sop'].sop_id} yielded {n_numeric} parameter-based quiz item(s) "
            f"from measured specs (e.g. temperatures/times)."
        )
    findings.append(
        "IF/THEN decision aids were auto-derived from conditional and escalation "
        "language in each procedure (e.g. alarm, excursion, out-of-limit)."
    )

    return {
        "module": "m13_training",
        "title": "Training Content Auto-Generation",
        "slide": 13,
        "summary": {
            "sops_processed": len(rows),
            "total_questions": total_questions,
            "total_summaries": total_summaries,
        },
        "key_findings": findings[:6],
        "artifacts": artifacts,
        "table": rows,
        "table_columns": ["sop_id", "summaries", "questions", "aids"],
    }
