# SOP Quality Transformation Pipeline

Analyses a pharmaceutical SOP estate across **13 capabilities** — similarity, readability,
regulatory-citation currency, cross-reference integrity, coverage gaps, style conformance,
and more — producing a corpus dashboard plus an individual assessment for every document.
It implements the *AI-Powered SOP Quality Transformation & Lifecycle Management* proposal
(`SOP_Quality_Transformation_Pitch_Generic.pptx`).

**Point it at your own SOPs** — PDF or Markdown; see [Running it on your own
SOPs](#running-it-on-your-own-sops). A 42-document demo corpus ships in
`examples/mock_corpus/` (a fictional sterile fill-finish site) purely so the install can
be self-tested and the capabilities demonstrated before real documents are involved.

Runs fully offline. No API key required.

## Two levels of output

**Every SOP gets its own assessment.** A corpus average is not actionable when a reviewer
is remediating one specific procedure, so the pipeline produces both:

| Output | What it answers | Path |
|---|---|---|
| Corpus dashboard | How is the SOP estate doing? | `output/report/index.html` |
| **Per-SOP dossiers** | How is *this document* doing? | `output/sops/<SOP-ID>.html` |
| Per-SOP index | Which documents need work first? | `output/sops/index.html` |

Each dossier carries that SOP's own scorecard radar, readability grades, regulatory
citations, style deviations, rewrite before/after, flowchart, and training package — plus
a status of **Conforms / Review / Action required** rolled up from every capability. The
index lists all documents worst-first: that ordering is the remediation queue.

Capabilities split by scope. Relational analyses stay corpus-level because one view
genuinely covers the set; document-level analyses produce an assessment per SOP:

- **Corpus-wide** — similarity (m01), topic clustering (m02), dependency graph (m04),
  MinHash duplicates (m08), coverage gaps (m09)
- **Per-SOP** — readability (m03), rewriting (m06), scorecard (m07), visual aids (m10),
  style (m11), multi-language (m12), training (m13)
- **Both** — regulatory audit (m05): each citation assessed individually, then rolled up
  per SOP and across the corpus

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
git clone https://github.com/angelbenitezmd/sop-quality-pipeline.git
cd sop-quality-pipeline
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

python3 -m sop_pipeline.cli verify        # self-test the install on the demo corpus
```

`verify` runs all 13 capabilities against the bundled demo corpus. If it prints
*"the install is good"*, your environment is sound — check that **before** trusting
the pipeline on real regulated documents.

Requires Python 3.10+. Runs fully offline: no API key, no network access.

## Running it on your own SOPs

**1 — Configure the site.** Edit [`config/site_config.json`](config/site_config.json):
the regulatory version table (drives the citation-currency audit), the expected
coverage bands (drives the gap analysis), and your department codes. This is the one
file you must review before a real run — the defaults describe a fictional site.

**2 — Load your documents.** From PDFs (digital-native, exported from a DMS/Word):

```bash
python3 -m sop_pipeline.ingest --pdf-dir /path/to/pdfs --out data/sops
```

Check `data/sops/ingest_report.json` — anything marked `needs_review` should get a
human look before you trust its analysis. Already have Markdown? Drop it straight
into `data/sops/`.

**3 — Run.**

```bash
python3 -m sop_pipeline.cli run           # all 13 + both reports
python3 -m sop_pipeline.cli run --module 5    # just the regulatory audit
open output/report/index.html             # corpus dashboard
open output/sops/index.html               # per-SOP assessments, worst first
```

Any capability runs on its own with `--module N` (1-13) — the fast loop while tuning
config or checking a fresh PDF conversion. See
**[docs/RUNNING_MODULES.md](docs/RUNNING_MODULES.md)** for what each one answers, its
runtime, and where its output lands.

`data/sops/` is where your corpus goes and is **gitignored wholesale** — client
documents cannot be committed by accident. While it is empty the pipeline falls back
to the demo corpus, so a fresh clone runs immediately; the moment you add a file
there, your corpus takes over. `output/` is generated and rebuilt by every run.

## Running on another machine

The code contains no absolute paths — all paths derive from `PROJECT_ROOT` in
`sop_pipeline/core/corpus.py`, so a clone runs anywhere `requirements.txt` is installed.
Charts render headless (matplotlib `Agg`), so it works over SSH and in CI.

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
config/site_config.json    # EDIT THIS — regulatory versions, coverage bands, departments
data/sops/                 # YOUR corpus goes here (gitignored; empty -> demo is used)
examples/mock_corpus/      # bundled 42-SOP demo corpus + its ground_truth.json
sop_pipeline/
  core/corpus.py           # SOP/Corpus model, loader, section + sentence parsing
  core/lexicon.py          # ambiguity, passive voice, nominalization, style profiles
  core/regkb.py            # regulatory citation extraction + version currency
  core/viz.py              # shared chart palette
  ingest.py                # PDF -> Markdown conversion + quality report
  modules/m01..m13.py      # the 13 capabilities
  report.py                # corpus dashboard
  sop_report.py            # per-SOP assessment dossiers
  cli.py                   # orchestrator (run / verify / list / ingest)
tools/make_test_pdfs.py    # renders the demo corpus to realistic SOP PDFs (test fixture)
output/                    # generated: dashboards, per-SOP dossiers, charts, CSVs
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
