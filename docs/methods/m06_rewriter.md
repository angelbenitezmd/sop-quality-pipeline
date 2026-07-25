# 06 — LLM-Assisted SOP Rewriting

**Question it answers:** If we mechanically rewrite an SOP for clarity, how much easier does it get to read, how much shorter, and how much of its vagueness can we surface as explicit open items for a subject-matter expert — without silently inventing specifications?

**Deck slide:** 20.

**Scope:** Both. Every English SOP is rewritten and measured before/after (`per_sop`), and a single deterministically-chosen "worst-quality complex" SOP is promoted to the flagship view with the headline chart and a full side-by-side Markdown. The corpus roll-up reports a mean before/after reading grade and a total count of open items raised across all documents.

---

## The source: what it reads

The rewriter consumes the SOP **body** text (the prose after the YAML header) and re-derives three of the foundation signals on it, before and after its own transformation:

- **Signal 5 — Reading grade (readability).** Measured here with the **`textstat`** library's Flesch-Kincaid Grade (`textstat.flesch_kincaid_grade`), rounded to one decimal. This is the module's primary success metric: did the rewrite make the document easier to read?
- **Signal 1 — Ambiguous terms.** Re-counted with the shared ambiguity lexicon (`lexicon.find_ambiguous_terms`, the ~45-term list defined in Foundations). Used to measure how much un-actionable vagueness remains *unresolved* after rewriting.
- **Signal 2 — Passive voice.** Re-counted with the shared passive detector (`lexicon.count_passive`). Used to show that converting passive constructions to imperatives actually reduces passive density.

It also reads two raw text features directly: a **word count** (tokens matching the pattern for letters-and-apostrophes) and, derived from it, an **estimated page count** (words divided by 450).

Why these are defensible proxies for "did the rewrite help": reading grade and passive density are the two levers the deck's thesis rests on (operators can't reliably follow SOPs written above their level or written in responsibility-hiding passive voice), and ambiguous-term density is the direct measure of how much of the procedure is un-executable. Measuring all three before and after makes the effect of the rewrite auditable rather than asserted.

---

## How it works

The engine is **rule-based**, deterministic, and runs on plain regular expressions and string substitution — there is no trained model in the path that actually executes. The rewrite proceeds block by block so headings and Markdown tables survive intact:

1. **Block segmentation.** The body is split on blank lines. Any block containing a `|` is treated as a Markdown table and copied verbatim. A single ALL-CAPS line of at least 4 letters becomes a `## Title-Case` heading. Blocks beginning with `1.` (a numbered step) are split into contiguous steps and each step is renumbered sequentially. Everything else is treated as a paragraph. Wrapped lines within a block are re-joined so multi-line steps and paragraphs stay whole.

2. **Cleanup pass** (applied to each paragraph/step before splitting):
   - **Nominalization repair.** 18 fixed patterns of the form "the <noun> of" collapse to a gerund — e.g. "the verification of" → "verifying", "the preparation of" → "preparing" — which removes the buried-verb noun and its `-tion`/`-ment`/etc. suffix.
   - **Reduced-relative / passive stripping.** The phrase "that/which is|are|was|were|has been|have been|had been" is deleted, which also kills many embedded passives.
   - **Filler compression.** 12 wordy phrases are shortened, applied in list order — e.g. "in accordance with" → "per", "in order to" → "to", "for the purpose of" → "to", "with respect to" → "for". Some (e.g. "it shall be understood that") are deleted outright.
   - **Responsibility / inline-passive un-nesting.** "it is the responsibility of X that Y shall/must be Z-ed" is rewritten to "X <imperative(Z)> Y"; "it shall/must be <verb>ed that …" becomes "<imperative(verb)> that …".
   - **Ambiguity flagging** (see below) runs last, then whitespace is normalised.

3. **Sentence + clause splitting.** Each cleaned paragraph is split into sentences with the shared `split_sentences` helper (decimal- and abbreviation-aware; see Foundations), then each sentence is split further at clause boundaries: semicolons, and the connectors "whereby", "so that", "such that", "given that", plus an "and" that immediately precedes a "the/a/an/it … shall/must be" passive clause. This is what breaks run-on sentences and is the main driver of the reading-grade drop.

