# 05 — Regulatory Reference Audit
**Question it answers:** For every English SOP, does each regulatory standard it cites point at the *current* revision, or at a superseded one an auditor would flag?
**Deck slide:** 19.
**Scope:** both — each citation is classified individually, the classifications roll up into a per-SOP scorecard (`per_sop`, one entry for every English SOP plus its own `sops/<id>.csv` extract), and those roll up again into the corpus-wide status counts and audit table on the deck.

---

## The source: what it reads

This module consumes exactly one foundation signal — **Signal 6, Regulatory citations & currency** — and nothing else. It does not use ambiguity, passive voice, readability, or style. For each SOP it reads the document's **full text** (title + body) and scans the prose for regulatory references.

The extraction and classification are delegated in full to the shared knowledge base `sop_pipeline/core/regkb.py` (`RegKB`). The "current version" ground truth is **not** hard-coded in the module; it is loaded from the site configuration table `regulatory_current_versions` in `config/site_config.json` via `RegKB.from_manifest(corpus.manifest)`. This is the deliberate design point from the foundations: the KB and the audit can never drift because they read the same table, and that table is **site configuration you maintain**.

Why a cited version number is a valid, defensible proxy for a compliance property: citing a superseded standard (e.g. the 2001 edition of EU GMP Annex 15 after the 2015 revision took effect) is a concrete, common, and objective audit finding. It is mechanical to check against a maintained register, which is exactly what makes it a good candidate for automation rather than relying on an SME to remember every revision. What it is *not* is a judgement about whether the SOP's content actually complies — only whether the *designation it cites* is the current one.

---

## How it works

The work happens in three layers.

**1. Extraction (per SOP, in `RegKB.extract`).** The KB holds an **ordered list of 23 citation patterns** (compiled `re` regular expressions, case-insensitive). It runs each pattern over the full text; for every match it produces a **canonical citation key** (e.g. `EU GMP Annex 1`, `ICH Q2(R2)`, `21 CFR 211.67`). The patterns cover 21 CFR parts, ICH (Q2/Q7/Q9/Q10), EU GMP Annex 1 and Annex 15, USP chapters (`<1058>`, `<797>`, `<71>`, `<85>`), ISO 14644-1 and 13408-1, PDA TR-60/TR-70, GAMP 5, and the ISPE Baseline Guide for CIP. Order matters and **the first pattern to match a given span wins** — this is why the specific `ICH Q2(R2)` and `ICH Q2(R1)` patterns are listed before the generic ones, and why the bare `ICH Q9` pattern carries a negative look-ahead `(?!\s*\(?R)` so it does not swallow `ICH Q9(R1)`.

**2. Version detection.** After a citation matches, the KB looks in a **30-character window immediately after the match** for a version designation, using a single "version-near" regex. That regex recognises: a bare four-digit year optionally followed by *revision/rev/edition/ed*; *rev/revision/edition* followed by a year; a colon-year like `:1999`; an ordinal edition like `2nd Ed` / `1st Ed`; and a parenthesised revision marker like `(R2)` / `R 1`. Some patterns instead capture the year *inside* the match (e.g. `ISO 14644-1:1999`), and there is a fallback that lifts a captured four-digit group when the window found nothing. The exact matched substring (citation + adjacent version text, whitespace-collapsed) is stored as **`as_written`** — this is what appears in the deck's "Reference Found" column so a reviewer sees the problem exactly as it reads in the SOP.

**3. Classification against the register (`RegKB._classify`).** The canonical key is looked up in the `regulatory_current_versions` table and assigned one of four statuses — **current / outdated / review / unknown** (see The scoring). If the same canonical citation appears more than once in one SOP, only the **most severe** occurrence is kept (deduplicated by canonical key).

The module (`m05_regaudit.py`) then does the roll-ups and rendering. `_collect` gathers every citation across all English SOPs into audit rows and sorts them most-severe-first. `_per_sop` groups rows by SOP and assigns each document a pass/warn/fail/n-a status with plain-language findings and its own CSV. `_plot` renders a two-panel PNG with **matplotlib** (a status-count bar chart and a horizontal "outdated by standard" breakdown); `_write_csv` writes the corpus audit table. No machine learning and no sampling are involved — the module notes the `random_state=42` requirement is satisfied vacuously because nothing here randomises.

---

## The scoring  (the critical section)

### Step A — the four per-citation statuses

Every extracted citation gets exactly one status. The rules, taken verbatim from `RegKB._classify` and `_outdated`:

| Status | How a citation earns it | Action string produced |
|---|---|---|
| **current** | The canonical key is in the register and no cited version matches one of that entry's `outdated_designations` (and the version text does not contain the word "review"). This is the default. | `None` |
| **outdated** | A cited version designation matches one of the entry's `outdated_designations` — matched by stripping all non-word characters from both sides and testing whether either string contains the other. | `Update reference to <current>` |
| **review** | Not outdated, but the version text literally contains the substring `review`. | `Review scope against current version` |
| **unknown** | The canonical key is **not** in the register at all (and is not one of the two supersession special-cases below). | `Verify citation manually` |

