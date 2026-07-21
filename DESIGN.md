# SOP Quality Transformation Pipeline — Design

Reference: `SOP_Quality_Transformation_Pitch_Generic.pptx` (slides 15–26 = capabilities 1–12,
Phase 4 slide 13 = capability 13).

Fictional client: **Meridian Pharmaceuticals** — sterile injectable fill-finish site
(vials + pre-filled syringes), Building 4. All SOPs, people, and data are mock.

## Layout

```
data/sops/                  # mock SOP corpus (markdown + YAML frontmatter)
data/corpus_manifest.json   # authoring spec: every SOP + its seeded defects
sop_pipeline/
  core/corpus.py            # SOP dataclass, loader, section parser
  core/lexicon.py           # ambiguous terms, weak verbs, dept registry, style profiles
  core/regkb.py             # regulatory knowledge base (citation patterns + current versions)
  modules/m01..m13          # the 13 capabilities
  cli.py                    # orchestrator: python3 -m sop_pipeline.cli run [--module NN]
output/                     # all generated artifacts; output/report/index.html = dashboard
```

## The 13 capabilities

| # | Module | Deck slide | Core approach |
|---|--------|-----------|---------------|
| 1 | `m01_similarity` | 15 | TF-IDF + cosine similarity matrix, heatmap PNG, high-overlap cluster list |
| 2 | `m02_topics` | 16 | TF-IDF + SVD embedding, KMeans topic clusters, top-terms labels, 2-D scatter PNG (BERTopic-style; pure sklearn) |
| 3 | `m03_readability` | 17 | Flesch-Kincaid, Gunning Fog, Coleman-Liau per SOP (textstat), grade distribution PNG, %>Grade 12 |
| 4 | `m04_dependencies` | 18 | Regex/NLP extraction of `SOP-XXX-NNN` refs from body text, networkx digraph: orphans, cycles, broken links, hubs; graph PNG |
| 5 | `m05_regaudit` | 19 | Extract regulatory citations (CFR/ICH/EU GMP/USP/ISO/PDA), validate against `regkb` current-version table, status table CSV/MD |
| 6 | `m06_rewriter` | 20 | Rule-based simplification engine (sentence splitting, passive→active, ambiguity substitution, boilerplate trim) + optional Anthropic API; before/after metric panel |
| 7 | `m07_scorecard` | 21 | 5 dimensions: clarity, completeness, usability, consistency, defensibility → 0–10 scores, radar/bar PNG, corpus average |
| 8 | `m08_minhash` | 22 | datasketch MinHash + LSH over shingles, structural near-duplicate pairs, comparison vs cosine results |
| 9 | `m09_coverage` | 23 | Requirements matrix (regulatory topic → expected SOP count) vs actual per-category counts; over/under-documentation chart |
| 10 | `m10_visual_aids` | 24 | Parse procedure steps + decision sentences → flowchart (matplotlib-rendered) + Mermaid source per SOP |
| 11 | `m11_style` | 25 | Style profile detection per SOP (header style, verb-first %, shall/must/should mix, numbering), deviation report vs house standard |
| 12 | `m12_multilang` | 26 | Pair `-ES` variants with EN parents: section count diff, numeric value diff, decimal-format flags, missing-warning detection |
| 13 | `m13_training` | 13 | Role-based summaries (operator/supervisor/QA), quiz generation from steps/params, decision-tree text aids, per-SOP training package |

Every module implements:

```python
def run(corpus: Corpus, outdir: Path) -> dict
# returns {"module": "mNN_name", "title": ..., "summary": {...}, "key_findings": [str, ...],
#          "artifacts": [relative paths], "table": optional list-of-dicts}
```

`cli.py` runs modules in order, saves `output/mNN/summary.json` per module, then renders
`output/report/index.html` (self-contained dashboard, embeds PNGs base64, findings + tables).

## Seeded defect matrix (what the pipeline must catch)

Ground truth lives in `data/corpus_manifest.json`. Targets:

- **Near-duplicates**: CLN-003/004/005 (room-cleaning triplet ~90%), EQP-002/003 (autoclave pair),
  MFG-002/003 (filling line pair), PKG-002/003 (labeling pair).
- **Reading grade**: ~60% of corpus authored ≥ Grade 13 (matches deck's "62% exceed Grade 12").
- **Regulatory refs outdated**: EU GMP Annex 15 (2015→2022), ICH Q2(R1)→Q2(R2), EU GMP Annex 1
  (2008→2022), ISO 14644-1:1999→2015, ICH Q9→Q9(R1) — spread over ~8 SOPs; rest current.
- **Dependency graph**: hub = SOP-DOC-001 (referenced by 15+); cycle = SOP-QC-002 → SOP-MFG-004 →
  SOP-ENV-001 → SOP-QC-002; orphans = SOP-WHS-003, SOP-ENV-004; broken refs = SOP-CLN-099
  (cited by CLN-007) and SOP-VAL-001 (cited by MFG-006).
- **Style**: each department writes in a distinct profile (see `lexicon.py`); house standard =
  ENV/DOC style (verb-first, ## headers, "must").
- **Multi-language**: SOP-CLN-001-ES (IPA concentration 70%→60% discrepancy, decimal commas),
  SOP-MFG-001-ES (missing safety warning, section count mismatch).
- **Coverage**: Cleaning over-documented (8 SOPs vs 3 expected topics), Dispensing under-documented
  (expected but absent), Warehouse thin.
- **Ambiguity**: "appropriate", "adequate", "periodically", "as necessary", "if needed",
  "sufficient" — heavy in CLN/PKG/MFG.

## SOP file format

```markdown
---
sop_id: SOP-CLN-001
title: Cleaning and Disinfection of ISO 7 Cleanrooms
department: Cleaning & Sanitization
site: Meridian Pharmaceuticals — Building 4
version: "4.1"
effective_date: 2023-11-15
next_review: 2025-11-15
owner: J. Whitfield, Manager, Contamination Control
language: en
status: Effective
---

(body: numbered sections; cross-references and regulatory citations appear in prose and in a
Related Documents section — modules extract them from text, not frontmatter)
```

40 EN SOPs: CLN×8, EQP×6, QC×6, MFG×6, ENV×4, PKG×4, WHS×3, DOC×3. Plus 2 ES variants (42 files).