4. **Passive → imperative.** Each resulting clause with **at least 3 words** is turned verb-first where a pattern matches:
   - A clause left starting with a bare participle ("be labeled with …") is fixed to "Label …".
   - A "<subject> shall/must be <verb>ed" clause becomes "<imperative(verb)> the <subject> …" — but only when the subject is **10 words or fewer** (a guard against mangling long or unusual constructions). "It"/"this" subjects are dropped rather than kept.
   - Verb inflection is handled by a small stemmer: 15 hand-mapped irregular participles ("transferred"→"transfer", "utilized"→"use", "subjected"→"process", "understood"→"note", …), an "-ied"→"-y" rule, and an "-ed"→base rule that undoes doubled consonants and re-adds a trailing "e" for stems ending in at/iz/is/ur/… The clause is capitalised and given a period.

**The Anthropic (LLM) path is optional and did not run here.** A real API call is offered, but only when the environment variable `ANTHROPIC_API_KEY` is set. If it is, the flagship SOP — and only the flagship, consulted **once**, never inside the 40-document loop — is sent to Claude (default model `claude-opus-4-8`, overridable via `ANTHROPIC_MODEL`) with a system prompt that forbids dropping or inventing citations, cross-references, numeric parameters, or safety warnings and instructs it to mark vague spans `[DEFINE …]` rather than invent a spec. The call is defensively guarded: a missing key, a missing `anthropic` package, a refusal (`stop_reason == "refusal"`), a truncation (`stop_reason == "max_tokens"`), or any exception each returns `None` and **falls back to the rule-based engine with a warning** — a silent engine change would be untraceable in an audit. Which engine actually produced the text is recorded in the output (`"rule-based"` vs `"anthropic-api (<model>)"`). In this environment there is no key, so every document — flagship included — was rewritten by the rule-based engine.

The flagship's before/after bar chart is drawn with **matplotlib** (four panels: reading grade, estimated pages, ambiguous terms, passive constructs; "before" bars red, "after" bars green).

---

## The scoring  (the critical section)

### The four measured metrics

For any text, `_metrics` computes:

| Metric | Exactly how | Notes |
| --- | --- | --- |
| Reading grade (FK) | `textstat.flesch_kincaid_grade(text)`, rounded to 1 decimal | Primary success metric. Empty text → 0.0 |
| Estimated pages | word count ÷ **450.0**, rounded to 2 decimals | 450 words per page is the fixed assumption |
| Ambiguous terms | count of shared-lexicon matches on the text **after `[DEFINE …]` spans are stripped out** | This is *unresolved* ambiguity only |
| Passive constructs | `lexicon.count_passive(text)` on the **full** text | Measured including any `[DEFINE …]` markers |
| Words | tokens matching letters-and-apostrophes | Drives the page estimate; a 0 here forces an `n/a` status |

Two counts describe ambiguity, and the distinction is the heart of this module:

- **Flagged-for-SME** (`flagged_for_definition`) = the number of `[DEFINE …]` markers in the rewritten text, counted with the pattern `\[DEFINE\s+[a-z ]+:[^\]]*\]`. Each is an **explicit open item**: the rewriter has isolated a vague word, wrapped it, and told the SME *what kind* of measurable criterion to supply.
- **Unresolved ambiguous** (`ambiguous`) = lexicon matches with the `[DEFINE …]` spans removed first. A term that has been flagged is deliberately **not** counted as unresolved ambiguity — it is a tracked open item, not a lingering defect.

So the rewrite does **not** silently pick a value for "appropriate". It converts each vague word into `[DEFINE <hint>: <original word>]`, preserving the source wording so the flag is traceable. The `<hint>` says which of **7 criterion categories** the SME must fill in, chosen by which term matched:

| Hint category | Triggered by (examples) |
| --- | --- |
| criterion | appropriate, reasonable, acceptable, suitable, adequate, sufficient |
| method | appropriately, properly, adequately, sufficiently, as directed |
| frequency | as necessary, as needed, as required, periodically, regularly, routinely |
| trigger condition | if needed, if necessary, when required, where applicable |
| time limit | in a timely manner, as soon as possible, asap |
| tolerance | approximately, about, roughly |
| applicable cases | generally, typically, normally, usually |

A term with no explicit mapping defaults to the `criterion` hint.

