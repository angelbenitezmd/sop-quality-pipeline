"""m06_rewriter — LLM-Assisted SOP Rewriting (deck slide 20).

Rewrites EVERY English SOP with a RULE-BASED rewrite engine and reports
before/after metrics per document (``per_sop``), on top of the corpus-level
flagship view: the worst-quality complex SOP (a normalized blend of reading
grade, ambiguous-term density and passive voice — deterministically
SOP-CLN-007) still gets the headline chart and full before/after markdown.

The rewrite engine:

  * splits run-on sentences at conjunctions / semicolons,
  * converts passive "shall/must be <verb>ed" into verb-first imperatives,
  * replaces ambiguous lexicon terms with bracketed measurable placeholders,
  * strips easy nominalizations and reduced-relative filler,
  * enforces verb-first numbered steps.

An Anthropic API call is offered as an optional path guarded by
``ANTHROPIC_API_KEY`` but the rule-based engine is what actually runs here
(there is no key in this environment). It is consulted ONCE, for the flagship
rewrite only — never 40 times in a loop. Before/after readability, page-count,
ambiguity and passive metrics are computed for every SOP and charted for the
flagship.
"""

from __future__ import annotations

import csv
import os
import re
import statistics
import warnings
from pathlib import Path

import textstat

from sop_pipeline.core import lexicon, viz
from sop_pipeline.core.corpus import Corpus, PROJECT_ROOT, split_sentences

# ---------------------------------------------------------------------------
# Rewrite rule tables
# ---------------------------------------------------------------------------

# Only participles the regular "-ed" suffix heuristic in _to_imperative() gets
# wrong; everything else (performed, identified, applied, ...) falls through to it.
IMPERATIVE_MAP = {
    "transferred": "transfer", "handled": "handle", "preserved": "preserve",
    "utilized": "use", "compared": "compare", "considered": "consider",
    "completed": "complete", "prepared": "prepare", "undertaken": "undertake",
    "achieved": "achieve", "determined": "determine", "subjected": "process",
    "understood": "note", "deemed": "define", "permitted": "permit",
}

# What kind of measurable criterion each vague term needs. The hint is appended to
# the marker so the SME sees *what* to supply, while the original word is preserved
# so the sentence stays grammatical and the flag is traceable to the source wording.
_AMB_HINTS: dict[str, tuple[str, ...]] = {
    "criterion": ("appropriate", "reasonable", "acceptable", "suitable", "adequate",
                  "sufficient", "appropriate manner"),
    "method": ("appropriately", "properly", "adequately", "sufficiently", "as directed",
               "as appropriate"),
    "frequency": ("as necessary", "as needed", "as required", "periodically", "regularly",
                  "routinely"),
    "trigger condition": ("if needed", "if necessary", "when required", "where applicable"),
    "time limit": ("in a timely manner", "as soon as possible", "asap"),
    "tolerance": ("approximately", "about", "roughly"),
    "applicable cases": ("generally", "typically", "normally", "usually"),
}
# vague term -> the kind of criterion required
AMB_HINT_FOR = {t: hint for hint, terms in _AMB_HINTS.items() for t in terms}

# A term flagged for definition is an explicit open item, not unresolved ambiguity —
# metrics strip these spans before counting.
DEFINE_SPAN_RE = re.compile(r"\[DEFINE\s+[a-z ]+:[^\]]*\]", re.IGNORECASE)

# Nominalization "the <noun> of" -> gerund (keeps grammar, drops -tion suffix count).
NOMINAL_PATTERNS = {
    "collection": "collecting", "generation": "generating", "establishment": "establishing",
    "recovery": "recovering", "execution": "executing", "application": "applying",
    "preparation": "preparing", "injection": "injecting", "determination": "determining",
    "documentation": "documenting", "maintenance": "maintaining", "completion": "completing",
    "calculation": "calculating", "verification": "verifying", "performance": "performing",
    "provision": "providing", "interpretation": "interpreting", "use": "using",
}

# Wordy filler -> concise equivalent (applied in order, longest first).
FILLER = [
    (r"in a manner that is intended to be ", ""), (r"it shall be further understood that ", ""),
    (r"it shall be understood that ", ""), (r"in accordance with", "per"),
    (r"in order that", "so that"), (r"in order to", "to"), (r"for the purpose of", "to"),
    (r"with respect to", "for"), (r"in support of", "for"), (r"is deemed to be", "is"),
    (r"to the extent that is practicable", "as far as practicable"),
    (r"that is considered to be", ""),
]

