# 07 — Quality Scorecard

**Question it answers:** How audit-ready is each SOP — and the corpus as a whole — when quality is broken into five measurable dimensions and rolled up so a document is only as good as its worst gap?

**Deck slide:** 21.

**Scope:** Both. Every English SOP is scored on the same five 0–10 dimensions and given its own weakest-link overall, status, weakest-dimension diagnosis and radar chart (in `output/m07_scorecard/sops/`). Those per-SOP rows are then averaged into a corpus baseline and contrasted against one **illustrative** post-remediation target, mirroring the deck's "3.5 → 8.2" story.

---

## The source: what it reads

The scorecard is a **composite** capability: it does not introduce new raw measurements so much as combine the foundation signals into an auditor-facing quality verdict. Per SOP it consumes:

- **Ambiguous-term density** (Foundation Signal 1) and **passive-voice count** (Signal 2) — the un-actionable-language and hidden-responsibility proxies that feed *clarity*.
- **Reading grade** (Signal 5), specifically Module 7's own **self-contained Flesch-Kincaid** grade with a bullet-aware sentence count — feeds both *clarity* and *usability*.
- **Verb-first steps** (Signal 4) — the imperative-step fraction that feeds *usability*.
- **Style profile** (Signal 7) — dominant heading style and dominant obligation modal — feeds *consistency*.
- **Regulatory citations & currency** (Signal 6, via `RegKB`) — feeds *defensibility*.
- **Raw structural features read directly here:** which of six expected sections are present (heading text matched by keyword), the enumerated/`Step N:` step lines, the `next_review` date from the SOP header, and the document's cross-references resolved against the corpus.

Why these are defensible proxies for "audit readiness": each maps to a concrete, recurring audit finding. An operator cannot follow a procedure written above their reading level (usability), cannot execute a vague or passive instruction consistently (clarity), cannot rely on a document missing its Responsibilities or Revision History (completeness), must re-learn conventions when every department writes differently (consistency), and a superseded citation or an overdue review is a finding on its own (defensibility). None of it is a trained model — every point traces back to a counted word, a matched pattern, or a config table.

---

## How it works

For each English SOP the module:

