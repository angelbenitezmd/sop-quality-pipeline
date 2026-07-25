# 12 — Multi-Language Harmonization

**Question it answers:** For every Spanish SOP paired with its English parent, does the translation agree with the original on its numbers, its number formatting, and its structure — or has something drifted, been dropped, or been mistranslated?

**Deck slide:** 26.

**Scope:** both — corpus-wide **and** per-SOP. The corpus rollup reports how many EN/ES pairs were audited and how many total discrepancies were found across three categories. Because scope is `per_sop`, *every* English SOP also gets its own entry: a paired one carries that pair's discrepancy table and a comparison card, while an English SOP with no translated variant is reported explicitly as `n/a` ("checked, nothing to harmonize") rather than being silently omitted.

---

## The source: what it reads

This module does **not** consume the seven named foundation signals (ambiguity, passive voice, readability, citations, style, etc.). Harmonization is a comparison between two documents, so instead it reads a small set of raw text features straight from each SOP's parsed text and compares the English against the Spanish:

- **Numeric quantities with units** — every number in the body immediately followed by a recognised unit token (`%`, `ml`, `min`/`minutes`/`minutos`, `degrees`/`grados`/`°`). *Why valid:* a translated SOP that says "60%" where the master says "70%", or drops a contact time, is a direct GMP defect — the operator would run the wrong process. Numbers-with-units are the machine-checkable core of "do the two versions specify the same thing."
- **Decimal separator style** — whether the body contains a comma-decimal like `0,5` (Spanish/European convention) versus a point-decimal like `0.5`. *Why valid:* mixed decimal conventions across a bilingual document set are a known transcription-error source; consistency is a defensible quality property on its own.
- **Sections** — the shared **Sections** observation from the foundations (a heading starts a new section; markdown `#`, roman-numeral, or ALL-CAPS headings all count). Used two ways: the *number* of sections in each language, and whether a **safety/warning section** exists in each. *Why valid:* if the English parent has a "Safety Warnings" section and the Spanish version does not, a Spanish-reading operator loses hazard information — the single most consequential thing that can go missing in translation.

Everything is computed from the parsed SOP text, not read off any manifest, so the verdict traces back to words actually present in each document.

---

## How it works

1. **Pair the documents.** Walk the corpus for every SOP whose `language == "es"` and that carries a `parent` id in its frontmatter (exposed as `parent_id`). Look the parent up by id (`corpus.get(parent_id)`); if the parent exists, that English/Spanish pair is audited. Pairs are processed in id-sorted order, so the output is deterministic.
2. **Extract numeric values by unit** from each document. A single regular expression finds a number (point- *or* comma-decimal) directly followed by a unit token. Units are folded to a canonical form — anything starting `min` → `min`; `degrees`/`grados`/`°` → `deg`; `%` and `ml` stay as-is — and each value is normalised (comma swapped for point) and rounded to 3 decimals, then collected into a **set per unit**. So each document becomes a map like `{"%": {70}, "min": {0.5, 5.0}}`.
3. **Detect decimal-style drift** by asking, per document, whether a `digit,digit` pattern appears anywhere in the body (a boolean, not a count).
4. **Measure structure** by counting each document's sections (`len(sop.sections)`) and by scanning section headings for safety keywords (in English and Spanish, accent-insensitive) to get a yes/no "has a safety section" per document.
5. **Compare and record rows.** Each disagreement becomes one discrepancy row tagged with its category (`value` / `format` / `structure`), the English value, and the Spanish value.
6. **Roll up and render.** Rows are counted per pair per category and drawn as a compact horizontal **stacked bar** (one bar per pair, coloured by category) beside an annotated EN-vs-ES detail table, using **matplotlib** via the shared `viz` helpers. The flat issue table is also written to `discrepancies.csv`, and each translated pair gets its own PASS/FAIL comparison card PNG under `sops/`.

No trained model, no library-computed score — every number is a rule you can read.

---

## The scoring  (THE CRITICAL SECTION — omit nothing)

### Pairing rule (which EN/ES pairs exist)

A Spanish document is paired to an English parent only when **both** hold:

- `language == "es"` (the corpus rollup) — or, for the per-SOP variant lookup, `language != "en"`; and
- the frontmatter `parent` field is set (`parent_id`), and `corpus.get(parent_id)` finds that parent in the corpus.

If several variants name the same parent, the first in id-sorted order is kept. English SOPs with no such variant are still reported — as `n/a`.

### The three discrepancy categories

Categories are exactly `["value", "format", "structure"]`, and each is detected as follows.

**1. `value` — numeric quantities that disagree.**
For each canonical unit appearing in *either* document, compare the English value-set against the Spanish value-set. If the two sets are not equal, emit one `value` row for that unit. The row's `en_value`/`es_value` list the *full* sorted set on each side (a `—` if a side has none). Key mechanics that matter for reading the result:

- The unit-and-number pattern is `(\d+(?:[.,]\d+)?)\s*(%|ml|minutes|minutos|min|degrees|grados|°)`, case-insensitive. A number counts only when a unit token follows it (optionally with whitespace between).
- Units are canonicalised before comparison: `min`/`minutes`/`minutos` → `min`; `degrees`/`grados`/`°` → `deg`; `%` and `ml` unchanged. So "5 min" and "5 minutos" are compared as the same unit.
- Every value is normalised by replacing `,` with `.` and rounding to **3 decimals** before it enters the set. This is deliberate: it means `0,5` and `0.5` are treated as the *same value*, so decimal-style differences never masquerade as value differences — that is the `format` category's job.

**2. `format` — decimal-separator convention drift.**
Per document, a boolean: does the body contain the pattern `\d,\d` (a comma between two digits)? If English and Spanish disagree on this boolean (one uses comma decimals, the other point decimals), emit exactly one `format` row. `en_value`/`es_value` read `"comma decimals (0,5)"` or `"point decimals (0.5)"` accordingly.

**3. `structure` — section count and/or a missing safety section.** This category can emit up to **two** rows:

- *Section-count mismatch:* if `len(en.sections) != len(es.sections)`, emit one `structure` row reading `"{n_en} sections"` vs `"{n_es} sections"` with issue `"Section-count mismatch (n_en EN vs n_es ES)"`.
- *Safety section present on one side only:* a document "has a safety section" if any of its section headings, with leading numbering stripped (regex `^\s*\d+(?:\.\d+)*\.?\s*`) and accents removed and lowercased, contains any of the safety keywords: **safety, warning, hazard, caution, seguridad, advertencia, precaucion, peligro**. If the English and Spanish "has-safety" booleans differ, emit one `structure` row. It also sets an internal `missing_section` flag — but **only** in the specific direction `safety present in EN and absent in ES` (`missing_section = safe_en and not safe_es`). The reverse (present in ES, absent in EN) still produces a visible row but does not increment the "missing a section present in the parent" counter.

### How components combine (there is no weighted score)

There is no composite 0–100 number and no weighting. The unit of output is the **discrepancy row**. Counts are pure tallies:

- Per pair, per category: `counts[pair][category] = number of rows in that category`.
- Per pair total = sum of its rows across all three categories.
- Corpus total = number of rows across all pairs.
- `pairs_with_missing_sections` = number of pairs whose `missing_section` flag fired (EN-has, ES-missing safety section).

### Status bands (the verdict)

The verdict is **fail-if-any-discrepancy**, else pass, with a distinct `n/a` for "no variant":

| Situation | Status | Card verdict |
|---|---|---|
| EN SOP has a translated variant **and** ≥ 1 discrepancy row | `fail` | `FAIL` |
| EN SOP has a translated variant **and** 0 discrepancy rows | `pass` | `PASS` |
| EN SOP has **no** translated variant | `n/a` | (no card) |

In code: per-SOP status is `"fail" if rows else "pass"`, or `"n/a"` when no variant exists; the comparison-card verdict is `"FAIL" if rows else "PASS"`. There is no "warn" tier — a single row fails the pair. This is intentional for a GMP context: any numeric, format, or structural divergence between an approved master and its translation is a finding, not a warning.

### Corpus-level summary numbers