# Clause-boundary connectors used to break run-on sentences.
_SPLIT_RE = re.compile(
    r";\s+"
    r"|\s+whereby\s+"
    r"|\s+so that\s+"
    r"|\s+such that\s+"
    r"|\s+given that\s+"
    r"|,?\s+and (?=(?:the|a|an|it)\b[^,.]{0,55}?\b(?:shall|must)\s+be\b)",
    re.IGNORECASE,
)

# Inline "it shall/must be <verb>ed that ..." -> "<imperative> that ..." (function sub).
_IT_INLINE = re.compile(r"\bit\s+(?:shall|must)(?:\s+have\s+been|\s+be)\s+([a-z]+)\s+that\b", re.I)
# "it is the responsibility of X that Y shall/must be Zed" -> "X Z(imp) Y".
_RESP = re.compile(
    r"\bit\s+is\s+the\s+responsibility\s+of\s+(?:the\s+)?(.+?)\s+that\s+(.+?)\s+"
    r"(?:shall|must)(?:\s+have\s+been|\s+be)\s+([a-z]+)\b", re.I
)
_SUBJ_PASSIVE = re.compile(
    r"^(?:the\s+|a\s+|an\s+|this\s+)?(.*?)\s+(?:shall|must)(?:\s+have\s+been|\s+be)\s+([a-z]+)\b", re.I
)
_LEAD_PART = re.compile(r"^(?:be\s+)?([a-z]+(?:ed|en))\s+(that\b|to\b|with\b|in\b|only\b|using\b|from\b)", re.I)
_AMB_SUB_RE = lexicon.AMBIGUITY_RE


# ---------------------------------------------------------------------------
# Core rewrite helpers
# ---------------------------------------------------------------------------

def _to_imperative(participle: str) -> str:
    p = participle.lower()
    if p in IMPERATIVE_MAP:
        return IMPERATIVE_MAP[p]
    if p.endswith("ied"):
        return p[:-3] + "y"
    if p.endswith("ed"):
        s = p[:-2]
        if len(s) > 2 and s[-1] == s[-2] and s[-1] not in "aeiou":
            s = s[:-1]
        if s.endswith(("at", "iz", "is", "ur", "os", "ov", "iv", "ac", "ic", "it", "er", "id")):
            s += "e"
        return s
    return p


def _replace_ambiguous(text: str) -> str:
    """Flag each vague term for SME definition, preserving the original wording.

    Produces e.g. "an [DEFINE criterion: appropriate] quantity" — grammatical in any
    position, traceable to the source word, and explicit about what must be supplied.
    """
    def _mark(m: re.Match) -> str:
        term = m.group(1)
        hint = AMB_HINT_FOR.get(term.lower(), "criterion")
        return f"[DEFINE {hint}: {term}]"

    return _AMB_SUB_RE.sub(_mark, text)


def _cleanup(text: str) -> str:
    """Nominalization, reduced-relative and filler simplifications + ambiguity."""
    for noun, ger in NOMINAL_PATTERNS.items():
        text = re.sub(rf"\bthe\s+{noun}\s+of\b", ger, text, flags=re.I)
    # Drop "that/which is|are|was|were|has been..." reduced relatives (also kills passives).
    text = re.sub(r"\b(?:that|which)\s+(?:is|are|was|were|has been|have been|had been)\s+", "", text, flags=re.I)
    for pat, rep in FILLER:
        text = re.sub(pat, rep, text, flags=re.I)
    # "it is the responsibility of X that Y shall be Zed" -> "X Z(imperative) Y".
    text = _RESP.sub(lambda m: f"{m.group(1)} {_to_imperative(m.group(3))} {m.group(2)}", text)
    # "it shall be confirmed that ..." -> "confirm that ..." (compound imperative).
    text = _IT_INLINE.sub(lambda m: f"{_to_imperative(m.group(1))} that", text)
    text = _replace_ambiguous(text)
    return re.sub(r"\s+", " ", text).strip()


