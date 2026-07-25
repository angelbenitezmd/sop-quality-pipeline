# 08 — MinHash Near-Duplicate Detection

**Question it answers:** Which SOPs are *structural* near-duplicates of each other — copy-pasted and lightly edited — even when TF-IDF cosine (m01) under-ranks them because the clones were reworded?

**Deck slide:** 22.

**Scope:** Corpus-wide. The module looks at the whole English SOP set at once and returns a ranked list of candidate *pairs*; it does not assign a score to any single SOP. The unit of output is the pair, not the document.

---

## The source: what it reads

This module does **not** consume the derived foundation signals (ambiguity, passive voice, readability, citations, style). It reaches one level below them, to the raw observation the foundations call **Words** — the ordered token list each SOP exposes (`re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+", body)`: letter/apostrophe tokens, accented Spanish letters included). It reads that word sequence for every SOP whose front-matter `language` is `en` (`corpus.english()`), and separately reads the manifest's `near_duplicate_groups` purely as an answer key to label its findings — the manifest never influences which pairs are detected.

**Why the ordered word list is a valid proxy for cloning.** Two procedures that were copy-pasted share long *runs* of identical wording in the same order, not just a shared vocabulary. By comparing overlapping windows of consecutive words (shingles) rather than a bag of terms, the module measures how much of one document's actual token sequence reappears verbatim in another. That is a direct, defensible signature of copy-paste lineage — the thing that creates change-control debt when one clone is updated and its siblings are not — and it is exactly what a bag-of-words cosine can miss when a clone is reworded.

---

## How it works

The library doing the work is **datasketch** (`MinHash`, `MinHashLSH`). Step by step:

1. **Shingling.** Each SOP's word list is lowercased and cut into overlapping **k = 5-word shingles** — every window of 5 consecutive words (`"the vial shall be inspected"`, then `"vial shall be inspected and"`, …). A document of *n* words yields *n − 5 + 1* shingles, held as a set (duplicates collapse). A document shorter than 5 words degenerates to a single shingle of its whole text, or the empty set if it has no words.

2. **MinHash sketch.** For each SOP a **MinHash signature of num_perm = 128 permutations** (`seed = 42`, so the permutations are identical on every run) is built by hashing each shingle. The 128-number sketch is a compressed fingerprint: the fraction of the 128 slots on which two sketches agree is an unbiased estimate of the true Jaccard overlap of their shingle sets.

3. **LSH blocking.** All 128-permutation sketches are inserted into a **MinHashLSH index tuned to threshold = 0.4**. LSH bands the sketches so that only pairs likely to exceed ~0.4 Jaccard land in the same bucket — a fast pre-filter that avoids comparing all pairs.

4. **Candidate query.** Every SOP is queried against the index; each returned neighbour (other than itself) becomes an unordered candidate pair (`frozenset`), de-duplicated.

5. **Exact-estimate + rank.** For each surviving candidate pair the module computes the MinHash Jaccard estimate directly (`minhashes[a].jaccard(minhashes[b])`, rounded to 4 decimals) and looks the pair up in the manifest group index to label it. Pairs are sorted by estimated Jaccard descending, then by pair name ascending as a deterministic tiebreak.

6. **Recall check + plot.** The module intersects its recovered pairs with the manifest's ground-truth near-duplicate pairs to report recall, then renders a horizontal **matplotlib** bar chart (`minhash.png`) of the top candidate pairs.

---

## The scoring (the critical section)

There is no composite score, no weighting, and no pass/warn/fail band in this module. Its numbers are all direct MinHash Jaccard estimates plus a set-membership label. Every constant:

| Parameter | Value | Role |
|---|---|---|
| `K` | **5** | Word-shingle length (5 consecutive words per window) |
| `NUM_PERM` | **128** | MinHash permutations; every Jaccard estimate is a multiple of 1/128 |
| `THRESHOLD` | **0.4** | LSH banding target — pairs likely above this are surfaced as candidates |
| `SEED` | **42** | Fixed permutation seed → identical sketches every run |

**How a pair's number is produced.** `est_jaccard = (number of the 128 sketch slots on which the two SOPs agree) / 128`, rounded to 4 decimals. So every value on the chart is one of 0/128, 1/128, …, 128/128. There are no caps, no scaling, and no combination step — the estimate *is* the reported number.

**How a pair becomes a candidate at all.** Membership is decided by LSH banding at `threshold = 0.4`, **not** by the estimate. LSH is approximate: a pair enters the candidate list if it shares at least one LSH band, which can happen for pairs whose true Jaccard sits somewhat below 0.4. This is why the module still reports each candidate's estimate afterwards — the estimate tells you how strong the surfaced pair really is, and some surfaced pairs land under 0.4.

**The `group` label (not a score, a cross-check).** Each candidate pair is looked up in an index built from the manifest's `near_duplicate_groups`: every unordered member-pair within a group maps to that group's name. A pair found there is labelled with the group name (e.g. `autoclave`); a pair not found is labelled `—`. This partitions candidates into two buckets:

- **manifest-confirmed** (`group != "—"`) — a known near-duplicate the detector was expected to catch.
- **unlisted structural echo** (`group == "—"`) — a pair the detector surfaced that the manifest did not pre-declare.

**Recall reporting.** `recovered = (all manifest near-dup pairs) ∩ (pairs LSH surfaced)`; the key finding states `recovered / expected` pairs across the count of distinct groups touched. This is a completeness measure of the detector against ground truth, not a quality score of any SOP.

