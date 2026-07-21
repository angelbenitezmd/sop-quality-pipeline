# SOP Authoring Guide (for corpus generation)

You are writing realistic mock SOPs for **Meridian Pharmaceuticals — Building 4**, a sterile
injectable fill-finish site (vials + pre-filled syringes). Content is fictional but must read
like genuine pharma GMP procedures. Each file is one SOP at `data/sops/<SOP-ID>.md`.

**Read `data/corpus_manifest.json` first** — it is the spec. Your assigned SOPs each have an
entry with: title, version, dates, owner, `style_profile`, `cross_refs` (SOP IDs you MUST cite
in the body), `reg_refs` (regulatory citations you MUST include, with the exact `as_written`
string), `seeded_defects` (defects you MUST inject), and `notes` (specific guidance).

**Read the two exemplars** to match format exactly:
- `data/sops/SOP-DOC-001.md` — house style (`env_doc_standard`): `##` markdown headings,
  numbered verb-first imperative steps, obligation word "must". Clean, readable (~Grade 9).
- `data/sops/SOP-CLN-003.md` — cleaning style (`cln_caps_shall`): ALL-CAPS headings, "shall",
  heavy passive voice, long run-on sentences, ambiguous terms. Deliberately hard to read.

## Frontmatter (required, exactly these keys)

```yaml
---
sop_id: SOP-XXX-000
title: <from manifest>
department: <full department name>
department_code: XXX
site: Meridian Pharmaceuticals — Building 4
version: "<from manifest, quoted>"
effective_date: <YYYY-MM-DD from manifest>
next_review: <YYYY-MM-DD from manifest>
owner: <from manifest>
language: en            # or 'es' for -ES variants; add: parent: SOP-XXX-000
status: Effective
style_profile: <from manifest>
---
```

## Body

Typical sections: Purpose, Scope, Responsibilities, Materials/Equipment, Procedure (numbered
steps), Acceptance Criteria / In-Process Controls, Related Documents, References, Revision
History. Vary section names by department. **Cite every `cross_refs` SOP ID verbatim** (e.g.
`SOP-DOC-001`) in prose or a Related Documents section, and include every `reg_refs.as_written`
string verbatim in a References section or inline. Length: simple SOPs ~250-450 words; complex
~450-800 words; very_complex ~700-1100 words.

## Style profiles (write the body to MATCH the assigned profile)

| profile | headings | obligation | voice / phrasing |
|---|---|---|---|
| `env_doc_standard` (ENV, DOC) | `## 1. Title` markdown | **must** | verb-first imperative, active, short sentences |
| `cln_caps_shall` (CLN) | `ALL CAPS` | **shall** | passive ("shall be performed"), long run-ons |
| `eqp_step_should` (EQP) | `Step 1:`, `Step 2:` plus short headers | **should** | mixed; "Step N:" procedure format |
| `qc_roman_nominal` (QC) | Roman numerals `I.`, `II.`, `III.` | **must** | nominalized academic prose ("performance of verification of...") |
| `mfg_future_operator` (MFG) | `## 1. Title` markdown | **will** | future tense narration ("The operator will...") |
| `pkg_bullet_responsible` (PKG) | short markdown headers | **responsible for** | bulleted lists, "X is responsible for ensuring..." |
| `whs_minimal` (WHS) | sparse/minimal headers | **should** | short sentences, minimal structure |

## Seeded defects — what each tag means (INJECT the ones listed for your SOP)

- `ambiguity_heavy` — use vague terms liberally: "appropriate", "adequate", "as necessary",
  "periodically", "if needed", "sufficient", "as required", "suitable", "in a timely manner".
- `passive_voice` — write steps in passive ("The surface shall be wiped", "Samples are collected").
- `long_sentences` / `very_long_sentences` — 40-80+ word run-on sentences with multiple clauses.
- `nominalization` — bury verbs in nouns: "perform verification of", "conduct an assessment of",
  "provide documentation of", "ensure the completion of the calibration of".
- `outdated_reg` — write the regulatory citation using the OUTDATED designation given in
  `reg_refs.as_written` (e.g. "EU GMP Annex 15 (2001 revision)", "ICH Q2(R1)", "ISO 14644-1:1999",
  "ICH Q9", "GAMP 5 (1st Ed)", "EU GMP Annex 1 (2008 revision)"). Do NOT "fix" it — the audit
  module must catch it.
- `broken_reference` — cite the non-existent SOP ID given in `cross_refs` (SOP-CLN-099 or
  SOP-VAL-001) as if it were a real related document. The dependency module must flag it.
- `near_duplicate` — see below.
- `orphan` — cite NO other SOP IDs at all and keep `cross_refs` empty (already empty in manifest).
- `overdue_review` — no body action needed; the past `next_review` date in frontmatter is the signal.
- `cycle_member` — just cite the `cross_refs` given; the cycle emerges from the graph.
- ES variant defects (`ml_*`) — see below.

## Near-duplicate groups (CRITICAL — one agent owns each group)

Members must be **~90% textually identical**, differing only in the room/line/unit identifier
and a few parameters. Write the FIRST member fully, then produce the others by copying the whole
body and substituting the identifier throughout. Groups:
- Room cleaning: `SOP-CLN-003` (already written — READ IT), `SOP-CLN-004` (Cleanroom B /
  Inspection Suite), `SOP-CLN-005` (Cleanroom C / Gowning & Airlock). Make 004 and 005
  near-copies of 003 with the room name/suite swapped and one or two parameter tweaks.
- Autoclave: `SOP-EQP-002` (Autoclave A), `SOP-EQP-003` (Autoclave B) — near-identical, unit ID swapped.
- Filling line: `SOP-MFG-002` (Line 1 / vial), `SOP-MFG-003` (Line 2 / syringe) — near-identical.
- Labeling: `SOP-PKG-002` (vial secondary packaging), `SOP-PKG-003` (syringe) — near-identical.

## Spanish variants (`-ES`)

Write in Spanish, mirroring the EN parent's structure, with `language: es` and `parent:` set.
- `SOP-CLN-001-ES`: parent `SOP-CLN-001`. **Same section count** as parent, BUT: state IPA
  concentration as **60%** (parent says 70% — a real content discrepancy), and use **decimal
  commas** throughout (`0,5 minutos`, `5,0 minutos`) where the EN parent uses decimal points.
- `SOP-MFG-001-ES`: parent `SOP-MFG-001`. **OMIT the Safety Warnings section** that the EN
  parent contains (so it has one fewer section — a section-count mismatch and a missing critical
  warning). Otherwise mirror the parent.

Write clean, valid Markdown. No placeholder text (no "xxx", "TODO", "[insert]", "lorem ipsum").
```
