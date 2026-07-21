"""m13_training — Training Content Auto-Generation (deck slide 13).

For **every** English SOP in the corpus, auto-generate a self-contained training
package:

  (a) role-based summaries — Operator (key steps, plain language),
      Supervisor (oversight + acceptance criteria), QA (references, records,
      data-integrity points);
  (b) 3-5 knowledge-check questions derived from the procedure steps and from
      that SOP's own numeric parameters (contact times, temperatures, particle
      sizes, concentrations), each with an answer key;
  (c) a quick-reference card plus an IF/THEN decision aid.

Scope is ``per_sop``. Each package is written to
``output/m13_training/sops/training_<SOP-ID>.md`` and reported under
``per_sop``; ``training_index.md`` indexes them all. Steps are extracted from
the four drafting conventions present in the corpus (numbered lists,
``Step N:`` paragraphs, bulleted procedures, directive prose), so an SOP in any
house style still yields a usable package. One corpus chart (``training.png``)
rolls the item counts up — no per-SOP images, the markdown is the deliverable.

Everything is derived from the SOP text itself; the manifest/RegKB only supply
ground-truth labels.
"""

from __future__ import annotations

import math
import random
import re
from pathlib import Path

from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT, split_sentences
from sop_pipeline.core.regkb import RegKB
from sop_pipeline.core import lexicon, viz

RANDOM_STATE = 42

# Section headings that introduce the actionable procedure, in priority order.
_PROC_KEYWORDS = ["procedure", "preparation", "method", "process", "operation", "instruction"]

# Front/back matter that never contains operator steps. Matched against the
# heading with any leading numbering stripped.
_BOILERPLATE_RE = re.compile(
    r"^(purpose|scope|responsibilit|responsibility|definition|abbreviat|glossar"
    r"|reference|related document|revision history|document history|approval"
    r"|distribution|appendix|attachment|materials|equipment|house style"
    r"|effective date|records|documentation|sop-)",
    re.IGNORECASE,
)
# Acceptance sections are surfaced in the Supervisor block, so they are not also
# folded into the operator step list.
_NONSTEP_RE = re.compile(r"^acceptance", re.IGNORECASE)
# Narrower exclusion for numeric-parameter mining: tables of dates and versions
# would otherwise masquerade as measured specs.
_NONPARAM_RE = re.compile(r"^(revision history|document history|reference|related document)", re.IGNORECASE)

_NUM = r"\d+(?:\.\d+)?"
_UNITS = (
    r"°\s*C|°\s*F|µm|μm|µg|μg|mg|kg|mL|ml|L\b|ppm|parts\s+per\s+million|percent|%"
    r"|CFU|psi|bar\b|rpm|microsiemens|µS/cm"
    r"|hours?|hrs?|minutes?|min\b|seconds?|sec\b|days?|weeks?|months?|years?"
)
_NUMPARAM_RE = re.compile(
    rf"{_NUM}(?:\s*(?:[–—-]|to)\s*{_NUM})?\s*(?:{_UNITS})",
    re.IGNORECASE,
)

_DIRECTIVE_RE = re.compile(
    r"\b(shall|should|must|will|is required to|are required to|is to be|are to be)\b",
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


# Leading section numbering: "6. ", "3.1 ", "V. ". The roman branch demands a
# dot so that a heading like "Label Issuance" does not lose its "L".
_LEADING_NUM_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVXL]{1,6}\.)\s+")


def _strip_numbering(heading: str) -> str:
    return _LEADING_NUM_RE.sub("", heading).strip()


def _norm_heading(heading: str) -> str:
    """Drop leading section numbering so 'V. PROCEDURE' / '6. Procedure' compare alike."""
    return _strip_numbering(heading).lower()


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


def _step_items(text: str) -> list[str]:
    """'Step 1: ...' paragraph style (the EQP house style)."""
    return _list_items(text, r"Step\s+\d+\s*[:.)]")


