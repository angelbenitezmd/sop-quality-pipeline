# 02 — Topic Clustering (BERTopic-style)

**Question it answers:** Without anyone tagging them, what natural subject groups do the SOPs fall into — and which procedures are really the same document wearing different labels?

**Deck slide:** 16.

**Scope:** Corpus-wide. This module produces one view over the whole English corpus at once: a table of topics and a 2-D map. It does **not** score individual SOPs and writes no per-SOP file — a document's only "output" here is which topic number it landed in and where its dot sits on the map.

---

## The source: what it reads

This module is different from most of the pipeline: it does **not** consume the shared foundation signals (ambiguity, passive voice, readability, citations, style). Those signals measure *quality*; topic clustering measures *aboutness*. So it goes back to the raw text.

For every English SOP (`corpus.english()`, i.e. `language == "en"`) it reads `full_text` — the document's **title plus body** — and its `sop_id` and `title`. The Spanish translations are excluded so that a document and its translation don't form a spurious two-member "topic."

Before any counting, two kinds of text are scrubbed so they can't dominate the topics:

- **SOP-id cross-references** — every token matching `SOP-[A-Z]{2,4}-\d{3}(?:-[A-Z]{2})?` (e.g. `SOP-CLN-002`, `SOP-MFG-001-ES`) is replaced with a space. Otherwise two SOPs that merely cite each other would look topically related.
- **Boilerplate vocabulary** — 37 generic SOP words (`sop`, `procedure`, `shall`, `must`, `record`, `ensure`, `purpose`, `scope`, `qa`, `operator`, `review`, `version`, `table`, `form`, `log`, …) are added to sklearn's built-in `ENGLISH_STOP_WORDS` and dropped. These appear in *every* SOP, so leaving them in would blur every cluster toward the same grey centre.

Why the remaining bag of words is a defensible proxy for topic: once shared boilerplate and cross-reference codes are removed, what a procedure *repeats* is what it is *about*. A vial-filling SOP says "filling," "line," "aseptic" many times; a cleaning SOP says "cleanroom," "sporicidal," "mopping." Term frequency, weighted down for words that are common across the corpus, is the classic and auditable way to capture that.

---

## How it works

A four-stage pipeline modelled on the shape of BERTopic, but with **no neural embedding model** — every stage is a readable sklearn transform, so the result is deterministic and inspectable.

1. **TF-IDF term–document matrix** (`sklearn` `TfidfVectorizer`). Turns each SOP into a sparse vector of weighted term counts. Terms that are frequent in one document but rare across the corpus get the highest weight.
2. **TruncatedSVD** (`sklearn` `TruncatedSVD`) reduces that wide, sparse matrix to a small dense "latent semantic space" — this is the Latent Semantic Analysis step standing in for BERTopic's embedding + UMAP reduction. Documents that use overlapping vocabulary end up near each other even if they don't share every exact word.
3. **KMeans** (`sklearn` `KMeans`) partitions the documents in that latent space into a fixed number of topics.
4. **Labelling + map.** Each topic is named from its own most distinctive terms, and the whole set is drawn as a `matplotlib` scatter plot (first two SVD dimensions), one coloured dot per SOP.

Both the SVD and KMeans stages are seeded, so re-running on the same corpus always yields the same topics and the same picture.

---

## The scoring (the critical section)

There is no 0–100 score here — the "numbers" are the model's fixed parameters, the topic assignments, and the derived labels. Every constant below is lifted verbatim from the source.

### Stage parameters

