# How the pipeline works — explainable-AI method cards

This folder explains **exactly how every capability reaches its numbers**, in plain
language rather than code. It is written to be presented to reviewers, SMEs, and auditors:
each score decomposes into named, counted signals you can trace and re-run. Nothing here is
a trained or opaque model — the pipeline *suggests*, with its reasoning exposed, and a human
*decides*.

## Read this first

**[Foundations — the shared signals](methods/00_foundations.md).** The building blocks every
module reuses: ambiguous-term density, passive voice, nominalizations, verb-first steps,
reading grade, regulatory-citation currency, and style profiles. The per-module cards
reference these by name instead of re-deriving them.

## The method cards

Each card follows the same structure: *question it answers · source signal · how it works ·
**the scoring** (exact formulas and thresholds) · how to read the result · worked example ·
what it cannot see (limitations)*.

| # | Capability | Scope | Card |
|---|---|---|---|
| 1 | SOP Similarity Analysis | corpus | [m01_similarity](methods/m01_similarity.md) |
| 2 | Topic Clustering | corpus | [m02_topics](methods/m02_topics.md) |
| 3 | Readability & Complexity | per-SOP | [m03_readability](methods/m03_readability.md) |
| 4 | Cross-Reference Dependencies | corpus | [m04_dependencies](methods/m04_dependencies.md) |
| 5 | Regulatory Reference Audit | both | [m05_regaudit](methods/m05_regaudit.md) |
| 6 | LLM-Assisted Rewriting | per-SOP | [m06_rewriter](methods/m06_rewriter.md) |
| 7 | **Quality Scorecard** | per-SOP | [m07_scorecard](methods/m07_scorecard.md) |
| 8 | MinHash Near-Duplicate Detection | corpus | [m08_minhash](methods/m08_minhash.md) |
| 9 | Coverage Gap Analysis | corpus | [m09_coverage](methods/m09_coverage.md) |
| 10 | AI-Generated Visual Aids | per-SOP | [m10_visual_aids](methods/m10_visual_aids.md) |
| 11 | Style & Structure Standardization | per-SOP | [m11_style](methods/m11_style.md) |
| 12 | Multi-Language Harmonization | per-SOP | [m12_multilang](methods/m12_multilang.md) |
| 13 | Training Content Auto-Generation | per-SOP | [m13_training](methods/m13_training.md) |

## The scorecard in one glance

The quality scorecard (module 7) is the capability most often asked about, so here is its
shape up front — the full derivation with every constant is in its card.

Five dimensions, each scored **0–10**, all measured from the text:

| Dimension | What it rewards | Built from |
|---|---|---|
| **Clarity** | actionable, direct prose | low ambiguity + reading grade + low passive voice |
| **Completeness** | the expected document structure | how many of six standard sections are present |
| **Usability** | a floor operator can follow it | readability + numbered, verb-first steps |
| **Consistency** | internal uniformity | one heading style + one obligation word |
| **Defensibility** | it would survive an audit | current citations + reference/revision sections − overdue-review/broken-ref penalties |

The five combine into an **overall** score with a deliberate twist — a **weakest-link**
roll-up: `overall = 0.65 × average + 0.35 × the single weakest dimension`. A document is only
as defensible as its worst gap, so a serious hole in one dimension can't be averaged away by
strong scores elsewhere. Bands: **pass ≥ 8, review 6–8, action required < 6**.

That weakest-link choice is why a corpus can average a decent-looking plain mean yet still
report a low overall — and it is exactly the property an auditor cares about.

## Why this matters for the deployment

Every module is deterministic (fixed seeds; a fixed "today" of 1 Jul 2026 for overdue-review
checks), so re-running the same corpus reproduces the same numbers — a prerequisite for
anything an auditor might independently verify. And because each score traces back to counted
words, matched patterns, or a config table, you can always answer the auditor's real
question: *why did this document get this number?*