**Chart encoding (`minhash.png`).** Top **12** pairs by estimate, horizontal bars; manifest-confirmed pairs in the house secondary teal, unlisted echoes in tertiary light teal; a dashed reference line is drawn at the LSH threshold **0.4** and captioned; each bar is annotated with its estimate to two decimals; highest estimate on top.

---

## How to read the result

- **A high estimate (toward 1.0)** means the two SOPs share most of their 5-word windows in the same order — strong evidence they descend from one template or one another. `EQP-002 / EQP-003` at 0.82 means roughly four-fifths of one's word-windows reappear in the other: treat as a genuine clone pair for change-control review.
- **A mid estimate (~0.4–0.7)** means substantial shared structure with real edits — a controlled family (shared boilerplate) or an incompletely diverged clone; judge by whether the shared runs are procedural steps or standard headers.
- **A low estimate that still appears (below the 0.4 line)** means LSH banding surfaced the pair on partial overlap; the estimate tells you it is a weak structural echo, not a clone. Read these as "shares some passages," worth a glance, not an alarm.
- **The `group` column** tells you whether the finding was already known (manifest-confirmed) or **newly surfaced** (`—`). The unlisted echoes are the most interesting output: structural similarity that a vocabulary-based cosine may have under-ranked.
- **Complementarity with m01.** m01 (TF-IDF unigrams+bigrams → cosine, redundant at cosine ≥ 0.75) rewards *shared vocabulary*; m08 rewards *shared word sequence*. Run them together: a pair high in both is unambiguous redundancy; a pair high in m08 but low in m01 is a reworded clone cosine missed; a pair high in m01 but not surfaced here is shared terminology/boilerplate rather than a copy-paste lineage.
- **Artifact.** `minhash.png` is the reviewer's one-glance view: bars above the dashed 0.4 line in the darker teal are the confirmed clone families; anything in light teal is an echo to triage.

---

## Worked example

From the demo corpus (`output/m08_minhash/summary.json`): **40 EN SOPs**, **9 candidate pairs**, **6/6** manifest near-duplicate pairs recovered across **4 groups** (100% recall).

Trace the top pair, **EQP-002 / EQP-003**:

1. Both SOPs are shingled into overlapping 5-word windows, MinHashed into 128-permutation sketches (`seed = 42`).
2. LSH (`threshold = 0.4`) places them in a shared band, so `EQP-003` is returned when `EQP-002` is queried → the pair `{EQP-002, EQP-003}` is recorded.
3. Their sketches agree on **105 of 128** slots → estimated Jaccard **105/128 = 0.8203**.
4. The pair is found in the manifest group index under **`autoclave`**, so it is labelled manifest-confirmed and drawn in house teal, well above the 0.4 line.
5. Sorted by estimate descending, 0.8203 is the largest value, so this pair is the reported `top_pair` / `top_jaccard`.

Now the contrast that shows why the estimate and the candidacy are separate. **CLN-001 / CLN-003** appears in the candidate list at estimated Jaccard **0.2812 (= 36/128)** with group **`—`**. LSH surfaced it — CLN-001 shares a band with the `room_cleaning` clone family (CLN-003 / CLN-004 / CLN-005, each confirmed at ~0.77–0.79) — yet its estimate sits *below* the 0.4 threshold line. Reading: CLN-001 is not a member of the cloned room-cleaning trio, but it reuses enough of their wording to echo them structurally. That is precisely the kind of partial reuse a reviewer wants flagged as a lead, and precisely why the module reports the estimate rather than trusting LSH membership as a verdict. The three unlisted echoes in this corpus are all CLN-001 against that trio (0.2812, 0.2812, 0.2734).

---

## What it cannot see (limitations)

- **It measures word-sequence overlap, not meaning or correctness.** Two SOPs can be near-identical in wording yet one carries a wrong setpoint; MinHash will call them near-duplicates and say nothing about which is right. Conversely, two procedures that are functionally equivalent but written independently will score low — the signal is lineage, not equivalence.
- **The 0.4 LSH threshold is a probabilistic pre-filter, not a guarantee.** LSH can surface pairs below 0.4 (false positives, as the CLN-001 echoes show) and can, in principle, miss a true pair that banded unluckily. The reported 100% recall is against *this* manifest on *this* corpus; it is not a mathematical promise for every corpus.
- **num_perm = 128 makes every estimate granular and slightly noisy.** Each value is a multiple of 1/128 (≈ 0.0078 resolution) and carries the sampling error of a 128-slot sketch — treat the two-decimal number as an estimate, not an exact Jaccard. Tied estimates (e.g. the two room_cleaning pairs both at 0.7891) are ordered only by pair name, so equal bars do not imply a real ranking between them.
- **k = 5 word shingles set the sensitivity floor.** Reordering or inserting words every few tokens breaks 5-word windows and lowers the estimate, so a heavily paraphrased clone can slip under the radar; very short SOPs (fewer than 5 words) collapse to a single shingle and cannot be compared meaningfully.
- **Shingling is lowercased and word-only.** Numbers-as-digits, punctuation, and formatting are stripped by the word tokenizer, so tables of distinct numeric values sharing a prose template can look more duplicative than they are, and case-based distinctions are invisible.
- **The `group` label is only as good as the manifest.** A pair labelled `—` is "not pre-declared," which is *not* proof it is a novel finding rather than a manifest omission — and a manifest-confirmed label does not certify the clone is a defect (some cloning is intentional, controlled boilerplate). A human still decides whether a surfaced pair is uncontrolled duplication or an accepted shared template, and which member is the source of truth.