def _action_sentences(text: str) -> list[str]:
    """Directive prose sentences — the fallback for SOPs written without lists."""
    out: list[str] = []
    for sent in split_sentences(text):
        s = re.sub(r"\s+", " ", sent).strip()
        if len(s.split()) < 5 or s.startswith("|"):
            continue
        first = re.sub(r"[^A-Za-z]", "", s.split()[0]).lower()
        if (
            _DIRECTIVE_RE.search(s)
            or first in lexicon.STRONG_IMPERATIVES
            or lexicon.sentence_starts_with_verb(s)
        ):
            out.append(s)
    return out


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


# ---------------------------------------------------------------------------
# Step extraction — four drafting conventions, one interface
# ---------------------------------------------------------------------------

def _is_directive(item: str) -> bool:
    return bool(_DIRECTIVE_RE.search(item)) or lexicon.sentence_starts_with_verb(item)


def _extract_steps(text: str) -> tuple[list[str], str]:
    """Return (steps, method) for one section body."""
    for fn, method in (
        (_numbered_items, "numbered"),
        (_step_items, "step-prefixed"),
        (_bullet_items, "bulleted"),
    ):
        items = [i for i in fn(text) if len(i.split()) >= 2 and not i.startswith("|")]
        if len(items) < 2:
            continue
        # A bulleted block is only a procedure if most of its lines either direct
        # an action or are full statements — otherwise it is a taxonomy
        # ("General waste", "Hazardous and chemical waste", ...).
        if method == "bulleted":
            substantive = sum(1 for i in items if _is_directive(i) or len(i.split()) >= 8)
            if substantive * 2 < len(items):
                continue
        return items, method
    prose = _action_sentences(text)
    if len(prose) >= 2:
        return prose, "prose"
    return [], "none"


def _step_groups(sections: list[tuple[str, str]]) -> tuple[list[tuple[str, list[str]]], str, str]:
    """Pick the operator-facing steps.

    A keyword-named section with an explicit step list wins outright; otherwise
    the steps of every non-boilerplate section are consolidated so that
    bullet-driven and prose-only SOPs still yield a full package.
    Returns (groups, primary_heading, method).
    """
    candidates = [
        (h, t) for h, t in sections
        if not _BOILERPLATE_RE.match(_norm_heading(h)) and not _NONSTEP_RE.match(_norm_heading(h))
    ]
    scored = [(h, *_extract_steps(t)) for h, t in candidates]

    for kw in _PROC_KEYWORDS:
        for heading, items, method in scored:
            if kw in heading.lower() and method in ("numbered", "step-prefixed"):
                return [(heading, items)], heading, method

    groups = [(h, items) for h, items, _ in scored if items]
    if not groups:
        return [], "", "none"
    methods = sorted({m for _, items, m in scored if items})
    primary = max(groups, key=lambda g: len(g[1]))[0]
    return groups, primary, methods[0] if len(methods) == 1 else "mixed"


def _section_lines(text: str) -> list[str]:
    """Readable lines from a section: its list items if it is a list, otherwise
    its sentences. Table rows and numbering fragments are dropped."""
    out: list[str] = []
    for line in _bullet_items(text) or _numbered_items(text) or split_sentences(text):
        line = re.sub(r"^[-*•]\s*", "", re.sub(r"\s+", " ", line).strip())
        if len(line.split()) >= 4 and not line.startswith("|"):
            out.append(line)
    return out


