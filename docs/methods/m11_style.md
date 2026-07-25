# 11 — Style & Structure Standardization

**Question it answers:** Does each SOP follow the one house writing standard — markdown headings, the obligation word "must", verb-first steps, low passive voice — or has each department drifted into its own dialect?

**Deck slide:** 25.

**Scope:** Both. The module's declared scope is **per-SOP** — every English SOP gets its own four-attribute conformance verdict (pass / warn / fail / n/a) and its own remediation note — but it also rolls those observations up to **corpus-wide** counts (how many conform) and to a **per-department** style fingerprint (dominant obligation word, dominant heading style, average verb-first %, average passive rate) that drives the two-panel figure. Only English SOPs are analyzed (`corpus.english()`); Spanish/translated documents are not scored here.

---

## The source: what it reads

This module measures the observable half of the **Style profile (foundations Signal 7)** and combines it with two other foundation signals. For each SOP it reads four things, all computed from the prose itself:

- **Heading style** — derived from the document's real section headings (the foundation's *Sections* observation), excluding the synthetic "Preamble" placeholder. This is the parser's ability to recognize markdown `#`-headings, ALL-CAPS lines, roman-numeral headings, and "Step N:" markers, turned into a single label.
- **Dominant obligation modal** — which of `must` / `shall` / `should` / `will` / `responsible for` appears most in the body (part of Signal 7).
- **Verb-first step %** — the fraction of the document's *step lines* that open with a strong imperative verb (**foundations Signal 4 — verb-first steps**).
- **Passive per 100 words** — passive-voice density (**foundations Signal 2 — passive voice**), normalized per 100 words.

Why these four are defensible proxies for "one consistent house style": they are the *form* attributes an operator actually re-learns when moving between departments — how sections are labelled, whether a requirement says "must" or "should", whether steps command an action or narrate one, and whether responsibility is stated actively or hidden in passive constructions. They do not measure tone or content quality (see limitations), but they are exactly the mechanical, countable part of document consistency.

The manifest's `style_profile` field (e.g. `cln_caps_shall`) is carried through only as a **ground-truth validation label** (`house_profile` / `manifest_style_profile`). It is **not** an input to any verdict — every number below is computed from the text.

---

## How it works

For each English SOP (`_observe`):

1. **Heading style.** Collect the real section headings and pass them to `lexicon.detect_heading_style`. That helper (a small rule set, no library/model) counts how many headings look like "Step N:", roman numerals, or ALL-CAPS, and picks a label by threshold (exact cut-points in the next section). If there are no parseable headings it returns `"none"`.
2. **Dominant modal.** `lexicon.modal_counts` counts whole-word occurrences of each of the five obligation words with regular expressions (`\bmust\b`, `\bshall\b`, `\bshould\b`, `\bwill\b`, `\bresponsible for\b`). The dominant modal is the argmax over the fixed list `["must", "shall", "should", "will", "responsible for"]`; ties break toward the earlier entry in that list. If no obligation word appears at all, the modal is `"none"`.
3. **Verb-first %.** A regular expression (`STEP_RE`) pulls out "step lines" — a line that begins with a numbered marker (`1.` / `1)`), a "Step N:" / "Step N." / "Step N)" marker, or a bullet (`-`, `*`, `•`) — and strips the marker. Each stripped step is tested by `lexicon.sentence_starts_with_verb`, which returns true when the first alphabetic token is in the shared strong-imperative verb set (foundations Signal 4). Verb-first % = 100 × (verb-first steps ÷ step lines), rounded to 1 decimal; if there are **no** step lines the value is `0.0`.
4. **Passive per 100 words.** `lexicon.count_passive` (the Signal 2 regex heuristic) counts passive constructions in the body; the rate is 100 × passive count ÷ word count, rounded to 2 decimals.

The house standard it compares against is pulled from the shared lexicon — `lexicon.STYLE_PROFILES[lexicon.HOUSE_STYLE]`, where `HOUSE_STYLE = "env_doc_standard"` — giving heading style `"markdown"` and modal `"must"`. (The same profile key is named in `config/site_config.json` as `house_style_profile`.)

