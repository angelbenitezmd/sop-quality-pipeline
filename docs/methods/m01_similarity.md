# 01 — SOP Similarity Analysis

**Question it answers:** Which SOPs in the corpus are near-duplicates or heavily overlapping, so the same procedure isn't maintained in three slightly different documents?

**Deck slide:** 15.

**Scope:** Corpus-wide. This module produces **one relational view of the whole English corpus** — a document-by-document similarity matrix — not a per-SOP score. There is no "grade" attached to any single SOP; the unit of analysis is the *pair* (and the cluster). The outputs are a heatmap, a full similarity matrix (CSV), a ranked table of the most-similar pairs, and a short list of overlap clusters.

---

## The source: what it reads

This module does **not** use the Foundation signals (ambiguity, passive voice, readability, citations, style). It works one level lower — on the **raw words** of each document.

- It reads each SOP's **`full_text`** — defined in the corpus loader as the document's **title plus body**, joined and stripped. Nothing else (no frontmatter, no manifest metadata) feeds the similarity math.
- It only considers **English SOPs** (`corpus.english()`, i.e. documents whose `language` is `en`). The two Spanish variants in the demo corpus (`SOP-CLN-001-ES`, `SOP-MFG-001-ES`) are excluded, which is why 40 documents are analysed out of 42 on disk.

**Why word-overlap is a defensible proxy for redundancy.** Two procedures that describe the same operation — "Manual Cleaning of Cleanroom A" vs. "…Cleanroom B" — reuse almost all of the same vocabulary, in the same phrasing, differing only in a room name or a unit ID. High shared-term overlap is therefore a direct, mechanical signal that two documents are saying nearly the same thing. It is content-based and fully traceable: every similarity number decomposes back into which shared words drove it. It is *not* a semantic model — it cannot tell that "sterilize" and "autoclave" are related unless the words themselves co-occur.

**One important honesty note carried through the whole card:** the group *names* you see in the output ("autoclave", "room_cleaning", "filling_line", "labeling") are **labels read from the corpus manifest's `near_duplicate_groups`**, not something the algorithm discovered. They exist only in the bundled mock corpus's `ground_truth.json`; a real corpus has none. The **detection** — the similarity number and which pairs cross the threshold — is real TF-IDF math and stands on its own. The manifest label only decorates a pair the math already found.

---

## How it works

1. **Order the documents by department.** The English SOPs are sorted by `(department, sop_id)` so that documents from the same area sit next to each other. This is what makes near-duplicate clusters land as contiguous bright blocks on the diagonal of the heatmap rather than being scattered.

2. **Vectorise with TF-IDF (`sklearn` `TfidfVectorizer`).** Each document's `full_text` becomes a vector of term weights. The vectoriser is configured with **English stop-words removed**, an **n-gram range of unigrams and bigrams** (single words *and* adjacent word pairs), and **`min_df=1`** (a term is kept even if it appears in only one document). TF-IDF up-weights terms that are distinctive to a document and down-weights terms common across the whole corpus, so shared *distinctive* phrasing counts for more than shared filler.

3. **Compute cosine similarity (`sklearn` `cosine_similarity`).** This produces the full 40×40 matrix of pairwise similarities, each between 0 (no shared weighted vocabulary) and 1 (identical vectors). Because TF-IDF is L2-normalised by default, cosine similarity here is the standard, well-understood measure. The self-similarity **diagonal is then forced to exactly `1.0`**.

4. **Rank the pairs and flag the high-overlap ones.** Every off-diagonal pair in the upper triangle is collected, sorted from most to least similar, and any pair at or above the redundancy threshold is flagged.

5. **Group flagged pairs into clusters (union-find).** The flagged pairs are treated as edges of a graph; connected components with more than one member become "overlap clusters" (e.g. all the room-cleaning SOPs that chain together into one group).

6. **Render (`matplotlib`).** The ordered matrix is drawn as a heatmap using the house sequential teal colour ramp, with the diagonal masked to neutral grey and department boundaries drawn as white separator lines.

The whole pipeline is **deterministic** — TF-IDF and cosine involve no randomness, so no seed is needed and the same corpus always yields the same matrix.

---

## The scoring (the critical section)

### The similarity number

- **Metric:** cosine similarity of TF-IDF vectors, range 0.0–1.0.
- **Vectoriser parameters (exact):**
  - `stop_words = "english"`
  - `ngram_range = (1, 2)` — unigrams **and** bigrams.
  - `min_df = 1`
  - `max_df` is **not set** in the code, so it stays at the scikit-learn default of `1.0` (no term dropped for being too common). There is likewise **no `max_features` cap** and **no dimensionality reduction** (no SVD / no `n_components`) — the full vocabulary is used. Lowercasing, the default token pattern, and L2 normalisation are scikit-learn defaults, not overrides.