**Outdated-match detail:** the cited version text is lower-cased and stripped of non-word characters (so `:1999` becomes `1999`, `1st Ed` becomes `1sted`); the same stripping is applied to each configured `outdated_designation`; the citation is outdated if either normalised string contains the other. So `EU GMP Annex 15 (2001 revision)` (normalises to `2001revision`) matches the designation `2001` and is flagged outdated.

**Supersession special-cases (hard-coded in `_classify`).** Two ICH keys have no register entry of their own and instead redirect to their successor:
- `ICH Q2(R1)` → treated as **outdated**, superseded by `ICH Q2(R2)`; current version reported as `Q2(R2)`.
- `ICH Q9` → treated as **outdated**, superseded by `ICH Q9(R1)`; current version reported as `Q9(R1)`.
For these the reported `reference`/`canonical` becomes the *successor* key while `as_written` preserves the old text as found (e.g. `ICH Q2(R1)`).

### The register (`config/site_config.json → regulatory_current_versions`)

These are the exact `current` designations and `outdated_designations` the classifier tests against. Everything not listed with an outdated set is `"current": "current"` (all the 21 CFR sections, USP chapters, ICH Q7/Q10, ISO 13408-1, PDA TR-60/TR-70), meaning any version text is accepted:

| Canonical key | `current` | `outdated_designations` |
|---|---|---|
| EU GMP Annex 1 | `2022 revision` | `2008`, `2008 revision`, `2003` |
| EU GMP Annex 15 | `2015 revision` | `2001` |
| ICH Q2(R2) | `Q2(R2)` | `Q2(R1)`, `Q2(R1) 2005` |
| ICH Q9(R1) | `Q9(R1)` | `Q9`, `Q9 2005` |
| ISO 14644-1 | `2015` | `1999` |
| GAMP 5 | `2nd Ed (2022)` | `1st Ed`, `2008` |
| ISPE Baseline Guide: CIP | `2nd Ed (2020)` | *(none)* |

### Step B — per-SOP status (the `both`-scope roll-up)

`_per_sop` assigns each English SOP one status, evaluated in this **precedence order** (first match wins):

| Per-SOP status | Exact condition |
|---|---|
| **n/a** | The SOP has **no** citations at all (`sop_rows` is empty). |
| **fail** | At least one **outdated** citation (`counts["outdated"] > 0`). |
| **warn** | No outdated, but at least one **review** *or* **unknown** citation. |
| **pass** | Citations found and every one is **current**. |

This is a weakest-link roll-up: a single outdated citation fails the whole document regardless of how many current ones sit beside it. Each entry also records a `summary` count block (`citations_found`, `current`, `outdated`, `review`, `unknown`) and human-readable `findings`.

### Step C — corpus roll-up and ordering

- The corpus `summary` reports five numbers: `sops_scanned`, `references_extracted` (total rows), and counts of `current`, `outdated`, `review`. (Note: `unknown` is counted per-SOP but is **not** included in this top-level summary block.)
- The public audit table and CSV are sorted by the tuple **(table-severity, sop_id, canonical)**, where table-severity is `outdated = 0, review = 1, unknown = 2, current = 3` — so problems lead the table.
- Beware two *different* severity orderings live in this pipeline: the table-sort order above (lower number = shown first), and a separate dedup order inside `RegKB` used only to keep the worst duplicate (`current = 0, unknown = 1, review = 2, outdated = 3`, higher = more severe). They rank the middle categories differently; both are correct for their own purpose.
- Panel 1 of the PNG charts only three bars in the fixed order **current, review, outdated** (green / amber / red). `unknown` is not drawn.

---

## How to read the result

- **A citation is `current`** → the version designation it cites matches the site register; no action.
- **`outdated`** → the SOP cites a superseded revision; the `action` names the exact target (e.g. "Update reference to 2015 revision"). This is a real, ready-to-write finding.
- **`review`** → the text flagged itself for review; a human should check scope against the current version.
- **`unknown`** → the reference is not in your register at all; verify manually and, if it is a real standard you care about, add it to `regulatory_current_versions`.

**A per-SOP `fail`** means at least one outdated citation — hand that document's `sops/<id>.csv` to its owner; every row and its remediation are already spelled out. **`pass`** means citations exist and all are current. **`n/a`** means the SOP cites no standards this KB recognises — not necessarily good or bad, just nothing to audit.

**Artifacts:** `regaudit.csv` is the full corpus audit table (SOP | reference | status | current_version | action), problems first. `regaudit.png` is the deck visual — left panel the current/review/outdated tally, right panel a horizontal bar of which standards are outdated and how often. Each `sops/<id>.csv` is a single document's extract for its owner.

---

## Worked example

**SOP-QC-001** (a QC analytical-testing procedure) — real numbers from `summary.json`: `citations_found = 2`, `current = 1`, `outdated = 1`, `review = 0`, `unknown = 0`, per-SOP `status = "fail"`.