def _to_active(clause: str) -> str:
    """Turn a passive clause into a verb-first imperative where possible."""
    c = clause.strip().rstrip(".").rstrip(",")
    if not c:
        return c
    lead = _LEAD_PART.match(c)  # bare participle left by a split, e.g. "be labeled with"
    subj_m = _SUBJ_PASSIVE.match(c)
    if lead:
        c = f"{_to_imperative(lead.group(1))} {c[lead.start(2):]}"
    elif subj_m and subj_m.group(1).strip() and len(subj_m.group(1).split()) <= 10:
        subj, verb, rest = subj_m.group(1).strip(), _to_imperative(subj_m.group(2)), c[subj_m.end():]
        if subj.lower() in ("it", "this"):
            art = subj = ""
        else:
            art = "" if re.match(r"(all|each|every|both|final)\b", subj, re.I) else "the "
        c = re.sub(r"\s{2,}", " ", f"{verb} {art}{subj}{rest}".strip())
    c = c[0].upper() + c[1:]
    return c + "."


def _rewrite_paragraph(text: str) -> str:
    out: list[str] = []
    for sent in split_sentences(_cleanup(text)):
        for clause in _SPLIT_RE.split(sent):
            clause = (clause or "").strip()
            if len(clause.split()) >= 3:
                out.append(_to_active(clause))
    return " ".join(out)


def _rewrite_document(body: str) -> str:
    """Rewrite the SOP body block-by-block, keeping headings and tables intact.

    Blocks are blank-line separated; wrapped lines within a block are re-joined so
    multi-line numbered steps and paragraphs stay whole.
    """
    blocks: list[str] = []
    step_no = 0
    for chunk in re.split(r"\n\s*\n", body):
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            continue
        if "|" in chunk:  # markdown table -> keep verbatim
            blocks.append(chunk.strip())
            continue
        joined = " ".join(lines)
        head = lines[0]
        if len(lines) == 1 and head == head.upper() and sum(c.isalpha() for c in head) >= 4:
            blocks.append("\n## " + head.title())
        elif re.match(r"^\d+\.\s", head):  # one or more contiguous numbered steps
            for step in re.split(r"\s+(?=\d+\.\s)", joined):
                step_no += 1
                blocks.append(f"{step_no}. " + _rewrite_paragraph(re.sub(r"^\d+\.\s*", "", step)))
        else:
            blocks.append(_rewrite_paragraph(joined))
    return "\n\n".join(b for b in blocks if b.strip())


# Override with ANTHROPIC_MODEL to run the rewrite on a different Claude model.
LLM_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-opus-4-8"

LLM_SYSTEM = (
    "You rewrite pharmaceutical GMP SOPs for clarity without changing their meaning. "
    "Rules: keep every regulatory citation, cross-reference (SOP-XXX-000), numeric "
    "parameter, and safety warning exactly as written — never drop or invent one. "
    "Convert steps to verb-first imperatives, split run-on sentences, and prefer active "
    "voice. Where the source is vague ('appropriate', 'as necessary'), mark it "
    "[DEFINE <what is needed>: <original word>] rather than inventing a specification. "
    "Return only the rewritten SOP body in Markdown."
)


