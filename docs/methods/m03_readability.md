# 03 — Readability & Complexity Scoring

**Question it answers:** Does each SOP read at a level a general shop-floor operator can actually follow, or is the prose pitched above them?

**Deck slide:** 17.

**Scope:** Both — corpus-wide *and* per-SOP. Every English SOP gets its own reading-grade verdict (pass / warn / fail) and a small text scorecard in `output/m03_readability/sops/`, and those roll up into a corpus average, a "percent above Grade 12" figure, and a single bar chart that plots each document individually. Spanish (`-ES`) variants are excluded — only documents whose language is `en` are scored.

---

## The source: what it reads

This module uses exactly one foundation signal: **Signal 5 — Reading grade (readability)**. It does not touch ambiguity, passive voice, citations, or style; its whole job is the reading-grade lens.

Concretely it reads each SOP's `full_text` — the document **title plus body** joined together — and hands that raw string to the `textstat` library. It does not consume any of the pipeline's counted signals (no ambiguous-term list, no imperative-verb list); the three formulas below do their own internal sentence-splitting and syllable-counting on the text. The only pipeline-derived text views it uses are for *context*, not for the grade itself: `words` (letter/apostrophe tokens from the body) and `sentences` feed the "words per sentence" figure printed alongside each score.

Why reading grade is a defensible proxy: the deck's thesis is that operators cannot reliably follow SOPs written above their reading level. US school-grade level is the standard, auditable measure of that. It is a surface formula — it counts sentence length and word complexity, not meaning — so a high grade is a **flag to review**, never proof of a defect (see limitations).

---

## How it works

1. **Score each English SOP with three `textstat` formulas.** For every document the module computes three independent US grade-level estimates from the `textstat` package:
   - `flesch_kincaid_grade` — Flesch-Kincaid grade,
   - `gunning_fog` — Gunning fog index,
   - `coleman_liau_index` — Coleman-Liau index.

   All three are driven by the same two levers (sentence length and word complexity) but weight them differently — FK and fog lean on syllables, Coleman-Liau on characters-per-word — so agreement across the three is a robustness check and disagreement tells the rewriter what to attack.

2. **Average the three into one grade.** The three raw formula outputs are averaged with equal weight into a single mean grade per SOP.

3. **Rank and flag.** SOPs are sorted worst-first (highest mean grade at the top). Each is flagged relative to the Grade-12 line, and each gets a three-way pass/warn/fail band.

4. **Roll up the corpus.** The module computes the corpus mean grade, the mean of each individual formula, the count and percent of SOPs above Grade 12, and names the least- and most-readable documents.

5. **Render artifacts.** `matplotlib` draws a horizontal bar chart (`readability.png`) of every SOP's mean grade with a dashed Grade-12 reference line and a dotted corpus-average line; a `scores.csv` lists all SOPs; and one markdown scorecard per SOP is written to `sops/<SOP-ID>.md`.

Everything is deterministic — the same text always yields the same grade, which is what makes it re-runnable for an auditor.

---

## The scoring  (the critical section)

### The three metrics and how they combine

Each SOP's mean grade is the **plain equal-weight average of the three textstat formulas**:

> mean grade = ( Flesch-Kincaid grade + Gunning fog index + Coleman-Liau index ) / 3

There are no weights — each formula contributes one-third. Each of the three formula outputs is rounded to **1 decimal place** for display, and the mean is computed from the full-precision formula outputs and then rounded to 1 decimal. (A precision consequence: re-averaging the three *displayed* one-decimal numbers can occasionally differ from the reported mean by 0.1, because the module averages before rounding.)

### The Grade-12 threshold and the "percent above" figure

- **`GRADE_THRESHOLD = 12.0`** — the end of a general-audience (Grade 12) reading level. This is the "floor target."
- A document's corpus-level flag is **`above`** if its mean grade is **strictly greater than 12.0**, otherwise **`ok`** (so a mean of exactly 12.0 is `ok`).
- **`pct_above_grade12 = round(100.0 × (number of SOPs above) / (total SOPs), 1)`** — the headline "share of the corpus reading above operator level," to one decimal.

### The per-SOP pass / warn / fail bands

The three-way verdict comes from two cut points — `GRADE_THRESHOLD = 12.0` and **`WARN_CEILING = 16.0`** — applied to the mean grade:

| Status | Exact condition on mean grade | Plain-language level |
| --- | --- | --- |
| **pass** | mean grade ≤ 12.0 | "high-school level or below" |
| **warn** | 12.0 < mean grade ≤ 16.0 | "college level" |
| **fail** | mean grade > 16.0 | "graduate level" |

The bands are inclusive at the top of each range: exactly 12.0 is a pass, exactly 16.0 is a warn. These bands and the corpus `above`/`ok` flag agree at the 12.0 line — everything that is `warn` or `fail` is also `above`.

### The "grades vs floor" delta and per-formula deltas

- Each SOP reports a signed **delta = round(mean grade − 12.0, 1)** — positive means above the floor.
- The delta is phrased as text: if its absolute value is **< 0.05** it reads "exactly at" the floor; otherwise "*X.X* grades above" / "*X.X* grades below."
- The scorecard table also lists each formula's own gap to the floor: **round(formula grade − 12.0, 1)**.

### The "too little prose" guard

- **`MIN_SCOREABLE_WORDS = 40`.** If an SOP's body has fewer than 40 word-tokens, the reading grade is treated as statistical noise: the module still emits an entry (no document is dropped) but sets status **`n/a`** with the flag "not scored — too little prose" and makes no pass/warn/fail judgement. In the current demo corpus no document trips this guard.

### The "driver" formula