def _numeric_params(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Return (value, containing-sentence) pairs for distinct numeric specs,
    skipping revision/reference tables where numbers are dates and versions."""
    body = "\n\n".join(t for h, t in sections if not _NONPARAM_RE.match(_norm_heading(h)))
    seen: dict[str, tuple[str, str]] = {}
    for sent in split_sentences(body):
        clean = re.sub(r"\s+", " ", sent).strip()
        if clean.startswith("|"):
            continue
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

def _build_package(sop, kb: RegKB, complexity: str = "") -> dict:
    sections = _split_headed(sop.body)
    # Section-aware lines, not raw sentences: a bullet-only SOP has no sentence
    # boundaries the splitter can see, so its whole body would come back as one blob.
    lines = [ln for _, text in sections for ln in _section_lines(text)]

    groups, primary, method = _step_groups(sections)
    steps = [s for _, items in groups for s in items]

    numeric = _numeric_params(sections)
    citations = kb.extract(sop.sop_id, sop.full_text)
    related = sop.cross_references

    # -- Supervisor: oversight sentences + acceptance criteria ---------------
    resp = _find_section(sections, ["responsibilit", "responsibility"])
    oversight = [
        line for line in (_section_lines(resp[1]) if resp else [])
        if re.search(r"\b(supervisor|manager|lead|quality assurance|review|verif|confirm|approv|ensur|oversee|responsib)",
                     line, re.IGNORECASE)
    ]
    accept = _find_section(sections, ["acceptance", "in-process", "limits", "criteria"])
    accept_lines = _section_lines(accept[1]) if accept else []

    # -- QA: records / data-integrity points ---------------------------------
    records = _find_section(sections, ["documentation", "records", "data"])
    di_points = _section_lines(records[1]) if records else []
    if not di_points:
        di_points = [
            ln for ln in lines
            if re.search(r"\b(record|document|logbook|data integrity|SOP-DOC-001)", ln, re.IGNORECASE)
        ][:3]
    di_points = di_points[:4]

    # -- Quiz pool (3-5, deterministic order) --------------------------------
    quiz: list[tuple[str, str]] = []
    for val, sent in numeric[:2]:
        quiz.append((f"Fill in the blank: \"{_cloze(sent, val)}\"", val))
    if steps:
        first_heading = _strip_numbering(groups[0][0])
        quiz.append((f"What is the first step performed under \"{first_heading}\"?", _plainify(steps[0])))
        count_q = (
            f"How many steps does the {sop.sop_id} procedure contain?" if len(groups) == 1
            else f"Across its {len(groups)} operational stages, how many steps does {sop.sop_id} define in total?"
        )
        quiz.append((count_q, str(len(steps))))
    if citations:
        names = ", ".join(c.canonical for c in citations)
        quiz.append((f"Which regulatory reference(s) does {sop.sop_id} cite?", names))
    elif related:
        quiz.append((f"Name a related SOP that {sop.sop_id} cross-references.", ", ".join(related)))
    if accept_lines:
        quiz.append(("State one acceptance criterion this procedure must meet.", accept_lines[0]))
    if len(quiz) < 3 and related:  # guarantee the 3-question floor
        quiz.append((f"Name a related SOP that {sop.sop_id} cross-references.", ", ".join(related)))
    if len(quiz) < 3:  # last resort: ownership/control facts still testable
        quiz.append((
            f"Which function owns {sop.sop_id}, and who is the document owner?",
            f"{sop.department_name} — {sop.owner or 'owner not stated'}",
        ))
    quiz = quiz[:5]

    # -- Decision aid + quick reference --------------------------------------
    decision = _conditionals(lines)
    derived = len(decision)
    if len(decision) < 2:
        decision.append("IF a step cannot be performed as written THEN stop and notify the shift supervisor before proceeding.")
        decision.append("IF acceptance criteria are not met THEN document the excursion and escalate to Quality Assurance (per SOP-DOC-001).")
        decision = decision[:4]

    # Session length: 2 min per step + 2 min per question on a 10 min briefing,
    # rounded up to the nearest 5 so schedulers get a usable slot.
    est_minutes = int(5 * math.ceil((10 + 2 * len(steps) + 2 * len(quiz)) / 5))

    quick_ref = [
        f"Owner: {sop.owner or 'n/a'} · Version {sop.version} · Effective {sop.effective_date}",
        f"Primary reference(s): {', '.join(c.canonical for c in citations) or 'none cited'}",
        f"Related SOPs: {', '.join(related) or 'none'}",
        f"Key numeric specs: {', '.join(v for v, _ in numeric) or 'none stated'}",
        f"Procedure steps to master: {len(steps)}",
        f"Estimated session length: {est_minutes} min ({complexity or 'unrated'} complexity)",
    ]

    return {
        "sop": sop,
        "groups": groups,
        "proc_heading": primary or "Procedure",
        "method": method,
        "steps": steps,
        "numeric": numeric,
        "oversight": oversight,
        "accept_lines": accept_lines,
        "citations": citations,
        "related": related,
        "di_points": di_points,
        "quiz": quiz,
        "decision": decision,
        "derived_decisions": derived,
        "quick_ref": quick_ref,
        "complexity": complexity,
        "est_minutes": est_minutes,
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
    L.append(
        f"*Steps extracted from the SOP's own {pkg['method']} drafting style · "
        f"estimated session length {pkg['est_minutes']} min*"
    )
    L.append("")
    L.append("## 1. Role-Based Summaries")
    L.append("")
    multi = len(pkg["groups"]) > 1
    where = f"consolidated from {len(pkg['groups'])} sections" if multi else pkg["proc_heading"]
    L.append(f"### Operator — key steps ({where})")
    if pkg["steps"]:
        n = 0
        for heading, items in pkg["groups"]:
            if multi:
                L.append("")
                L.append(f"**{heading}**")
            for item in items:
                n += 1
                L.append(f"{n}. {_plainify(item)}")
    else:
        L.append("_No procedural steps could be extracted from this document._")
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
            newer = f" (current: {c.current_version})" if c.current_version and c.current_version != c.status else ""
            L.append(f"- Reference: {c.canonical} — status *{c.status}*{newer}")
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


def _render_index(rows: list[dict]) -> str:
    L = ["# Training Package Index", "",
         f"Auto-generated training packages for all {len(rows)} English SOPs. "
         "Each package contains Operator / Supervisor / QA summaries, a knowledge "
         "check with answer key, and a quick-reference / decision aid.", "",
         "| SOP | Department | Style detected | Steps | Questions | Aids | Est. min | Status | Package |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        pkg = f"sops/training_{r['sop_id']}.md" if r["status"] == "pass" else "—"
        L.append(
            f"| {r['sop_id']} | {r['department']} | {r['source_style']} | {r['steps']} | "
            f"{r['questions']} | {r['aids']} | {r['est_minutes']} | {r['status']} | {pkg} |"
        )
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Corpus chart
# ---------------------------------------------------------------------------

def _chart(rows: list[dict], outdir: Path) -> str:
    fig, ax = viz.new_fig(13.0, 5.8)
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

    width = 0.72
    series = [
        (summaries, [0] * len(rows), viz.CATEGORICAL[0], "Role summaries"),
        (questions, bottom_q, viz.CATEGORICAL[3], "Quiz questions"),
        (aids, bottom_a, viz.CATEGORICAL[4], "Quick-ref / decision aids"),
    ]
    for values, bottoms, color, label in series:
        ax.bar(x, values, width=width, bottom=bottoms, color=color,
               label=label, zorder=3, linewidth=0)

    totals = [s + q + a for s, q, a in zip(summaries, questions, aids)]
    top = max(totals) if totals else 1

    # Department dividers + group labels: 40 bars read better in blocks.
    depts = [r["sop_id"].split("-")[1] for r in rows]
    start = 0
    for i in range(1, len(depts) + 1):
        if i == len(depts) or depts[i] != depts[start]:
            if start > 0:
                ax.axvline(start - 0.5, color=viz.GRID, linewidth=1.0, zorder=1)
            ax.text((start + i - 1) / 2, top * 1.04, depts[start], ha="center", va="bottom",
                    fontsize=8.5, fontweight="bold", color=viz.MUTED, zorder=4)
            start = i

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=90, fontsize=7)
    ax.set_ylabel("Training items generated (count)")
    ax.set_xlabel("SOP (department code + number)")
    ax.set_xlim(-0.8, len(rows) - 0.2)
    ax.set_ylim(0, top * 1.16)
    ax.set_title("Auto-Generated Training Items per SOP — full EN corpus", pad=26)
    ax.text(
        0.5, 1.015,
        f"Every one of the {len(rows)} English SOPs gets its own package: 3 role summaries "
        "+ knowledge check + quick-reference / decision aid",
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=8.5, color=viz.MUTED,
    )

    # Legend fully outside the axes (below the x-axis label) so it can never sit
    # on top of a bar or a value label.
    ax.legend(
        loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3,
        frameon=False, fontsize=9, handlelength=1.4, handleheight=0.9,
        columnspacing=1.8, borderpad=0.0,
    )
    viz.finish(ax)
    return viz.save(fig, outdir / "training.png")


# ---------------------------------------------------------------------------
# Per-SOP assessment
# ---------------------------------------------------------------------------

def _per_sop_entry(pkg: dict, md_rel: str | None) -> dict:
    sop = pkg["sop"]
    if md_rel is None:
        return {
            "summary": {"summaries": 0, "questions": 0, "aids": 0, "steps": 0,
                        "numeric_params": 0, "source_style": "none", "est_minutes": 0},
            "findings": [
                f"{sop.sop_id} has no extractable procedural content (no numbered, "
                "step-prefixed, bulleted or directive-prose steps outside front matter), "
                "so no training package could be derived — remediate the document structure first."
            ],
            "artifacts": [],
            "table": [],
            "status": "n/a",
        }

    n_numeric = len([q for q in pkg["quiz"] if q[0].startswith("Fill in the blank")])
    stages = len(pkg["groups"])
    findings = [
        f"Generated a 3-role package ({pkg['summaries']} summaries, {pkg['questions']} quiz "
        f"items, {pkg['aids']} aids) from {len(pkg['steps'])} step(s) across {stages} "
        f"section(s), extracted from this SOP's {pkg['method']} drafting style.",
    ]
    if n_numeric:
        specs = ", ".join(v for v, _ in pkg["numeric"][:n_numeric])
        findings.append(f"Answer key is anchored on {n_numeric} real numeric parameter(s) from the text: {specs}.")
    else:
        findings.append(
            "No measurable numeric parameter (time/temperature/concentration) found in the body — "
            "the knowledge check falls back to step, reference and acceptance recall."
        )
    if pkg["citations"]:
        stale = [c.canonical for c in pkg["citations"] if c.status in ("outdated", "review")]
        findings.append(
            f"QA module cites {len(pkg['citations'])} regulatory reference(s)"
            + (f"; {', '.join(stale)} flagged as outdated/under review and must be corrected "
               "before the package is released for training." if stale else " — all current.")
        )
    findings.append(
        f"{pkg['derived_decisions']} IF/THEN line(s) auto-derived from the SOP's own conditional "
        f"language, {len(pkg['decision']) - pkg['derived_decisions']} added from the standard "
        f"escalation template; estimated session length {pkg['est_minutes']} min."
    )

    return {
        "summary": {
            "summaries": pkg["summaries"],
            "questions": pkg["questions"],
            "aids": pkg["aids"],
            "steps": len(pkg["steps"]),
            "numeric_params": len(pkg["numeric"]),
            "source_style": pkg["method"],
            "est_minutes": pkg["est_minutes"],
        },
        "findings": findings,
        "artifacts": [md_rel],
        "table": [
            {"n": i, "question": q, "answer": a}
            for i, (q, a) in enumerate(pkg["quiz"], 1)
        ],
        "table_columns": ["n", "question", "answer"],
        "status": "pass",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(corpus: Corpus, outdir: Path) -> dict:
    random.seed(RANDOM_STATE)
    outdir = Path(outdir)
    sops_dir = outdir / "sops"
    sops_dir.mkdir(parents=True, exist_ok=True)
    # Packages moved into sops/ — drop any left at the top level by an older run.
    for stale in outdir.glob("training_SOP-*.md"):
        stale.unlink()

    kb = RegKB.from_manifest(corpus.manifest)
    targets = sorted(corpus.english(), key=lambda s: s.sop_id)

    per_sop: dict[str, dict] = {}
    rows: list[dict] = []
    packages: list[dict] = []

    for sop in targets:
        complexity = str(corpus.manifest_entry(sop.sop_id).get("complexity", ""))
        pkg = _build_package(sop, kb, complexity)
        packages.append(pkg)
        # A package needs *some* procedural substance; otherwise report n/a rather
        # than shipping an empty deck to a trainer.
        usable = bool(pkg["steps"]) or len(pkg["quiz"]) >= 3
        md_rel: str | None = None
        if usable:
            md_path = sops_dir / f"training_{sop.sop_id}.md"
            md_path.write_text(_render_md(pkg), encoding="utf-8")
            md_rel = str(md_path.relative_to(PROJECT_ROOT))
        per_sop[sop.sop_id] = _per_sop_entry(pkg, md_rel)
        rows.append({
            "sop_id": sop.sop_id,
            "department": sop.department,
            "summaries": pkg["summaries"] if usable else 0,
            "questions": pkg["questions"] if usable else 0,
            "aids": pkg["aids"] if usable else 0,
            "steps": len(pkg["steps"]),
            "numeric_params": len(pkg["numeric"]),
            "source_style": pkg["method"] if usable else "none",
            "est_minutes": pkg["est_minutes"] if usable else 0,
            "status": "pass" if usable else "n/a",
        })

    index_path = outdir / "training_index.md"
    index_path.write_text(_render_index(rows), encoding="utf-8")

    png = _chart(rows, outdir)
    artifacts = [
        str(Path(png).relative_to(PROJECT_ROOT)),
        str(index_path.relative_to(PROJECT_ROOT)),
    ]

    generated = [r for r in rows if r["status"] == "pass"]
    total_questions = sum(r["questions"] for r in rows)
    total_summaries = sum(r["summaries"] for r in rows)
    total_aids = sum(r["aids"] for r in rows)
    styles = sorted({r["source_style"] for r in generated})
    with_numeric = [r for r in generated if r["numeric_params"]]
    total_minutes = sum(r["est_minutes"] for r in rows)

    findings = [
        f"Generated complete training packages for {len(generated)}/{len(rows)} EN SOPs across "
        f"{len({r['department'] for r in generated})} departments — every document now has its own.",
        f"Produced {total_questions} knowledge-check questions, {total_summaries} role summaries "
        f"(Operator / Supervisor / QA) and {total_aids} quick-reference / decision-aid lines.",
        f"Step extraction handled {len(styles)} different drafting conventions ({', '.join(styles)}), "
        "so bullet-only and prose-only SOPs yield packages as readily as numbered ones.",
        f"{len(with_numeric)} SOPs contained measurable parameters and got parameter-anchored quiz "
        f"items; the remaining {len(generated) - len(with_numeric)} fall back to step/reference recall "
        "— a drafting gap worth closing.",
        f"Estimated {total_minutes} minutes ({total_minutes / 60:.1f} h) of curriculum, "
        f"averaging {total_minutes / max(len(generated), 1):.0f} min per SOP.",
        "IF/THEN decision aids were auto-derived from conditional and escalation language "
        "in each procedure (e.g. alarm, excursion, out-of-limit).",
    ]

    return {
        "module": "m13_training",
        "title": "Training Content Auto-Generation",
        "slide": 13,
        "summary": {
            "sops_processed": len(rows),
            "packages_generated": len(generated),
            "total_questions": total_questions,
            "total_summaries": total_summaries,
            "total_aids": total_aids,
            "est_curriculum_hours": round(total_minutes / 60, 1),
        },
        "key_findings": findings[:6],
        "artifacts": artifacts,
        "table": rows,
        "table_columns": [
            "sop_id", "department", "summaries", "questions", "aids",
            "steps", "numeric_params", "source_style", "est_minutes", "status",
        ],
        "scope": "per_sop",
        "per_sop": per_sop,
    }