| Stage | Parameter | Exact value |
|---|---|---|
| TF-IDF | `ngram_range` | `(1, 2)` — unigrams **and** bigrams (that is why labels like "filling line" and "isopropyl alcohol" appear) |
| TF-IDF | `min_df` | `2` — a term must appear in at least 2 documents |
| TF-IDF | `max_df` | `0.6` — a term appearing in more than 60% of documents is dropped as too common |
| TF-IDF | `token_pattern` | `[A-Za-z]{3,}` — alphabetic tokens of 3+ letters only (numbers and 1–2 letter tokens ignored) |
| TF-IDF | `sublinear_tf` | `True` — term frequency is dampened to `1 + log(tf)` so one word repeated 50 times can't swamp a document |
| TF-IDF | `stop_words` | `ENGLISH_STOP_WORDS ∪` the 37 domain-boilerplate words |
| SVD | `n_components` | `min(10, n − 1)` → with n = 40 documents, **10** latent dimensions |
| SVD | `random_state` | `42` |
| KMeans | `n_clusters` (k) | `min(8, n)` → with n = 40, **8** topics (`N_CLUSTERS = 8`) |
| KMeans | `random_state` | `42` (`RANDOM_STATE = 42`) |
| KMeans | `n_init` | `10` — KMeans is run 10 times from different seeds and the best inertia is kept |

So on the demo corpus: **40 documents → 2,102-term vocabulary → 10 SVD dimensions → 8 KMeans topics.**

### How a topic gets its label

For each topic, the module averages the TF-IDF vectors of only that topic's member documents, ranks the terms by that mean weight, and takes the **top 8**. Those 8 become the topic's `top_terms`; the **first 3** of them, joined with " / ", become the short `label`. The topic table also lists the first **4** member SOP ids as `example_sops`. Topics are then sorted **largest first** by member count.

There is no minimum topic size and no "outlier/-1" topic — KMeans assigns every document to exactly one of the k topics, so even a 2-member topic is reported.

### The two named "findings"

Two lightweight rules turn the raw clusters into the plain-English highlights on the slide. Neither is a score; each is a keyword-overlap count or a set test.

- **Equipment/Cleaning topic.** For each topic, count how many of its top-terms fall in a fixed 20-word equipment/cleaning list (`clean, cleaning, cleanroom, disinfect, disinfection, sporicidal, alcohol, sanitize, wipe, swab, autoclave, sterilizer, equipment, machine, filling, line, isolator, lyophilizer, wfi, maintenance`). The topic with the **highest** overlap count is flagged as the Equipment/Cleaning topic — but only if that overlap is at least 1.
- **Syringe vs Vial.** Collect the topic numbers of all SOPs whose *title* contains "syringe" and, separately, "vial." If the two sets **share** a topic number, the finding reads "co-cluster … near-identical line procedures differing mainly by container format." If they don't share one but both exist, it reports the split instead.

Two more lines are always appended — the largest topic (size and label) and a one-line summary of k and document count — and the whole findings list is capped at **6** entries.

### The map (2-D scatter)

- Projection is simply the **first two SVD components** — `x` = component 1, `y` = component 2. There is no separate 2-D embedding step; the picture is a literal slice of the same latent space KMeans clustered in.
- Marker area is fixed at `MARKER_SIZE = 68.0` points²; each topic uses the next colour from the shared 10-colour `CATEGORICAL` palette (`CATEGORICAL[cid % 10]`), with a darkened edge (each RGB channel × `0.6`).
- Axis limits pad the data by `0.075` on x and `0.06` on y.
- Because several SOPs land on nearly identical coordinates, a deterministic de-overlap pass (`_spread`) nudges coincident dots apart **in pixel space only**, capped so no dot drifts more than `0.75` of a marker diameter from its true position (relaxation runs up to 200 passes; exactly-coincident points are split along a golden-angle of `2.39996323` radians). This is cosmetic — it changes where a dot is *drawn*, never which topic it belongs to.
- One SOP id per topic is annotated: the member closest to that topic's centroid, placed by a greedy collision-avoidance search with leader lines where the label has to sit far from its dot.

---

## How to read the result

- **The topic table** (`table` in `summary.json`) is the main artifact. Each row is a discovered subject group: its `label`, its `size`, its 8 `top_terms`, and up to 4 example SOP ids. Read it top-down — the biggest topics are your corpus's dominant subject areas.
- **A topic whose members span several department codes** is the interesting case: it means procedures written by different teams are really about the same thing. That is a consolidation or harmonisation candidate.
- **`topics_scatter.png`** is the same information as a map. Tight, well-separated colour blobs mean cleanly distinct subject areas; two colours that interleave mean two "topics" that are barely distinguishable — often a sign the same procedure was duplicated with minor variation.
- **A reviewer should act on it** by treating each topic as a "did we mean to have this many near-duplicate procedures here?" prompt — not as a verdict. The module suggests groupings; a human confirms whether they should be merged, cross-referenced, or left alone.