For each scored SOP the module names which of the three formulas **runs highest** (the plain maximum of the three rounded values) and maps it to a remediation hint:
- Flesch-Kincaid highest → "long sentences carrying polysyllabic words,"
- Gunning fog highest → "long sentences packed with three-syllable+ terms,"
- Coleman-Liau highest → "long words and dense character-per-word load."

### Supporting count: words per sentence

Printed for context (it does **not** feed the grade). The sentence count is **max( count of `sentences`, count of terminal `.`/`!`/`?` marks in the body, 1 )** — the max guards against an all-bullet SOP collapsing to a single "sentence." Then **words per sentence = round( word-token count / that sentence count, 1 )**. This figure also switches the *warn* remediation wording: at **≥ 20** words/sentence the advice is "split the long sentence"; below 20 it is "the load is vocabulary rather than length — plain-word substitutions."

---

## How to read the result

- **A low mean grade is good.** Grade 8–10 ≈ general audience; Grade 13+ ≈ college; the module's own bands call ≤ 12 executable as-written, 12–16 a re-read tax, > 16 effectively unusable at the point of use.
- **`readability.png`** — one horizontal bar per SOP, worst (highest grade) on top. Green bars are at/below Grade 12, red bars above it; the dashed line is the Grade-12 threshold and the dotted line is the corpus average. This is the slide-17 visual and the fastest way to see how much of the corpus is red.
- **`scores.csv`** — every English SOP with its three formula grades, mean grade, and `above`/`ok` flag; sort or filter it to build a remediation queue.
- **`sops/<SOP-ID>.md`** — the per-document scorecard: status banner, the four-row metric table (three formulas + mean, each with its gap to Grade 12), findings, and corpus context (rank, corpus mean, words per sentence).
- **How to act:** treat `fail` documents as priority rewrites (imperative-voice, shorter sentences); treat `warn` documents by the driver hint — if words/sentence is high, split sentences; if not, swap jargon for plain words. A high grade on a genuinely technical SOP is a review prompt, not an automatic defect.

---

## Worked example

**Least-readable document: `SOP-EQP-005`** (rank 1 of 40).

Its three formula grades, straight from `summary.json`:

| Formula | Grade | Gap to Grade 12 |
| --- | --- | --- |
| Flesch-Kincaid grade | 34.8 | +22.8 |
| Gunning fog index | 39.7 | +27.7 |
| Coleman-Liau index | 17.6 | +5.6 |

- **Average:** (34.8 + 39.7 + 17.6) / 3 = 92.1 / 3 = **30.7** → reported mean grade **30.7**.
- **Delta:** 30.7 − 12.0 = **+18.7** → "18.7 grades above Grade 12."
- **Band:** 30.7 > 16.0 → **fail**, "graduate level."
- **Flag:** 30.7 > 12.0 → **above**.
- **Driver:** Gunning fog (39.7) is the highest of the three → "long sentences packed with three-syllable+ terms," consistent with its **76.3 words per sentence**.

So a single number — mean Grade 30.7 — turns into the verdict *fail / graduate level / priority imperative-voice rewrite*. This one document is the reason the corpus's worst bar dwarfs the rest.

**Contrast — most-readable: `SOP-DOC-002`** (rank 40 of 40): FK 7.8 / fog 9.6 / CLI 10.4 → mean (27.8 / 3) = **9.3**, delta −2.7 → **pass**, "high-school level or below." Here Coleman-Liau (10.4) is the highest of the three, so the driver hint flips to "long words and dense character-per-word load" rather than long sentences.

**Corpus roll-up:** with 33 of 40 SOPs above Grade 12, `pct_above_grade12 = round(100 × 33 / 40, 1) =` **82.5%**; the corpus mean grade is **16.3** (FK 15.6 / fog 19.0 / CLI 14.4); per-SOP verdicts are **7 pass (≤ 12), 12 warn (12–16), 21 fail (> 16)** — and 12 + 21 = 33 matches the "above" count exactly.

---

## What it cannot see (limitations)

- **It is a surface formula, not comprehension.** All three metrics count syllables, characters, and sentence length — not whether the instruction is *correct* or *followable*. A clear, well-sequenced procedure that happens to use necessary technical vocabulary ("chromatography," "endotoxin") scores as "hard"; a fluent-but-wrong instruction scores as "easy."
- **Legitimate technical terms inflate the grade.** A high grade can be entirely defensible domain language. That is exactly why the output is a flag to review, not a defect — a human must judge whether the complexity is necessary.
- **Garbage can score "normal."** As the foundations note, un-cleaned or fragmented PDF text can produce a *normal-looking* grade because the sentence-length / syllable ratio stays stable even when the text is broken. A passing grade is not proof the text is intact.
- **The Grade-12 floor and the 12/16 band edges are policy choices, not physics.** A document at 12.1 is `warn` and one at 12.0 is `pass`, though they are indistinguishable to a reader. Treat documents near the cut points as ties, not as meaningfully different.
- **Three formulas, one blind spot.** All three are variants of the same length-plus-complexity idea, so they tend to move together. Averaging them reduces per-formula quirks but does not add an independent view of clarity — none of them can see structure, layout, tables, diagrams, or how the steps are ordered.
- **Sentence-counting is heuristic.** The `textstat` formulas and the module's own supporting sentence count rely on punctuation. Heavily bulleted or fragment-style SOPs can be counted as very short or very long "sentences," pushing the grade either way; the max-of-two-counts guard mitigates but does not eliminate this.
- **Below 40 words it declines to judge.** Very short SOPs are reported but not scored, so this module contributes no readability verdict for stubs — a human must assess those directly.
- **Spanish and other non-English SOPs are out of scope.** Only `en` documents are scored; translated variants get no reading-grade verdict here.