1. **Measures the text.** It computes the reading grade (self-contained Flesch-Kincaid), ambiguity per 100 words, passive constructions per 100 words, the set of headings and their styles, which of six expected sections are present, the enumerated step lines and how many start with an imperative verb, the obligation-modal counts, the regulatory citations and their currency status (`RegKB.extract`), whether the periodic review is overdue, and whether any cross-reference points to an SOP absent from the corpus. The heading, step, section, modal and citation machinery are the shared foundation signals; the grade uses a bullet-aware sentence count so a fully bulleted SOP is not scored as one giant run-on sentence.
2. **Scores five dimensions** (each 0–10, higher = better) from those measurements — the exact formulas are below.
3. **Rolls them up** into a single `overall` using a *weakest-link* blend, and assigns a pass/warn/fail status.
4. **Diagnoses the weakest dimension**, writes plain-language "drivers" for each dimension, and estimates how many overall points would be recovered by lifting the weakest dimension alone to its target.
5. **Renders** a per-SOP radar (this SOP vs. the illustrative target) with **matplotlib** (via the pipeline's `viz` helper), plus one corpus figure combining a radar for the representative SOP and a per-dimension baseline-vs-target bar panel.

At corpus level it averages the five dimensions and the overalls across all scored SOPs, picks the lowest and highest scoring SOPs, and selects a **representative SOP** — the one whose five-dimension profile is Euclidean-closest to the corpus-average profile (ties broken by `sop_id`). Artifacts: `scorecard.png`, `scorecard.csv`, and one radar PNG per SOP under `sops/`. Everything is deterministic (`RANDOM_STATE = 42`; fixed analysis date).

---

## The scoring  (the critical section)

All five dimensions are on a 0–10 scale, higher = better, and every dimension is finally clamped to `[0, 10]`. The five in fixed order are **clarity, completeness, usability, consistency, defensibility**.

### Reading grade (input to clarity and usability)

Module 7's self-contained Flesch-Kincaid grade:

> grade = 0.39 × (words / units) + 11.8 × (syllables / word) − 15.59, then capped at a maximum of **30.0**.

`units` is the bullet-aware sentence count: the larger of the shared splitter's sentence count, the number of bullet/numbered/`Step N:` lines, and 1. Syllables are counted by vowel-groups with a silent-final-*e* adjustment (minimum 1 per word).

### 1. Clarity — inverse of ambiguity, grade, and passive density

> clarity = 10 − min(**5.0**, **1.8** × amb_per100) − clamp((grade − **9**) / **2.5**, 0, **3**) − min(**2.0**, **0.4** × passive_per100)

- Ambiguity penalty: 1.8 points per ambiguous term per 100 words, **capped at 5.0**.
- Grade penalty: nothing until grade 9, then (grade − 9) / 2.5 points, **capped at 3.0** (reached at grade 16.5 and above).
- Passive penalty: 0.4 points per passive construction per 100 words, **capped at 2.0**.

### 2. Completeness — fraction of six expected sections present

> completeness = 10.0 × (sections present) / **6**

The six expected sections are **purpose, scope, responsibilities, procedure, references, revision history**, detected by matching heading text against fixed keyword patterns (`purpose`; `scope`; `responsib`; `procedure|method|process|instruction`; `reference`; `revision`). Special case: if no heading matches *procedure*, the presence of any enumerated/`Step N:` step lines counts as the procedure section. So each missing section costs 10/6 ≈ 1.67 points; five of six present scores 8.33.

### 3. Usability — readability plus numbered, verb-first steps

> usability = clamp( readability + step_score , 0, 10)

- **readability** = clamp(**6.0** × (**18** − grade) / **10.0**, 0, **6**). Grade 8 (or lower) → 6.0; grade 18 → 0. Caps this component at 6.
- **step_score** = **2.0** + **2.0** × (verb-first steps / total steps), **but only if the SOP has any enumerated/`Step N:` steps**; with no steps at all, step_score = 0.0. So a document with steps earns a floor of 2.0 for having them, rising to 4.0 when every step is verb-first.

A no-steps SOP is therefore capped at 6.0 (readability only) and usually far lower; a document written entirely in prose with no numbered steps scores 0 on the step half.

### 4. Consistency — internal uniformity of heading style + obligation modal

> consistency = clamp( 10.0 × ( **0.55** × heading_unif + **0.45** × modal_unif ) )

- **heading_unif** = (count of the most common heading style) / (total headings); **0.3** if there are no headings.
- **modal_unif** = (count of the most common obligation modal) / (total modals); **0.4** if there are no modals.

A document that uses one heading style throughout and one obligation word throughout scores 10.0. Note this rewards *internal* uniformity, not conformance to the house standard — an SOP that is 100% ALL-CAPS headings and 100% "shall" scores a perfect 10 here even though the house standard is markdown headings and "must" (that house-standard question is Module 11's job, not this dimension's).

### 5. Defensibility — citations current, reference/revision sections, review currency, live cross-refs

Start at **10.0** and subtract:

| Condition | Penalty |
|---|---|
| No regulatory citations at all | −**4.0** |
| Has citations, fraction not "current" = `frac_bad` | −**3.5** × frac_bad |
| No References section present | −**1.5** |
| No Revision History section present | −**1.5** |
| Periodic review overdue (`next_review` < 2026-07-01) | −**2.0** |
| Any cross-reference points to an SOP absent from the corpus | −**2.0** |

Then clamp to `[0, 10]`. `frac_bad` is the share of the SOP's citations whose status is anything other than `current` (i.e. outdated / review / unknown, per Signal 6). A perfectly clean SOP that is merely overdue for review lands at exactly 8.0 — which is why 8.0 is the single most common defensibility value in the corpus.

### Roll-up — the weakest-link overall

> overall = **0.65** × mean(five dimensions) + **0.35** × min(five dimensions)

This is the deliberate design choice the author flagged. A plain average would let a document hide a fatal gap behind four strong dimensions; a pure minimum would throw away all information but the single worst number. The 65/35 blend keeps most of the weight on the balanced profile while giving the **weakest dimension** an extra, explicit pull — so a document is scored partly on *how good it is on average* and partly on *how bad its worst gap is*. In audit terms: a beautifully formatted, complete SOP that no operator can actually read is not audit-ready, and the roll-up refuses to let its high dimensions paper over that. Concretely, the overall always sits **below** the plain mean of the five bars whenever the dimensions are uneven, and the gap between them is exactly the "cost" of the weakest link.

### Status bands

| Overall | Status |
|---|---|
| ≥ **8.0** | **pass** |
| **6.0** to < 8.0 | **warn** |
| < **6.0** | **fail** |

(`PASS_AT = 8.0`, `WARN_AT = 6.0`.)

### The illustrative target (not a computed threshold)

`TARGET_PROFILE` = clarity **8.5**, completeness **9.5**, usability **8.5**, consistency **8.5**, defensibility **8.5**; `TARGET_OVERALL` = **8.2**. These are **illustrative** — labelled as such in every chart and finding. They mirror the deck's remediation headline; they are *not* derived from the profile (running the profile through the weakest-link formula would give ≈8.6, not 8.2). The target is a visual reference line for "what good looks like," never a computed pass mark. The pass mark is the 8.0 band above.

### Weakest-dimension diagnosis

The lowest-scoring dimension (ties broken alphabetically) is named the weakest link. Everything within **0.5** of that floor is treated as jointly weakest, capped at the two lowest. A per-SOP "projected gain" also reports how much overall would rise if that one dimension were lifted to its target value, all else held equal.

---

## How to read the result

- **A high overall (pass, ≥ 8.0)** means the SOP is strong on all five dimensions *and* has no single fatal gap. A **warn (6–8)** typically means one dimension is dragging an otherwise good document down. A **fail (< 6.0)** means either broad weakness or one dimension near zero (clarity and usability are the usual culprits in this corpus).
- **The per-dimension scores tell you *what* to fix.** Because the roll-up is weakest-link, the highest-leverage action is almost always lifting the single weakest dimension — the per-SOP finding quantifies exactly that ("lifting X alone to its target is worth ~N points").
- **`scorecard.csv`** is the full per-SOP matrix (sop_id, dept, five dimensions, overall) — the deck's remediation queue, sorted worst-first.
- **`scorecard.png`** shows the representative SOP's radar (as-is vs. illustrative target) beside the corpus-average bars per dimension, with the target drawn as a marker, not a competing bar.
- **`sops/<SOP-ID>.png`** is each SOP's own radar, coloured by status, against the illustrative target profile.
- **A reviewer should act on the weakest dimension first and protect the strongest** — the findings explicitly say "remediation should protect it, not rewrite it," because uniform structure (consistency, completeness) is usually the corpus's strength and should not be disturbed while fixing prose.

---

## Worked example

**SOP-MFG-001** (Manufacturing) is the corpus's **representative SOP** — the profile closest to the corpus average — so it is the one drawn on `scorecard.png`. Its measured inputs: reading grade **12.6**, **1.19** ambiguous terms and **3.69** passive constructions per 100 words, **14** enumerated steps of which **0%** start with an imperative verb, 10 headings all markdown, obligation wording 100% "will", 2 regulatory citations all current, References and Revision History both present, periodic review overdue since 2026-03-15.

Tracing the five dimensions:

- **Clarity = 4.94.** 10 − min(5, 1.8×1.19 = 2.14) − clamp((12.6−9)/2.5 = 1.44, 0, 3) − min(2, 0.4×3.69 = 1.48) = 10 − 2.14 − 1.44 − 1.48 = **4.94**.
- **Completeness = 10.0.** All six sections present → 10 × 6/6.
- **Usability = 5.23.** readability = 6×(18−12.6)/10 = 3.24; step_score = 2.0 + 2.0×(0/14) = 2.0 (it has steps, but none verb-first); 3.24 + 2.0 ≈ **5.23**.
- **Consistency = 10.0.** heading_unif = 1.0 (10/10 markdown), modal_unif = 1.0 (100% "will") → 10 × (0.55 + 0.45).
- **Defensibility = 8.0.** Start 10, citations all current (no penalty), both sections present, but review overdue → −2.0 → **8.0**.

Roll-up: mean(4.94, 10.0, 5.23, 10.0, 8.0) = 7.63; min = 4.94. overall = 0.65×7.63 + 0.35×4.94 = **6.69** → rounds to **6.7**, a **WARN**. Note the weakest-link pull: the plain mean is 7.6, but the roll-up drags it down to 6.7 because clarity (4.94) is the worst dimension. The diagnosis names **clarity** the weakest link and estimates that lifting it to its 8.5 target would recover ~0.6 overall points.

For contrast, the corpus's **lowest** SOP, **SOP-WHS-002 (overall 3.4, FAIL)**, shows the roll-up at its most brutal: grade 18.4, 3.08 ambiguous and 7.93 passive per 100 words drive **clarity to 0.0** (all three penalties hit their caps: 5 + 3 + 2 = 10), and with **no numbered steps at all**, usability is also **0.0**. Even with completeness 8.3, consistency 10.0 and defensibility 8.0, the two zeros pull a 5.3 plain mean down to 0.65×5.27 + 0.35×0.0 = **3.42** — matching the deck's 3.5 baseline. At the other end, house-standard **SOP-ENV-001** reaches **8.9 (PASS)**, proving the illustrative 8.2 target is achievable with the corpus's own documents.

Corpus baseline (n = 40): average overall **6.1**, with weakest dimension **usability (4.4)** and clarity (5.3) close behind — the prose dimensions are the crisis — while completeness (9.9) and consistency (9.7) are the structural strengths. (The corpus overall of 6.1 is the average of the per-SOP weakest-link overalls, not a weakest-link of the averages, which is why it sits below the 7.3 plain mean of the five dimension averages.)

---

## What it cannot see (limitations)

- **It is a composite of proxies, and inherits every one of their blind spots.** Clarity relies on the fixed ambiguous-word list and the regex passive detector; usability rewards a fixed imperative-verb list; defensibility knows only what the regulatory-version table knows. A vague instruction phrased without a listed word, a valid step opening with an unlisted verb, or a standard revised after the config table was last updated will all be scored wrongly — see Foundations for each signal's boundaries.
- **The target is illustrative, not a validated standard.** `TARGET_PROFILE` and the 8.2 headline exist to tell the deck's story. Do not treat "meets target" as a compliance pass; the actual band mark is 8.0, and both are internal conventions, not a regulatory bar.
- **The weights (0.65/0.35, the per-dimension coefficients, the section list, the penalty sizes) are engineering judgements, not calibrated against audit outcomes.** They are transparent and defensible, but no external ground truth says clarity's ambiguity penalty *should* be 1.8, or that the weakest link *should* carry 35%. A reviewer should read the dimension scores, not just the overall.
- **Consistency measures internal uniformity, not correctness.** A document uniformly written in a non-standard style (ALL-CAPS headings, "shall") scores 10 here; whether that style matches the house standard is a different question (Module 11).
- **Defensibility's overdue check is date-mechanical.** It compares `next_review` to a fixed analysis date (2026-07-01); it cannot tell whether a review is genuinely due, waived, or in progress, and it checks the *version cited*, never whether the SOP's content actually complies.
- **Empty documents cannot be scored.** An SOP with no body text yields a status of `n/a` rather than a number — absence of a score is itself a flag for a human.
- **The scorecard suggests where to look and quantifies the leverage; it does not certify audit readiness.** A high overall is a document worth defending, not a guarantee; a low overall is a document worth reading, not proof of a defect. A qualified reviewer still decides.