The scan finds two references in its text: `ICH Q2(R1)` and `21 CFR 211.165`.

1. **`ICH Q2(R1)`.** The ordered patterns reach the `ICH Q2(R1)` pattern and it matches, yielding canonical key `ICH Q2(R1)`. That key is **not** in the register — but it is one of the two supersession special-cases, so `_classify` redirects it through `_outdated` to the successor `ICH Q2(R2)`. Result: `reference = ICH Q2(R2)`, `as_written = ICH Q2(R1)`, `status = outdated`, `current_version = Q2(R2)`, `action = "Update reference to Q2(R2)"`.
2. **`21 CFR 211.165`.** Matches the `21 CFR (\d{3}\.\d{1,3})` pattern → canonical `21 CFR 211.165`, which is in the register as `"current"` with no outdated set. Status = **current**, action `None`.

Roll-up (Step B): the SOP has one outdated citation, so the `fail` condition (`counts["outdated"] > 0`) fires first → **status = fail**, with the finding *"Outdated citation \"ICH Q2(R1)\" — update to Q2(R2)"* and *"1 of 2 citations in SOP-QC-001 are current; 1 requires action."* In the corpus audit table this SOP's outdated row is sorted ahead of all current rows (table-severity 0 vs 3).

**The standard (non-supersession) path, for contrast — SOP-CLN-003.** One citation, `EU GMP Annex 15 (2001 revision)`. The `EU GMP Annex 15` pattern matches; the 30-character window after it captures `2001 revision` as the version text. `EU GMP Annex 15` *is* in the register (`current = 2015 revision`, outdated set `[2001]`). Normalising `2001 revision` → `2001revision`, which contains the designation `2001` → **outdated**, `action = "Update reference to 2015 revision"`, per-SOP **fail** (`0 of 1 citations current`). This is one of the two Annex-15 findings behind the corpus headline.

**Corpus roll-up.** Across `sops_scanned = 40` SOPs, `references_extracted = 51`: `current = 44`, `outdated = 7`, `review = 0`. The per-SOP rollup is **33 pass, 7 fail, 0 warn, 0 n/a** — the seven fails being exactly the seven outdated citations (EU GMP Annex 15 in SOP-CLN-003 and SOP-CLN-007, ISO 14644-1:1999 in SOP-ENV-002, GAMP 5 1st Ed in SOP-EQP-005, EU GMP Annex 1 2008 in SOP-MFG-005, ICH Q2(R1) in SOP-QC-001, ICH Q9 in SOP-QC-003).

---

## What it cannot see (limitations)

- **It knows only what the register knows.** A standard revised *after* your `regulatory_current_versions` table was last edited will read as current. The table is site configuration you must maintain; the audit's completeness is entirely bounded by it. Two distinct blind spots: a standard outside the 23 extraction patterns is **missed entirely** (never even extracted), while a citation the patterns *do* extract but whose canonical key is absent from the register is flagged **`unknown`** (`Verify citation manually`). The generic `21 CFR <section>` pattern makes the latter real — it will match any `211.xxx` section, so a CFR section not listed in the table would surface as `unknown` rather than being validated. This demo corpus happens to contain zero `unknown` citations, but that is a property of the data, not a guarantee.
- **Version, not content.** It checks the *designation cited*, never whether the procedure's text actually complies with that standard. An SOP can cite the current revision and still contradict it.
- **The 30-character window can grab the wrong version.** Because version detection looks at raw text just after a citation, a version designation belonging to a *neighbouring* citation can be absorbed into the wrong `as_written`. Real example: in SOP-CLN-007 the current `PDA TR-70` row carries `as_written = "PDA TR-70 and EU GMP Annex 15 (2001 rev"` — the window reached into the next citation's date. Here it is harmless (PDA TR-70 has no `outdated_designations`, so it stays correctly `current`), but the displayed reference string is misleading, and a citation with an outdated set could in principle be mis-scored by a stray adjacent year.
- **Only literal, pattern-matched citations count.** A standard named in prose without its recognisable token ("the sterile-products annex"), or one mangled by imperfect PDF ingest, is not seen. Extraction is case-insensitive regex, not comprehension.
- **De-duplication hides repeats and can mask mixed usage.** Within one SOP the same canonical citation collapses to a single row (the most severe occurrence), so `citations_found` counts *distinct* standards, not mentions. If a document cites Annex 1 correctly in one place and with an outdated date in another, only the outdated row survives — good for flagging, but you lose visibility that a correct citation also exists.
- **`unknown` is under-surfaced.** It is excluded from the top-level `summary` counts and from the PNG's status bars (which draw only current/review/outdated), so a corpus with unrecognised references could look cleaner at a glance than the per-SOP data shows. Read the per-SOP `warn` entries, not just the chart.
- **A human still adjudicates.** The module produces ready-to-action findings, but which superseded citation is a genuine gap versus an intentional historical reference (e.g. citing a legacy standard for a legacy record) is a judgement it cannot make.