- **Diagonal:** every document's similarity to itself is set to exactly `1.0` by construction (`np.fill_diagonal(sim, 1.0)`). The diagonal is not evidence of anything and is masked out of every reported number.

### The redundancy threshold

- **`HIGH_OVERLAP = 0.75`.** A pair is a "high-overlap" (redundant-candidate) pair when its cosine similarity is **≥ 0.75**. This single cut point is the only decision threshold in the module — there are no pass/warn/fail bands; a pair is either at/above 0.75 (flagged) or below it (not flagged).
- Pairs are taken from the **upper triangle only** (each unordered pair counted once) and **exclude the diagonal**.
- **`max_similarity`** reported in the summary is the largest off-diagonal pair similarity across the whole corpus.

### How clusters are formed

- Flagged pairs (≥ 0.75) are edges; **connected components** are found by **union-find**. Only components with **more than one member** are kept and reported as clusters. A cluster's reported range is the minimum and maximum *within-cluster* pairwise similarity.
- A cluster is labelled a **"`<name>` cluster"** (e.g. "autoclave cluster") only if a manifest group name exists **and every member shares that same group name**; otherwise it is labelled a generic **"Overlap cluster"**. (This is why a cluster that mixes a manifest-labelled duplicate with a merely-similar neighbour shows up as "Overlap cluster" rather than under a group name.)

### The interpretation tag on each pair

Each ranked pair gets a plain-language tag, decided in this order:

| Condition | Tag |
|---|---|
| Both SOPs are in the **same manifest near-duplicate group** | `Near-duplicate (<group name>)` |
| Otherwise, both SOPs are in the **same department** | `Same-department overlap` |
| Otherwise | `Cross-department overlap` |

Only the first tag depends on the manifest; the other two depend only on the department code, which comes from the SOP id. The similarity **number** is independent of all three.

### What each output contains

- **`similarity_matrix.csv`** — the complete 40×40 matrix, values formatted to **4 decimal places**, diagonal `1.0000`. Row/column labels are the short ids (e.g. `CLN-003`, the `SOP-` prefix stripped).
- **Ranked pair table** — the **top 12** pairs by similarity, each with the pair, similarity **rounded to 3 decimals**, and the interpretation tag.
- **`summary`** — three numbers: `documents_analyzed`, `high_overlap_pairs` (count at ≥ 0.75), and `max_similarity` (rounded to 3).
- **`key_findings`** — a headline count line plus one line per cluster, **capped at 6 lines total**. In these lines similarity ranges are printed to **2 decimals**.

### Heatmap rendering (display-only — affects no reported number)

These constants change only how the picture looks; the CSV, the pairs, and every reported figure are computed from the untouched matrix.

| Element | Exact value |
|---|---|
| Figure size | 10.0 × 9.0 inches |
| Colour ramp | house `SEQUENTIAL` teal ramp (`#EAF2F6` → `#0B3C5D`), light = low, deep = high |
| Colour scale | `vmin = 0.0`, `vmax = DISPLAY_VMAX = 0.80` (clipped just above the 99th percentile of real off-diagonal similarity so genuine clusters read clearly; the colour bar carries an "extend" arrow for values above 0.80) |
| Diagonal | masked and filled neutral grey `DIAGONAL_FILL = "#C8CFD4"` — "masked, not data" |
| Department dividers | white (`#FFFFFF`) lines where the department code changes between adjacent rows/columns, line width 1.0 |
| Colour-bar ticks | `0.0, 0.2, 0.4, 0.6, 0.8` |
| Redundancy marker | an **amber** line (`#E8833A`) drawn across the colour bar at **0.75**, i.e. the `HIGH_OVERLAP` flag |
| Axis tick label size | 6.5 pt (x-labels rotated 90°) |

Note the visual subtlety: the colour scale tops out at **0.80** for legibility, but the **decision threshold is 0.75** (the amber line). A block that looks "near the top of the scale" is at or past the redundancy flag.

---

## How to read the result