The rollup reports exactly three: `pairs_checked` (number of EN/ES pairs audited), `total_discrepancies` (total rows), and `pairs_with_missing_sections` (pairs where the EN parent's safety section is absent from the ES translation).

---

## How to read the result

- **Zero discrepancies on a pair (`pass` / `PASS`)** means the translation matches the master on every recognised number, uses the same decimal convention, has the same section count, and preserves the safety section. It does **not** certify the prose is a faithful translation — only that these mechanical checks agree.
- **Any discrepancy (`fail` / `FAIL`)** flags the pair for human reconciliation against the approved master. Read the category to know the stakes: a `value` row means the two versions specify different quantities (potentially a wrong-process risk); a `structure` row naming a missing safety section is the most serious — hazard information a Spanish-reading operator will not see.
- **`n/a`** means the English SOP was checked and simply has no Spanish variant in the corpus. This is reported deliberately so a reviewer can distinguish "checked, nothing to harmonize" from "never checked."

**Artifacts:**
- `multilang.png` — the corpus figure: a stacked bar of discrepancies per pair coloured by category (`value` / `format` / `structure`), beside a detail table spelling out every discrepancy with the actual EN and ES values (the ES value drawn in the "bad" colour).
- `discrepancies.csv` — the flat machine-readable issue table, columns `pair, category, en_value, es_value, issue`.
- `sops/<SOP-ID>.png` — one comparison card per translated pair, showing each issue's EN value vs ES value with a PASS/FAIL banner.

A reviewer should treat every `fail` as a required reconciliation before the Spanish document is released, prioritising missing-safety-section findings first.

---

## Worked example

From the demo corpus (`output/m12_multilang/summary.json`), **2 EN/ES pairs** were audited, producing **4 discrepancies** (value 1, format 1, structure 2), with **1 of 2** pairs missing a section present in its English parent. Trace both pairs:

**Pair 1 — SOP-CLN-001 vs SOP-CLN-001-ES → 2 discrepancies → FAIL.**
- *Value:* The English says the IPA concentration "shall be used is **70%**"; the Spanish says "al **60%**". Extract by unit: EN `% → {70}`, ES `% → {60}`. The sets differ, so one `value` row is emitted: `en_value = "70%"`, `es_value = "60%"`. (Note the contact-time numbers — EN "0.5 minutes"/"5.0 minutes" vs ES "0,5 minutos"/"5,0 minutos" — do *not* trigger a value row: after comma-to-point normalisation and rounding to 3 decimals both sides give `min → {0.5, 5.0}`, which are equal.)
- *Format:* EN's body contains `0.5` (point decimals) and no `digit,digit`; ES's body contains `0,5` (comma decimals). The booleans differ, so one `format` row: `en_value = "point decimals (0.5)"`, `es_value = "comma decimals (0,5)"`.
- *Structure:* both documents parse to **9 sections** and both carry their sections symmetrically, so no section-count row and no safety-mismatch row.
- Tally: value 1, format 1, structure 0 → **2 rows → status `fail`**.

**Pair 2 — SOP-MFG-001 vs SOP-MFG-001-ES → 2 discrepancies → FAIL.**
- *Structure (count):* EN parses to **10 sections**, ES to **9**. `10 != 9`, so one `structure` row: `"10 sections"` vs `"9 sections"`.
- *Structure (safety):* EN has the heading "## 5. Safety Warnings" — numbering stripped to "Safety Warnings", lowercased, contains the keyword `safety` (and `warning`), so `safe_en = True`. The Spanish version has no safety/warning heading (it goes straight from "Materiales y Equipo" to "Procedimiento"), so `safe_es = False`. The booleans differ → a second `structure` row (`"Safety/Warnings section present"` vs `"(missing)"`), and because the direction is EN-has / ES-missing, `missing_section` fires. The per-SOP finding spells this out: *"Missing section in SOP-MFG-001-ES: 'Safety Warnings' exists in SOP-MFG-001 only — re-translate before release."*
- No value rows (numbers agree) and no format row.
- Tally: value 0, format 0, structure 2 → **2 rows → status `fail`**, and this is the **1 pair** counted in `pairs_with_missing_sections`.

**Rollup:** 2 pairs, 4 rows (value 1, format 1, structure 2), 1 pair missing a parent section. And of the **40** English SOPs in the corpus, **38** have no translated variant and are each reported as `n/a` — checked, nothing to harmonize, never skipped.

---

## What it cannot see (limitations)

- **It only checks numbers next to a fixed unit list.** A quantity written with a unit outside `%`, `ml`, `min`/`minutes`/`minutos`, `degrees`/`grados`/`°` (kg, rpm, pH, µg, hours, psi, °C spelled differently) is invisible — a mistranslated dose in those units passes silently. A number with no unit at all is never compared.
- **Value comparison is set-based and unit-blind to position.** It asks "do the two documents mention the same set of %-values?", not "does step 3's value match step 3's value." Two documents that both contain `{70, 90}` for `%` agree even if the 70 and 90 are swapped between steps. Conversely, a value legitimately present in only one language (an extra example) reads as a discrepancy.
- **`°` collapses to `deg`, losing the scale.** "37 degrees" (Celsius) and "37 grados" compare as equal, but the module cannot tell °C from °F, and it does not read a trailing `C`/`F` letter — a Celsius-vs-Fahrenheit mistranslation of the same number is not caught.
- **Format drift is a single global boolean per document.** One `0,5` anywhere flips the whole document to "comma decimals." A document that mixes both conventions internally, or that has no decimals at all, cannot be characterised precisely, and a pair where *both* sides happen to use comma decimals shows no format finding even if neither follows house style.
- **Structure is counted, not aligned.** Equal section counts pass even if the sections are in a different order or a section was replaced rather than dropped. The safety check keys on a fixed keyword list in two languages — a hazard section titled with a synonym not in the list (e.g. "EHS", "PPE Requirements") is not recognised as a safety section, so a genuinely present section can read as missing, or a missing one as present.
- **Direction asymmetry in the missing-section counter.** `pairs_with_missing_sections` counts only EN-has / ES-missing. A safety section present in the Spanish but absent from the English parent still produces a visible row but is *not* counted as a "missing" pair.
- **Pairing depends entirely on frontmatter.** A Spanish translation with no `parent` id, a wrong parent id, or a parent not present in the loaded corpus is never paired — it simply is not audited, and no warning is raised about the orphan. The module also never checks that the translation is *linguistically* correct: faithful wording, correct terminology, and completeness of prose are entirely a human's judgment. This tool flags mechanical divergences; a qualified bilingual reviewer must adjudicate the translation itself.