The department roll-up and the figure are built in `run`. The figure is **matplotlib**: a left "obligation strip" (one coloured cell per department showing its dominant modal and that word's share) and a right horizontal bar chart (verb-first % and passive/100w per department against the two house target lines). Two artifacts are also written: a per-SOP CSV and one small markdown remediation note per SOP.

---

## The scoring  (the critical section)

### The four house-style attributes and the conform/deviate rule

Each SOP is checked on exactly four attributes. An attribute **deviates** under these precise rules (all constants lifted verbatim from `m11_style.py`):

| Attribute | How it is observed | House standard | Deviates when |
|---|---|---|---|
| Heading style | `detect_heading_style(headings)` | `"markdown"` | observed heading style **≠** `"markdown"` |
| Obligation modal | argmax of the five modal counts | `"must"` | observed modal **≠** `"must"` |
| Verb-first steps | `round(100 × verb-first ÷ step lines, 1)` | `>= 15.0%` | value **< 15.0** (`VERB_FIRST_MIN = 15.0`) |
| Passive / 100 words | `round(100 × passive ÷ words, 2)` | `<= 1.5` | value **> 1.5** (`PASSIVE_MAX = 1.5`) |

Note the comparisons are strict on both numeric attributes: verb-first uses `< 15.0` (so exactly 15.0% conforms), and passive uses `> 1.5` (so exactly 1.50 conforms).

### How the heading-style label is decided

`detect_heading_style` takes the list of real headings (n of them) and returns the **first** matching label in this order (thresholds exact):

1. Empty list → `"none"`.
2. "Step N:" headings `>= n × 0.4` → `"numbered_plain"`.
3. Roman-numeral headings `>= n × 0.4` → `"roman"`.
4. ALL-CAPS headings `>= n × 0.5` → `"allcaps"`.
5. Otherwise → `"markdown"` (the default, and the only label that conforms).

An "ALL-CAPS" heading is one where the stripped text equals its uppercase form and has at least 4 alphabetic characters. A "roman" heading matches `^\(?[IVXLC]+[\).\s]`; a "Step N:" heading matches `^step\s+\d+\s*:`. Because `"markdown"` is the fallback bucket, the detector is really a *positive* test for the three off-standard heading styles: anything it can't positively classify as step/roman/allcaps is treated as house-conforming markdown.

### Per-SOP status bands (pass / warn / fail / n/a)

The verdict is a pure count of how many of the four attributes deviate — a strict weakest-link-style escalation, no weighting:

| Deviations | Status |
|---|---|
| 0 | **pass** |
| exactly 1 | **warn** |
| 2 or more | **fail** |
| document not measurable | **n/a** |

"Not measurable" means the SOP does **not** satisfy `word_count > 0 AND (has ≥1 heading OR ≥1 step line)`; such a document cannot be assessed and is set to `n/a` (0 attributes counted as deviating). In the demo corpus every SOP was measurable, so the mix is **7 pass, 3 warn, 30 fail, 0 n/a** across 40 documents.

### The remediation math (what each finding tells a reviewer to fix)

Each deviation produces one plain-language finding. Two of them carry a computed edit count:

- **Verb-first fix count** = `max(0, ceil(0.15 × step_lines) − verb_first_steps)` — the number of steps to reword so the document clears the 15% floor.
- **Passive fix count** = `max(1, passive_count − int(0.015 × word_count))` — passive clauses to recast to get under the 1.5/100w ceiling (`int(...)` truncates; the floor of `max(1, …)` means at least one is always suggested when passive deviates).

The heading and modal findings quote the observed count directly (e.g. "convert all N section headers", "replace those M 'shall' occurrences with 'must'").

### How departments roll up

The per-department fingerprint (used only for the figure and the corpus narrative — it does **not** produce a department pass/fail) is built with three different aggregations, deliberately chosen per attribute:

- **Dominant modal** — `argmax` over the five modals of the **pooled** counts across all of that department's SOPs (ties break toward the earlier `MODALS` entry). This is a count-weighted vote, not a per-SOP majority.
- **Modal share** — each modal's pooled count ÷ the department's total obligation-word count.
- **Dominant heading style** — the **mode** (most common) per-SOP heading label in that department.
- **Verb-first %** and **passive/100w** — the **simple mean** of the per-SOP rounded values (verb-first rounded to 1 decimal, passive to 2), *not* a pooled recomputation.

Corpus-level counts are then: **distinct observed styles** = number of distinct `(dominant heading, dominant modal)` department pairs (6 in the demo); **non-house styles** = how many of those distinct pairs are not `(markdown, must)` (5); **conforming** / **deviating** = per-SOP counts of `conforms` (7 / 33). Note the two live at different levels — a department can have a house-looking dominant pair yet still contain SOPs that fail on verb-first or passive.

---

## How to read the result

- **A pass** means all four form attributes match the house standard — the document is already in the one dialect operators are trained to read; no style rewrite needed.
- **A warn** means exactly one attribute is off (e.g. it uses "should" instead of "must", but headings, steps, and voice are fine). These are cheap, targeted fixes.
- **A fail** means two or more attributes are off — the document reads as a foreign dialect and needs real restructuring.
- **A high verb-first %** is good (directive, operator-friendly steps); **a high passive/100w** is bad (responsibility hidden, harder to follow). The two house target lines on the bar chart make the gap between a department and the standard visible at a glance.

Artifacts and how to act on them:

- **`style.png`** — the two-panel figure. The obligation strip shows, per department, which single obligation word dominates and its share (green = "must", the house word; anything else is flagged off-standard). The bars show verb-first % and passive/100w per department against the `>= 15%` and `<= 1.5` house lines. This is the "8 departments, 6 dialects, 1 standard" story for the slide.
- **`style_by_sop.csv`** — one row per SOP: heading style, dominant modal, verb-first %, passive/100w, the ground-truth `house_profile` label, `conforms`, and `deviates_on`. This is the reviewer's worklist — sort by `deviates_on` to batch the same fix across many documents.
- **`sops/SOP-XXX-000.md`** — a per-SOP note: the four-row observed-vs-house table plus the specific findings (with the fix counts above). A reviewer remediating a single document reads this one file.

---

## Worked example

**SOP-CLN-001 (Cleaning & Sanitization) — a full fail.** Its observed measurements (from `summary.json`): heading style `allcaps`, dominant modal `shall`, verb-first `0.0%`, passive `6.54` per 100 words. Trace each attribute through the rule:

| Attribute | Observed | House | Test | Verdict |
|---|---|---|---|---|
| Heading style | `allcaps` | `markdown` | `allcaps ≠ markdown` | deviates |
| Obligation modal | `shall` | `must` | `shall ≠ must` | deviates |
| Verb-first % | `0.0` | `≥ 15.0` | `0.0 < 15.0` | deviates |
| Passive/100w | `6.54` | `≤ 1.5` | `6.54 > 1.5` | deviates |

Four deviations → **fail** (2+ band). The generated findings quote the real underlying counts and the remediation math:

- Heading: "convert all **9** section header(s) to markdown '## N. Title'" (9 real headings, all read as ALL-CAPS ≥ 50% of 9).
- Modal: "'shall' is dominant (**37** uses)… replace those 37 with 'must'."
- Verb-first: "0.0% of **6** step lines… reword **1** step(s)" — because `ceil(0.15 × 6) − 0 = ceil(0.9) = 1`.
- Passive: "6.54 per 100 words (**51** constructions in **780** words)… recast **~40**" — because `51 − int(0.015 × 780) = 51 − int(11.7) = 51 − 11 = 40`.

Contrast three verdict bands from the same corpus, showing the count-of-deviations rule turning numbers into a status:

| SOP | Heading | Modal | Verb-first | Passive | Deviations | Status |
|---|---|---|---|---|---|---|
| SOP-DOC-003 | markdown ✓ | must ✓ | 15.4% ✓ (≥15.0) | 0.00 ✓ | 0 | **pass** |
| SOP-EQP-006 | markdown ✓ | should ✗ | 33.3% ✓ | 1.35 ✓ (≤1.5) | 1 | **warn** |
| SOP-CLN-001 | allcaps ✗ | shall ✗ | 0.0% ✗ | 6.54 ✗ | 4 | **fail** |

SOP-DOC-003 is the boundary case that proves the strict comparison: 15.4% is above the 15.0 floor, so verb-first conforms and the document passes. SOP-EQP-006 fails only the modal test ("should" not "must") — one deviation, so it lands in **warn**, not fail. At the department level, Cleaning's fingerprint rolls up to dominant modal `shall` and an average `6.3` passive/100w (mean of its eight SOPs, `6.27` before display rounding) against ENV's `0.2` — the house standard — which is the gap the figure dramatizes.

---

## What it cannot see (limitations)

- **Form, not meaning.** It measures headings, the obligation word, step openers, and passive density — not whether the instruction is correct, complete, or safe. A perfectly conforming document can still contain a wrong step; a failing one can be technically flawless.
- **"markdown" is the fallback bucket.** The heading detector positively identifies only step / roman / ALL-CAPS styles; everything else defaults to `"markdown"` and therefore *conforms* on heading. It cannot distinguish genuine `##` headings from plain title-case lines that simply don't match the other patterns — both read as house-conforming.
- **Heading recognition depends on ingest.** If the markdown splitter never sees a document's headers (e.g. PDF headers lost in ingest), the heading style becomes `"none"`, which counts as a heading deviation even for a well-structured original.
- **Step lines must be list-marked.** Verb-first % is computed only over lines that match the numbered / "Step N:" / bullet pattern. An SOP that writes genuine imperative steps as prose paragraphs has **zero** step lines and scores `0.0%` verb-first — flagged as deviating even though its instructions are directive. This is why several narrative-style departments read as 0%.
- **Passive and verb-first inherit their signals' blind spots.** Passive detection is the Signal 2 regex heuristic (misses unusual constructions, can over-count adjectives that look like participles); verb-first depends on the fixed strong-imperative verb set (Signal 4) — a valid step opening with an unlisted verb reads as non-verb-first. Both are relative densities, not grammatical ground truth.
- **The modal vote is count-based.** Dominant modal is a raw frequency argmax; a document that uses "must" a few times but "should" slightly more is labelled "should". A near-tie is treated the same as a landslide.
- **Warn/fail counts attributes, not severity.** A document off by one heading label and a document off by a 6-per-100-word passive rate are both "one attribute" in isolation; the band counts *how many* attributes deviate, not *how badly*. A reviewer must read the per-SOP note to judge magnitude.
- **English only, and the manifest label is not a check.** Translated SOPs are excluded from this module entirely, and the manifest `style_profile` is a validation label carried alongside — never an input — so a mislabelled manifest would not change any verdict, but also gives the module no second opinion.