### The per-SOP status rule (pass / warn / fail)

Let **drop = grade_before − grade_after**. With `MATERIAL_GRADE_DROP = 2.0` and `GRADE_TARGET = 12.0`:

- **pass** — if `drop ≥ 2.0` (the rewrite is credited as *materially* easier) **or** `grade_before ≤ 12.0` (the source already read at or below the plain-language target, so the rewrite is a polish, not a remediation).
- **warn** — otherwise, if `drop > 0` (some improvement, but less than 2.0 grades and starting above 12.0).
- **fail** — otherwise (`drop ≤ 0` and the source was above the Grade 12 target, i.e. no gain on a document that needed one).
- **n/a** — a separate case: if either before- or after-word-count is 0, the SOP has no rewritable prose body; it is reported, not dropped, and excluded from corpus means.

Note the asymmetry: a document that starts *below* Grade 12 is a **pass even if the rewrite makes it slightly worse**, because it was never the target of remediation. In this corpus SOP-WHS-001 (10.9 → 11.0) and SOP-WHS-002 (11.7 → 11.9) both went *up* slightly yet score pass on the `grade_before ≤ 12.0` clause.

### How the flagship is chosen (`_pick_worst`)

Deterministic, no random seed needed. For every English SOP the module takes three raw numbers from its **full text** (title + body): FK grade, ambiguous-term count, passive count. Each of the three lists is converted to a **z-score** — `(value − mean) / population-standard-deviation`, with the standard deviation replaced by 1.0 if it is zero. The three z-scores are summed with **equal weight** (`z_grade + z_ambiguity + z_passive`), and the SOP with the highest sum wins. Ties resolve by the sort's stability. This picks the document that is simultaneously the hardest to read, the vaguest, and the most passive relative to its peers.

### Corpus roll-up

- `sops_rewritten` = number of English SOPs processed.
- `sops_passing` = count with status `pass`.
- `corpus_grade_before` / `corpus_grade_after` = mean FK grade over the graded SOPs (status ≠ `n/a`), rounded to 1 decimal.
- `open_define_items` = sum of `flagged_for_sme` across all SOPs.

---

## How to read the result

- **Reading grade — lower is better.** A drop of 2.0 or more is the bar for "materially easier". Grade ~8–10 is a general audience; 13+ is college level. A high *after* grade (e.g. flagship 17.6) means the mechanical engine ran out of easy wins — legitimate technical vocabulary, not sentence structure, is now setting the grade, and a human writer is needed to go lower.
- **Estimated pages** — a proxy for length; it usually falls slightly as filler is compressed, but can tick up when clause-splitting adds sentence-ending periods and the `[DEFINE …]` markers add characters.
- **Ambiguous terms (after) → almost always 0.** That is *by design*: every matched vague word is wrapped as a `[DEFINE …]` marker and therefore leaves the *unresolved* count. Do not read "0" as "the vagueness is fixed" — read it as "every vague word has been converted into an open item to fix". The real work is now the **flagged-for-SME** number.
- **Passive constructs — lower is better**, and shows how much of the passive voice the imperative conversion actually removed.
- **Status:** `pass` = materially easier or already at target; `warn` = improved but not enough, still above Grade 12; `fail` = no gain where one was needed; `n/a` = nothing to rewrite.

Artifacts:
- `rewrite_metrics.png` — the flagship's four before/after bars (red = before, green = after).
- `before_after.md` — the flagship's full original vs. rewritten body, with the metric table and the engine used, so a reviewer can read the actual rewrite.
- `output/m06_rewriter/sops/<SOP-ID>.md` — one before/after file per SOP, each headed by its metric table and its count of `[DEFINE …]` open items.
- `rewrite_all_sops.csv` — one row per SOP: status and every before/after number, for sorting and triage.

A reviewer should treat the CSV as a worklist: `warn`/`fail` rows are documents the mechanical pass could not fix and that need a human rewrite; the `flagged_for_sme` column is the backlog of measurable criteria the SMEs must define.

---

## Worked example

**SOP-CLN-007** — selected as the flagship because its equal-weight sum of z-scored grade, ambiguity, and passive was the highest in the corpus (raw inputs: FK grade 25.7, 11 ambiguous terms, 60 passive constructs). It is a cleaning SOP written in the ALL-CAPS/`shall`/passive house dialect — exactly the profile the engine is built to attack.