def _maybe_llm_rewrite(text: str) -> str | None:
    """Optional real-API path. Returns None (falling back to the rule-based engine)
    when no key is configured, the SDK is missing, or the call fails.

    A failure is warned about rather than swallowed silently — an SOP rewrite that
    quietly changed engines would be untraceable in an audit.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:  # pragma: no cover - requires a live API key
        import anthropic
    except ImportError:
        warnings.warn(
            "ANTHROPIC_API_KEY is set but the 'anthropic' package is not installed "
            "(pip install anthropic). Falling back to the rule-based engine.",
            RuntimeWarning, stacklevel=2,
        )
        return None
    try:  # pragma: no cover - requires a live API key
        client = anthropic.Anthropic()
        # No temperature/top_p/top_k: those are rejected on Opus 4.7+.
        msg = client.messages.create(
            model=LLM_MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=LLM_SYSTEM,
            messages=[{"role": "user", "content": "Rewrite this SOP:\n\n" + text}],
        )
        if msg.stop_reason == "refusal":
            warnings.warn("Model declined the rewrite; using the rule-based engine.",
                          RuntimeWarning, stacklevel=2)
            return None
        if msg.stop_reason == "max_tokens":
            warnings.warn("Rewrite hit max_tokens and would be truncated; "
                          "using the rule-based engine.", RuntimeWarning, stacklevel=2)
            return None
        # Skip thinking blocks — only text blocks carry the rewritten SOP.
        out = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return out.strip() or None
    except Exception as exc:
        warnings.warn(f"Anthropic API rewrite failed ({type(exc).__name__}: {exc}). "
                      "Falling back to the rule-based engine.", RuntimeWarning, stacklevel=2)
        return None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

_EMPTY_METRICS = {"grade": 0.0, "pages": 0.0, "ambiguous": 0,
                  "flagged_for_definition": 0, "passive": 0, "words": 0}


def _metrics(text: str) -> dict:
    if not text.strip():  # textstat is undefined on empty input
        return dict(_EMPTY_METRICS)
    words = len(re.findall(r"[A-Za-z']+", text))
    # Terms already flagged for SME definition are tracked open items, not
    # unresolved ambiguity — exclude those spans from the ambiguity count.
    flagged = len(DEFINE_SPAN_RE.findall(text))
    unresolved = DEFINE_SPAN_RE.sub(" ", text)
    return {
        "grade": round(textstat.flesch_kincaid_grade(text), 1),
        "pages": round(words / 450.0, 2),
        "ambiguous": len(lexicon.find_ambiguous_terms(unresolved)),
        "flagged_for_definition": flagged,
        "passive": lexicon.count_passive(text),
        "words": words,
    }


def _pick_worst(corpus: Corpus):
    """Deterministic worst-quality pick: z-scored grade + ambiguity + passive."""
    rows = []
    for sop in corpus.english():
        t = sop.full_text
        rows.append((sop, textstat.flesch_kincaid_grade(t),
                     len(lexicon.find_ambiguous_terms(t)), lexicon.count_passive(t)))

    def z(vals):
        m, sd = statistics.mean(vals), statistics.pstdev(vals) or 1.0
        return [(v - m) / sd for v in vals]

    zg, za, zp = z([r[1] for r in rows]), z([r[2] for r in rows]), z([r[3] for r in rows])
    scored = sorted(zip(rows, (a + b + c for a, b, c in zip(zg, za, zp))), key=lambda x: -x[1])
    return scored[0][0][0]


# ---------------------------------------------------------------------------
# Per-SOP reporting
# ---------------------------------------------------------------------------

# One source of truth for the metric tables (flagship and per-SOP alike).
METRIC_LABELS = [("Reading grade (FK)", "grade"), ("Estimated pages", "pages"),
                 ("Ambiguous terms", "ambiguous"), ("Passive constructs", "passive")]

# A rewrite is only credited as material at this many reading grades or better.
MATERIAL_GRADE_DROP = 2.0
# Plain-language target ceiling: at or below this the SOP already reads acceptably.
GRADE_TARGET = 12.0


def _metric_table(before: dict, after: dict) -> list[dict]:
    return [{"metric": lab, "before": before[k], "after": after[k]} for lab, k in METRIC_LABELS]


def _metric_table_md(table: list[dict]) -> str:
    rows = "".join(
        f"| {r['metric']} | {r['before']} | {r['after']} | "
        f"{round(r['after'] - r['before'], 2):+} |\n" for r in table
    )
    return "| Metric | Before | After | Delta |\n| --- | ---: | ---: | ---: |\n" + rows


def _status_for(before: dict, after: dict) -> str:
    """pass = materially easier to read (or already at target); fail = no gain."""
    drop = before["grade"] - after["grade"]
    if drop >= MATERIAL_GRADE_DROP or before["grade"] <= GRADE_TARGET:
        return "pass"
    return "warn" if drop > 0 else "fail"


def _write_rewrite_md(sop, before: dict, after: dict, original: str, rewritten: str,
                      engine: str, path: Path) -> str:
    path.write_text(
        f"# SOP Rewrite — {sop.sop_id}\n\n"
        f"**{sop.title}**  \nEngine: `{engine}`  \n\n"
        + _metric_table_md(_metric_table(before, after)) +
        f"\nOpen items for the SME: **{after['flagged_for_definition']}** `[DEFINE ...]` markers.\n"
        "\n---\n\n## Original\n\n" + original.strip() +
        f"\n\n---\n\n## Rewritten ({engine})\n\n" + rewritten.strip() + "\n",
        encoding="utf-8",
    )
    return str(path.resolve().relative_to(PROJECT_ROOT))


def _per_sop_entry(sop, before: dict, after: dict, rel_md: str, is_flagship: bool) -> dict:
    """Assemble one document's assessment. Empty bodies are reported, not dropped."""
    if before["words"] == 0 or after["words"] == 0:
        return {
            "summary": {"grade_before": before["grade"], "grade_after": after["grade"],
                        "pages_before": before["pages"], "pages_after": after["pages"],
                        "ambiguous_before": before["ambiguous"], "ambiguous_after": after["ambiguous"],
                        "flagged_for_sme": after["flagged_for_definition"],
                        "passive_before": before["passive"], "passive_after": after["passive"]},
            "findings": [f"{sop.sop_id} has no rewritable prose body "
                         f"({before['words']} words parsed) — nothing to rewrite or measure."],
            "artifacts": [], "table": [], "status": "n/a",
        }

    drop = round(before["grade"] - after["grade"], 1)
    verdict = ("cut the reading grade materially" if drop >= MATERIAL_GRADE_DROP else
               "left the reading grade unchanged or worse" if drop <= 0 else
               "cut the reading grade only slightly")
    findings = [
        f"Rule-based rewrite {verdict}: FK grade {before['grade']} -> {after['grade']} "
        f"({-drop:+.1f}); estimated pages {before['pages']} -> {after['pages']}; "
        f"passive constructs {before['passive']} -> {after['passive']}.",
        f"{after['flagged_for_definition']} [DEFINE ...] open item(s) await an SME measurable "
        f"criterion; unresolved ambiguous terms {before['ambiguous']} -> {after['ambiguous']}.",
    ]
    if before["grade"] <= GRADE_TARGET:
        findings.append(f"Source already read at or below the Grade {GRADE_TARGET:.0f} target "
                        f"({before['grade']}), so the rewrite is a polish, not a remediation.")
    if is_flagship:
        findings.append("Flagship SOP for this module — see rewrite_metrics.png and "
                        "before_after.md for the charted corpus-level view.")
    return {
        "summary": {"grade_before": before["grade"], "grade_after": after["grade"],
                    "pages_before": before["pages"], "pages_after": after["pages"],
                    "ambiguous_before": before["ambiguous"], "ambiguous_after": after["ambiguous"],
                    "flagged_for_sme": after["flagged_for_definition"],
                    "passive_before": before["passive"], "passive_after": after["passive"]},
        "findings": findings,
        "artifacts": [rel_md],
        "table": _metric_table(before, after),
        "status": _status_for(before, after),
    }


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def _chart(before: dict, after: dict, sop_id: str, path: Path) -> str:
    import matplotlib.pyplot as plt

    viz.apply_style()
    keys = ["grade", "pages", "ambiguous", "passive"]
    labels = ["Reading grade\n(FK)", "Est. pages\n(words/450)", "Ambiguous\nterms", "Passive\nconstructs"]
    fig, axes = plt.subplots(1, 4, figsize=(11.0, 4.2))
    fig.suptitle(f"LLM-Assisted Rewrite — {sop_id}: before vs after (lower is better)",
                 fontsize=13, fontweight="bold", color=viz.INK)
    for ax, k, lab in zip(axes, keys, labels):
        vals = [before[k], after[k]]
        bars = ax.bar([0, 1], vals, width=0.62, color=[viz.BAD, viz.GOOD], zorder=3)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Before", "After"])
        ax.set_title(lab, fontsize=10)
        ax.set_ylim(0, max(vals) * 1.25 + 0.5)
        ax.grid(axis="x", visible=False)
        for b, v in zip(bars, vals):
            txt = f"{v:.2f}" if k == "pages" else (f"{v:.1f}" if k == "grade" else f"{int(v)}")
            ax.text(b.get_x() + b.get_width() / 2, v, txt, ha="center", va="bottom",
                    fontsize=9, fontweight="bold", color=viz.INK)
        viz.finish(ax)
    handles = [plt.Rectangle((0, 0), 1, 1, color=viz.BAD), plt.Rectangle((0, 0), 1, 1, color=viz.GOOD)]
    fig.legend(handles, ["Before (original)", "After (rewritten)"], loc="lower center",
               ncol=2, bbox_to_anchor=(0.5, -0.03))
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    return viz.save(fig, path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(corpus: Corpus, outdir: Path) -> dict:
    outdir = Path(outdir)
    sopdir = outdir / "sops"
    sopdir.mkdir(parents=True, exist_ok=True)
    rel = lambda p: str(Path(p).resolve().relative_to(PROJECT_ROOT))

    sop = _pick_worst(corpus)
    original = sop.body

    # Consulted ONCE, for the flagship only — never inside the 40-SOP loop.
    # Report the engine that actually produced the text, not merely whether a key
    # was present — a silent fallback must never be recorded as an LLM rewrite.
    llm_output = _maybe_llm_rewrite(original)
    if llm_output:
        rewritten, engine = llm_output, f"anthropic-api ({LLM_MODEL})"
    else:
        rewritten, engine = _rewrite_document(original), "rule-based"

    before, after = _metrics(original), _metrics(rewritten)
    png = _chart(before, after, sop.sop_id, outdir / "rewrite_metrics.png")

    table = _metric_table(before, after)
    md = outdir / "before_after.md"
    md.write_text(
        f"# LLM-Assisted SOP Rewrite — {sop.sop_id}\n\n"
        f"**{sop.title}**  \nEngine: `{engine}`  \n\n" + _metric_table_md(table) +
        "\n---\n\n## Original\n\n" + original.strip() +
        f"\n\n---\n\n## Rewritten ({engine})\n\n" + rewritten.strip() + "\n",
        encoding="utf-8",
    )

    # --- per-SOP sweep: every EN SOP, rule-based engine, stable id order --------
    per_sop: dict[str, dict] = {}
    csv_rows: list[dict] = []
    for doc in sorted(corpus.english(), key=lambda s: s.sop_id):
        src = doc.body
        out_text = _rewrite_document(src)
        b, a = _metrics(src), _metrics(out_text)
        rel_md = _write_rewrite_md(doc, b, a, src, out_text, "rule-based",
                                   sopdir / f"{doc.sop_id}.md")
        entry = _per_sop_entry(doc, b, a, rel_md, doc.sop_id == sop.sop_id)
        per_sop[doc.sop_id] = entry
        csv_rows.append({"sop_id": doc.sop_id, "status": entry["status"],
                         "grade_before": b["grade"], "grade_after": a["grade"],
                         "pages_before": b["pages"], "pages_after": a["pages"],
                         "ambiguous_before": b["ambiguous"], "ambiguous_after": a["ambiguous"],
                         "passive_before": b["passive"], "passive_after": a["passive"],
                         "flagged_for_sme": a["flagged_for_definition"]})

    csv_path = outdir / "rewrite_all_sops.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(csv_rows[0].keys()))
        w.writeheader()
        w.writerows(csv_rows)

    graded = [r for r in csv_rows if per_sop[r["sop_id"]]["status"] != "n/a"]
    n_pass = sum(1 for r in csv_rows if per_sop[r["sop_id"]]["status"] == "pass")
    mean_before = round(statistics.mean([r["grade_before"] for r in graded]), 1) if graded else 0.0
    mean_after = round(statistics.mean([r["grade_after"] for r in graded]), 1) if graded else 0.0
    total_flags = sum(r["flagged_for_sme"] for r in csv_rows)

    return {
        "module": "m06_rewriter",
        "title": "LLM-Assisted SOP Rewriting",
        "slide": 20,
        "scope": "per_sop",
        "summary": {
            "sop_id": sop.sop_id,
            "grade_before": before["grade"],
            "grade_after": after["grade"],
            "pages_before": before["pages"],
            "pages_after": after["pages"],
            "ambiguous_before": before["ambiguous"],
            "ambiguous_after": after["ambiguous"],
            "flagged_for_sme": after["flagged_for_definition"],
            "sops_rewritten": len(per_sop),
            "sops_passing": n_pass,
            "corpus_grade_before": mean_before,
            "corpus_grade_after": mean_after,
            "open_define_items": total_flags,
        },
        "key_findings": [
            f"Worst-quality complex SOP selected: {sop.sop_id} "
            f"(FK grade {before['grade']}, {before['ambiguous']} ambiguous terms, {before['passive']} passive).",
            f"Rule-based rewrite cut reading grade {before['grade']} -> {after['grade']} "
            f"by splitting run-ons and enforcing verb-first steps.",
            f"Unresolved ambiguous terms {before['ambiguous']} -> {after['ambiguous']}: each is now an explicit "
            f"[DEFINE ...] open item ({after['flagged_for_definition']} total) for the SME to assign a "
            "measurable criterion — flagged, not silently resolved.",
            f"Passive constructs {before['passive']} -> {after['passive']}; "
            f"estimated pages {before['pages']} -> {after['pages']}.",
            f"All {len(per_sop)} EN SOPs rewritten: mean FK grade {mean_before} -> {mean_after}, "
            f"{n_pass}/{len(per_sop)} pass, {total_flags} [DEFINE ...] open items raised corpus-wide.",
            f"Engine actually used: {engine}. The LLM path runs only when ANTHROPIC_API_KEY "
            "is set and the call succeeds; any failure falls back to rules and is reported "
            "as rule-based, never as an LLM rewrite.",
        ],
        "artifacts": [rel(png), rel(md), rel(csv_path)],
        "table": table,
        "table_columns": ["metric", "before", "after"],
        "per_sop": per_sop,
    }
