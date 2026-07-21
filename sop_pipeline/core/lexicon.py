"""Shared lexicons and style definitions used across pipeline modules.

Centralizing these here keeps every module's judgment consistent: the same list
of ambiguous terms drives readability flags, scorecard clarity, and the rewriter.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Ambiguity — vague, non-actionable words that undermine SOP clarity.
# These are the words an auditor circles: they don't tell the operator what to do.
# ---------------------------------------------------------------------------

AMBIGUOUS_TERMS: list[str] = [
    "appropriate", "appropriately", "adequate", "adequately", "sufficient",
    "sufficiently", "as necessary", "as needed", "if needed", "if necessary",
    "as required", "as appropriate", "periodically", "regularly", "routinely",
    "when required", "where applicable", "reasonable", "acceptable", "properly",
    "suitable", "appropriate manner", "in a timely manner", "as soon as possible",
    "asap", "etc", "and/or", "some", "several", "various", "approximately",
    "about", "roughly", "generally", "typically", "normally", "usually",
    "may be", "should be considered", "clean thoroughly", "as directed",
]

# Spanish equivalents for multi-language checks.
AMBIGUOUS_TERMS_ES: list[str] = [
    "apropiado", "adecuado", "suficiente", "según sea necesario", "si es necesario",
    "periódicamente", "regularmente", "cuando sea necesario", "cuando corresponda",
    "razonable", "aceptable", "correctamente", "adecuadamente", "aproximadamente",
]


def _term_pattern(terms: list[str]) -> re.Pattern:
    parts = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    return re.compile(r"(?<![\w-])(" + "|".join(parts) + r")(?![\w-])", re.IGNORECASE)


AMBIGUITY_RE = _term_pattern(AMBIGUOUS_TERMS)
AMBIGUITY_ES_RE = _term_pattern(AMBIGUOUS_TERMS_ES)


def find_ambiguous_terms(text: str, spanish: bool = False) -> list[str]:
    rx = AMBIGUITY_ES_RE if spanish else AMBIGUITY_RE
    return [m.group(1).lower() for m in rx.finditer(text)]


# ---------------------------------------------------------------------------
# Passive voice — approximate detector: a "to be" verb followed (within a few
# tokens) by a past participle. Good enough to score relative passivity.
# ---------------------------------------------------------------------------

_BE_FORMS = r"(?:is|are|was|were|be|been being|been|being|shall be|must be|will be|has been|have been|had been)"
PASSIVE_RE = re.compile(
    r"\b" + _BE_FORMS + r"\b(?:\s+\w+){0,2}?\s+\b\w+(?:ed|en|wn|ne|ung| built|made|done|set|put|kept|held|sent|shown|taken|given|written|drawn|known|worn|torn)\b",
    re.IGNORECASE,
)

# Common irregular past participles the -ed rule misses.
_IRREGULAR_PP = {
    "made", "done", "set", "put", "kept", "held", "sent", "shown", "taken",
    "given", "written", "drawn", "known", "worn", "torn", "built", "found",
    "left", "read", "run", "begun", "chosen", "frozen", "driven",
}


def count_passive(text: str) -> int:
    return len(PASSIVE_RE.findall(text))


# ---------------------------------------------------------------------------
# Weak / non-directive sentence openers vs. strong imperative verbs.
# House style is verb-first imperative ("Record the value", "Verify the seal").
# ---------------------------------------------------------------------------

STRONG_IMPERATIVES: set[str] = {
    "record", "verify", "confirm", "measure", "inspect", "check", "remove",
    "install", "open", "close", "start", "stop", "wait", "wipe", "spray",
    "don", "doff", "label", "reconcile", "document", "sign", "date", "adjust",
    "set", "press", "select", "enter", "review", "collect", "transfer", "load",
    "unload", "sanitize", "disinfect", "clean", "prepare", "calibrate", "ensure",
    "notify", "discard", "store", "seal", "connect", "disconnect", "attach",
    "weigh", "dispense", "mix", "filter", "incubate", "read", "count", "add",
    "monitor", "log", "affix", "scan", "reject", "quarantine", "release",
}

# Nominalizations — abstract noun forms that bury the action ("performance of
# verification" instead of "verify"). Detected by suffix.
NOMINALIZATION_SUFFIXES = ("tion", "sion", "ment", "ance", "ence", "ility", "ization", "isation")

WEAK_OPENERS = (
    "it is", "there is", "there are", "the operator", "personnel", "the following",
    "in order to", "it should", "it shall", "responsibility for", "the purpose of",
)


def sentence_starts_with_verb(sentence: str) -> bool:
    """True if the first meaningful token is a strong imperative verb."""
    tokens = re.findall(r"[A-Za-z']+", sentence)
    if not tokens:
        return False
    # Skip a leading step number already stripped; look at first alpha token.
    first = tokens[0].lower()
    return first in STRONG_IMPERATIVES


def count_nominalizations(text: str) -> int:
    words = re.findall(r"[A-Za-z]{6,}", text.lower())
    return sum(1 for w in words if w.endswith(NOMINALIZATION_SUFFIXES))


# ---------------------------------------------------------------------------
# Style profiles — how each department writes. m11_style detects the *observed*
# profile of each SOP and reports deviation from the house standard.
#
# Each profile declares detectable signals:
#   heading_style : "markdown" | "allcaps" | "numbered_plain" | "roman" | "bulleted"
#   modal         : preferred obligation verb ("must" | "shall" | "should" | "will")
#   step_format   : how steps are introduced
# ---------------------------------------------------------------------------

HOUSE_STYLE = "env_doc_standard"

STYLE_PROFILES: dict[str, dict] = {
    "env_doc_standard": {
        "label": "House Standard (ENV/DOC)",
        "heading_style": "markdown",
        "modal": "must",
        "step_format": "numbered_verb_first",
        "description": "Markdown '##' headings, numbered verb-first steps, obligation word 'must'.",
    },
    "cln_caps_shall": {
        "label": "Cleaning (ALL-CAPS / shall)",
        "heading_style": "allcaps",
        "modal": "shall",
        "step_format": "numbered_passive",
        "description": "ALL-CAPS section headers, obligation word 'shall', frequent passive voice.",
    },
    "eqp_step_should": {
        "label": "Equipment (Step N: / should)",
        "heading_style": "numbered_plain",
        "modal": "should",
        "step_format": "step_colon",
        "description": "'Step N:' formatting, obligation word 'should', mixed voice.",
    },
    "qc_roman_nominal": {
        "label": "QC Lab (Roman numerals / nominal)",
        "heading_style": "roman",
        "modal": "must",
        "step_format": "nominal",
        "description": "Roman-numeral sections, nominalized academic prose.",
    },
    "mfg_future_operator": {
        "label": "Manufacturing (future tense / 'the operator will')",
        "heading_style": "numbered_plain",
        "modal": "will",
        "step_format": "future_operator",
        "description": "'The operator will...' future-tense narration.",
    },
    "pkg_bullet_responsible": {
        "label": "Packaging (bulleted / 'responsible for')",
        "heading_style": "bulleted",
        "modal": "responsible for",
        "step_format": "bulleted",
        "description": "Bulleted lists, 'X is responsible for ensuring...' constructions.",
    },
    "whs_minimal": {
        "label": "Warehouse (minimal headings)",
        "heading_style": "numbered_plain",
        "modal": "should",
        "step_format": "sparse",
        "description": "Sparse headings, short sentences, minimal structure.",
    },
}


def modal_counts(text: str) -> dict[str, int]:
    """Count obligation words to help infer a style profile's 'modal'."""
    t = text.lower()
    return {
        "must": len(re.findall(r"\bmust\b", t)),
        "shall": len(re.findall(r"\bshall\b", t)),
        "should": len(re.findall(r"\bshould\b", t)),
        "will": len(re.findall(r"\bwill\b", t)),
        "responsible for": len(re.findall(r"\bresponsible for\b", t)),
    }


def detect_heading_style(headings: list[str]) -> str:
    """Infer heading style from a list of raw section heading strings."""
    if not headings:
        return "none"
    allcaps = sum(1 for h in headings if h.strip() == h.strip().upper() and sum(c.isalpha() for c in h) >= 4)
    roman = sum(1 for h in headings if re.match(r"^\(?[IVXLC]+[\).\s]", h.strip()))
    stepcolon = sum(1 for h in headings if re.match(r"^step\s+\d+\s*:", h.strip(), re.IGNORECASE))
    n = len(headings)
    if stepcolon >= n * 0.4:
        return "numbered_plain"
    if roman >= n * 0.4:
        return "roman"
    if allcaps >= n * 0.5:
        return "allcaps"
    return "markdown"
