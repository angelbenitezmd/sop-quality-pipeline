# SOP Quality Transformation Pipeline

A working reference implementation of the **13 capabilities** in the
*AI-Powered SOP Quality Transformation & Lifecycle Management* proposal
(`SOP_Quality_Transformation_Pitch_Generic.pptx`), run against a mock
pharmaceutical manufacturing SOP corpus.

**Client (fictional):** Meridian Pharmaceuticals — Building 4, a sterile injectable
fill-finish site (vials + pre-filled syringes). All 42 SOPs and their data are mock,
authored specifically to exercise the pipeline.

## The 13 capabilities

Each maps to a "Proven Capabilities" slide in the deck (Phase 4 = training, slide 13):

| # | Module | Deck slide | What it does |
|---|--------|-----------|--------------|
| 1 | `m01_similarity` | 15 | TF-IDF cosine similarity matrix + heatmap; finds high-overlap SOP clusters |
| 2 | `m02_topics` | 16 | Unsupervised topic clustering (SVD + KMeans), BERTopic-style |
| 3 | `m03_readability` | 17 | Flesch-Kincaid / Gunning Fog / Coleman-Liau; % over Grade 12 |
| 4 | `m04_dependencies` | 18 | Cross-reference graph: orphans, cycles, broken links, hub docs |
| 5 | `m05_regaudit` | 19 | Extracts & validates every regulatory citation vs current versions |
| 6 | `m06_rewriter` | 20 | Rule-based SOP simplification with before/after quality metrics |
| 7 | `m07_scorecard` | 21 | 5-dimension quality score (clarity, completeness, usability, consistency, defensibility) |
| 8 | `m08_minhash` | 22 | MinHash + LSH structural near-duplicate detection |
| 9 | `m09_coverage` | 23 | SOP coverage vs regulatory requirements; over/under-documentation |
| 10 | `m10_visual_aids` | 24 | Auto-generated flowchart (+ Mermaid) from SOP procedure text |
| 11 | `m11_style` | 25 | Per-department style detection vs the house standard |
| 12 | `m12_multilang` | 26 | EN/ES variant comparison: value, format, and structure discrepancies |
| 13 | `m13_training` | 13 | Role-based summaries, quizzes, and job aids from SOP text |

## Quick start

```bash
git clone <your-repo-url> && cd "SOP Project"
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

python3 -m sop_pipeline.cli list          # show discovered modules
python3 -m sop_pipeline.cli run           # run all 13 + build the dashboard
python3 -m sop_pipeline.cli run --module 05   # run just the regulatory audit
open output/report/index.html             # the results dashboard
```

Requires Python 3.10+. Runs fully offline — no API key and no network access needed.
`output/` is generated and gitignored; every artifact is rebuilt by `run`.

## Running on another machine

The code contains no absolute paths — all paths derive from `PROJECT_ROOT` in
`sop_pipeline/core/corpus.py`, so a clone runs anywhere `requirements.txt` is installed.
Charts render headless (matplotlib `Agg`), so it works over SSH and in CI.

## Using a real SOP corpus

The 42 SOPs in `data/sops/` are **mock data** written to exercise the 13 capabilities.
To run against real documents:

1. Convert the real SOPs to Markdown with YAML frontmatter matching the format in
   `data/sops/SOP-DOC-001.md` (required keys: `sop_id`, `title`, `department_code`;
   recommended: `version`, `effective_date`, `next_review`, `owner`, `language`).
   Cross-references and regulatory citations are extracted from the **body text**, so
   they only need to appear in prose — no tagging required.
2. Put them in their own directory (e.g. `data/sops_real/`, which is gitignored) and point
   the pipeline at it:
   ```bash
   python3 -m sop_pipeline.cli run --sops data/sops_real
   ```
3. Review `data/corpus_manifest.json`. It supplies two things the pipeline reads as
   configuration rather than ground truth: `regulatory_current_versions` (the version
   currency table used by the regulatory audit) and `coverage_requirements` (expected SOP
   counts per topic area). Update both for the real site. The `sops` array is mock-corpus
   ground truth used for validation and can be ignored or emptied.

**Do not commit client SOPs.** `data/sops_real/` and `data/sops_client/` are gitignored.

Known gaps for real-world use: ingest is Markdown-only (PDF/DOCX conversion is not built in).

## Optional: enabling the LLM rewrite path (`m06`)

The pipeline runs **fully offline with no API key**. The only module that can call an API
is `m06_rewriter`, and only when you opt in:

```bash
pip install anthropic                 # not in requirements.txt by default
export ANTHROPIC_API_KEY=sk-ant-...   # the pipeline reads the environment
python3 -m sop_pipeline.cli run --module 06
```

`ANTHROPIC_MODEL` overrides the model (default `claude-opus-4-8`). See
[.env.example](.env.example) for the full list of variables — note that a `.env` file is
**not** auto-loaded; either `export` the variables or use a loader such as `direnv`.

**Never commit a key.** `.env` and `.env.*` are gitignored; only `.env.example` is tracked.

How failure is handled matters for an audit trail: if the key is missing, the `anthropic`
package isn't installed, the model declines, the response would be truncated, or the call
errors, `m06` emits a warning, falls back to the rule-based engine, and reports the engine
that **actually ran**. A silent fallback is never recorded as an LLM rewrite.

## Layout

```
data/
  corpus_manifest.json     # ground truth: every SOP + its seeded defects
  sops/*.md                # 42 mock SOPs (Markdown + YAML frontmatter)
sop_pipeline/
  core/corpus.py           # SOP/Corpus data model + loader + section/sentence parsing
  core/lexicon.py          # ambiguity, passive-voice, nominalization, style profiles
  core/regkb.py            # regulatory citation extraction + version currency KB
  core/viz.py              # shared matplotlib palette/helpers
  modules/m01..m13.py      # the 13 capabilities
  report.py                # self-contained HTML dashboard renderer
  cli.py                   # orchestrator
output/
  mNN_*/…                  # per-module artifacts (PNGs, CSVs) + summary.json
  report/index.html        # the dashboard
```

## Seeded defects (what the pipeline is designed to catch)

The corpus deliberately contains: four near-duplicate groups (room-cleaning triplet,
autoclave pair, filling-line pair, labeling pair); ~60% of SOPs above Grade 12
readability; several outdated regulatory citations (EU GMP Annex 15 2001, ICH Q2(R1),
ICH Q9, ISO 14644-1:1999, GAMP 5 1st Ed, EU GMP Annex 1 2008); a dependency cycle
(QC-002 → MFG-004 → ENV-001 → QC-002), two orphan SOPs, two broken cross-references
(SOP-CLN-099, SOP-VAL-001); five distinct department writing styles; a coverage gap
(no dispensing/weighing SOP, cleaning over-documented); and two Spanish variants with
content/format discrepancies. See `data/corpus_manifest.json` for the full ground truth.

## Guardrails (per the deck)

AI **suggests**; humans **decide**. The rewriter (`m06`) proposes changes with a full
before/after metric panel and preserves the original text; nothing is auto-applied.
Every module is deterministic and traceable to the source SOP text.