---

## Worked example

Take **topic 2** from the demo run, verbatim from `summary.json`.

Its members are 4 SOPs — `SOP-CLN-001, SOP-CLN-003, SOP-CLN-004, SOP-CLN-005`. Averaging their TF-IDF vectors and taking the top 8 terms yields:

> cleanroom, cleaning, alcohol, isopropyl, isopropyl alcohol, mopping, sporicidal, surfaces

The first three, joined with " / ", become the label **"cleanroom / cleaning / alcohol."**

Now the Equipment/Cleaning rule runs. It strips the commas and splits those top-terms into a token set — `{cleanroom, cleaning, alcohol, isopropyl, mopping, sporicidal, surfaces}` (the bigram "isopropyl alcohol" splits into two words already present) — and intersects it with the 20-word equipment/cleaning list. Four terms match: **cleanroom, cleaning, alcohol, sporicidal → overlap = 4.** That is the highest overlap of any of the 8 topics, so topic 2 is named the Equipment/Cleaning cluster and the finding is emitted:

> "Equipment/Cleaning cluster 2 ('cleanroom / cleaning / alcohol'): 4 SOPs, e.g. SOP-CLN-001, SOP-CLN-003, SOP-CLN-004."

For the second headline, look at **topic 1** ("filling / line / filling line", size 9). The syringe-titled SOPs (`SOP-MFG-003` "Syringe Line", `SOP-PKG-003` "Syringe Product") and the vial-titled SOPs (`SOP-EQP-001`, `SOP-MFG-001`, `SOP-MFG-002`, …) both land in topic 1. Because their topic sets share the number 1, the module reports them as co-clustering — "near-identical line procedures differing mainly by container format." A number (a shared cluster id) has become an audit-actionable observation: the syringe-line and vial-line SOPs may be one procedure that was forked by container.

Finally the always-on lines report the largest topic — **topic 7, 11 SOPs, "analytical / performance / water"** (`rows[0]` after the size sort) — and the summary line "KMeans (k=8) over TF-IDF->SVD partitions 40 EN SOPs into coherent topics."

---

## What it cannot see (limitations)

- **k is fixed, not discovered.** The corpus is forced into exactly 8 topics (`min(8, n)`). If the true number of subject areas is 6 or 12, KMeans will still return 8 — splitting a real topic or fusing two. Topic count is a chosen parameter, not a finding, and the boundaries are only as meaningful as that choice.
- **Every document is assigned; there are no outliers.** Unlike true BERTopic, there is no "-1 / noise" topic. A one-off SOP that belongs to no group is still placed in its nearest topic and can distort that topic's label.
- **Labels are surface terms, not meaning.** A label is just the 3 highest-weighted words — including bigram artifacts (e.g. the "grade grade" label in topic 0) — so it can read oddly or over-emphasise a frequent-but-incidental word. It is a handle, not a summary.
- **The map is a 2-D shadow of a 10-D space.** Only the first two of the 10 SVD components are plotted. Two dots that look adjacent may be far apart in the other 8 dimensions, and vice-versa; the `_spread` de-overlap step further means a dot's exact pixel position is not its exact coordinate. Read topic *membership* (colour) as truth, and read *distance* only as a rough hint.
- **It measures aboutness, not quality.** Two SOPs can share a topic while one is excellent and one is unusable — this module says nothing about ambiguity, readability, or compliance. It also can't tell you *why* two procedures overlap or *whether* they should be merged; the "Syringe vs Vial" and "Equipment/Cleaning" findings are keyword-driven heuristics that flag candidates for a human to adjudicate, not conclusions.
- **The keyword lists are hand-curated and English-only.** The Equipment/Cleaning finding depends on a 20-word list and the Syringe/Vial finding on literal title substrings; a cleaning SOP titled without any listed word, or a translated corpus, would slip past these highlight rules even though the underlying clustering still runs.