- **A high pair similarity (→ 1.0)** means two documents share almost all of their weighted vocabulary — they are very likely the same procedure with cosmetic substitutions (room letter, line number, unit ID). At/above **0.75** the module is explicitly flagging the pair as a redundancy candidate to review.
- **A low similarity (near 0)** means the documents share little distinctive language — expected for two unrelated procedures in different departments.
- **On the heatmap:** bright teal off-diagonal blocks, clustered inside a department's white-bordered square, are the redundancy story at a glance. A bright block that **straddles a white divider** would be a cross-department overlap and is worth a closer look. The grey diagonal is inert by design.
- **The CSV** is the audit-grade artifact: every pairwise number to 4 decimals, so any figure in the deck can be traced back to a specific cell.
- **Reviewer action:** for each flagged pair or cluster, decide whether the documents should be *consolidated* (one master SOP with an appendix of room/line specifics) or whether the near-duplication is genuinely justified. High overlap is a **prompt to consolidate**, not proof of a defect — two lines can legitimately need separate SOPs.

---

## Worked example

From the demo corpus (`output/m01_similarity/summary.json`): **40 English SOPs** were compared, yielding **9 high-overlap pairs at cosine ≥ 0.75**, with a **maximum off-diagonal similarity of 0.988**.

**The strongest pair — EQP-002 / EQP-003 (autoclave).** Their cosine similarity is **0.988** (top of the ranked table). Trace:

- Both documents are "Operation of Autoclave A / B (Sterilizer Load Configuration)" — the same procedure with the unit ID swapped. Nearly all their TF-IDF terms coincide, so the cosine sits at 0.988, just short of identical.
- 0.988 is **≥ 0.75**, so the pair is flagged as high-overlap.
- Both ids appear in the manifest group **`autoclave`**, so the interpretation tag is **`Near-duplicate (autoclave)`** — the manifest label decorating a pair the math already caught.
- Because both members share that group name, the cluster line is printed as an **"autoclave cluster"**, with its range shown to 2 decimals as **(0.99–0.99)**.

**A cluster that is *not* fully manifest-labelled — the cleaning group.** The high-overlap pairs among CLN documents chain together by union-find into one connected component: **CLN-001 / CLN-003 / CLN-004 / CLN-005**. Their within-cluster similarities span from **0.764** (CLN-001/CLN-004) up to **0.945** (CLN-003/CLN-004). CLN-003/004/005 are all in the manifest `room_cleaning` group, but **CLN-001 is not** — so not every member shares one group name, and the module labels the whole thing a generic **"Overlap cluster (0.76–0.94)"** rather than a "room_cleaning cluster". This is the labelling rule working exactly as written: the number-driven cluster is real, but the friendly group name is withheld because one member falls outside the manifest group.

So a reviewer reads: *nine redundant-candidate pairs; a two-document autoclave near-duplicate at 0.99 that is almost certainly one SOP written twice; and a four-document cleaning overlap cluster (0.76–0.94) where three room-cleaning SOPs are near-identical and a fourth general cleaning SOP sits close behind — all consolidation candidates.*

---

## What it cannot see (limitations)

- **It is lexical, not semantic.** Similarity comes from shared *words and word-pairs*, not shared *meaning*. Two SOPs that describe the same operation in genuinely different wording (synonyms, restructured steps, a translation) will score low. The Spanish variants are excluded entirely, so this module never detects an EN↔ES duplicate — that is a different module's job.
- **The threshold is a single hard line at 0.75.** A pair at 0.74 is invisible to the flag even though it is practically as overlapping as one at 0.76. The cut point is a deliberate, reviewable convention, not a law of nature; treat pairs just below it as worth a glance too (the full CSV shows them).
- **The group names are labels, not findings.** "autoclave", "room_cleaning", etc. come from the corpus manifest's ground-truth file, which only the demo corpus has. On a real corpus every flagged pair would be tagged only `Same-department overlap` or `Cross-department overlap` — the *detection* is unchanged, but the tidy names disappear. Do not read a group name as the algorithm having "understood" the topic.
- **High overlap is not automatically a defect.** Two filling lines or two cleanrooms may legitimately warrant separate SOPs. The module surfaces candidates; a human decides whether consolidation is actually appropriate and safe.
- **It can be fooled by boilerplate.** Documents that share large standard sections (identical safety preambles, identical GDP references) can read as more similar than their *procedural* content warrants. `min_df=1` with no `max_df` cap means even corpus-wide boilerplate contributes some weight. Conversely, a genuine duplicate padded with unique boilerplate could be pulled below the line.
- **The display scale is not the decision scale.** The heatmap colour clips at 0.80 for readability; the flag is at 0.75, and the true maximum (0.988 here) is compressed under the colour bar's "extend" arrow. Read the amber line and the CSV, not the apparent colour intensity, for the actual numbers.
- **The masked diagonal carries no information** — it is set to 1.0 and greyed out purely to keep the colour scale usable. It should never be read as a result.