Rule-based rewrite, before → after:

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| Reading grade (FK) | 25.7 | 17.6 | −8.1 |
| Estimated pages | 1.86 | 1.5 | −0.36 |
| Ambiguous terms (unresolved) | 11 | 0 | −11 |
| Passive constructs | 60 | 19 | −41 |

Tracing the numbers to a verdict:

- **drop = 25.7 − 17.6 = 8.1**, which is ≥ 2.0, so **status = pass** — the rewrite is credited as materially easier. (It is nowhere near the Grade 12 target, but it did not have to be; the material-drop clause alone earns the pass.)
- The 11 ambiguous terms did not vanish — they became **11 `[DEFINE …]` open items** (`flagged_for_sme = 11`), which is why the *unresolved* ambiguous count is 0. The SME now has a concrete, traceable list of 11 vague words to replace with measurable criteria.
- Splitting run-on sentences at semicolons and conjunctions is what cut the grade by 8 levels; converting "shall be <verb>ed" passives to imperatives is what took passive constructs from 60 to 19.
- Pages fell from ~837 words (1.86 × 450) to ~675 words (1.5 × 450) as filler was compressed.

At the corpus level the same engine took all **40** English SOPs from a mean FK grade of **15.6 → 13.1**, with **32/40 passing**, 8 in `warn`, and **190** `[DEFINE …]` open items raised for SMEs. For contrast, SOP-DOC-002 started at grade 7.7 and ended at 7.2 (drop 0.5, below the 2.0 bar) yet still scores **pass** — because it began below the Grade 12 target, so its finding explicitly reads "the rewrite is a polish, not a remediation."

---

## What it cannot see (limitations)

- **It is a rewriter, not a spec generator.** It never supplies a missing acceptance criterion — it can only *locate* vagueness and hand it to a human as a `[DEFINE …]` marker. The headline "ambiguous terms → 0" means "converted to open items", not "resolved". A reader who stops at the after-count will badly overstate what happened.
- **Flagged count can differ from the original ambiguity count.** The cleanup pass (filler compression, reduced-relative deletion) runs *before* the ambiguity flag, so it can expose or create a matchable vague word that was not present in the original prose. This is why some SOPs show more `[DEFINE …]` markers than their measured before-ambiguity — e.g. SOP-MFG-001 (before-ambiguity 9, flagged 10), SOP-QC-003 (3 vs 4), SOP-MFG-002 (0 vs 1). The markers are still traceable, but the two counts are not guaranteed to be equal.
- **The transforms are surface pattern-matching and can mangle meaning.** The passive→imperative rewrite fires only on subjects of 10 words or fewer and on a fixed set of participle inflections; a mis-stemmed verb or a wrongly-guessed subject can produce a grammatically odd or subtly wrong instruction. The output is a **draft for human review**, never a document to release as-is. Nothing in the pipeline verifies that the rewritten step still means what the original meant.
- **Reading grade is a surface formula (see Foundations).** It counts syllables and sentence length, not correctness. A rewrite can lower the grade while damaging accuracy, and a high *after* grade may simply reflect necessary technical terms. A material grade drop is evidence of *readability* improvement only.
- **Passive detection is a regex heuristic.** It will miss unusual passive constructions and can over-count adjectives that look like participles; the before/after passive numbers are a relative signal, not a grammatical ground truth. Some SOPs (e.g. SOP-EQP-002/003) show passive barely moving because their constructions fall outside the patterns the engine rewrites.
- **The 450-words-per-page figure is a fixed assumption**, not a measurement of the site's actual document template; the page numbers are indicative only.
- **The pass rule rewards a below-target starting point.** A document that begins at or below Grade 12 passes even if the rewrite makes it marginally harder to read — the status answers "did we hit the plain-language target", not "did this particular edit help every document".
- **The LLM path is inert in this environment.** The Anthropic call is fully guarded and honestly reported, but with no API key present it never ran; the flagship and all 40 SOPs were rewritten by the rule-based engine. Any audit claim about "LLM-assisted" rewriting must reconcile with the recorded engine string, which reads `rule-based` throughout this run.
