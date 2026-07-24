# Running modules individually

Every capability runs on its own with `--module <N>`. This is the fast loop: change
one thing, re-run one module in a second or two, look at its output — instead of
re-running all 13.

```bash
python3 -m sop_pipeline.cli run --module 5      # regulatory audit only
python3 -m sop_pipeline.cli run --module 05     # same thing; padding optional
```

**Both reports are still rebuilt.** A single-module run merges its fresh result with
the saved results of the other twelve, so `output/report/index.html` and the per-SOP
dossiers stay complete and consistent — you never end up with a half-empty dashboard.
(Corollary: on a clean checkout, run everything once before running modules singly,
or the other cards will be missing simply because they have never run.)

## Useful flags

| Flag | What it does |
|---|---|
| `--module N` | Run only capability N (`1`–`13`, zero-padding optional) |
| `--sops DIR` | Analyse a different corpus directory |
| `--quiet` | Suppress Python tracebacks on module failure |

```bash
python3 -m sop_pipeline.cli list                      # the 13 module names
python3 -m sop_pipeline.cli verify                    # self-test the install
python3 -m sop_pipeline.cli run --module 7 --sops data/sops_real
```

A bad number fails loudly and lists what is valid:

```
$ python3 -m sop_pipeline.cli run --module 99
No module matches number '99'. Available: ['m01_similarity', 'm02_topics', ...]
```

## The 13 capabilities

Runtimes are from the 42-document demo corpus; they scale with corpus size, and the
per-SOP modules scale roughly linearly with document count.

### Corpus-wide — one analysis covers the whole estate

These are relational: they compare documents against each other, so a single result
describes the set. No per-SOP output.

| # | Capability | Answers | Time | Output |
|---|---|---|---|---|
| 1 | Similarity | Which SOPs substantially overlap? | 1.6s | heatmap + `similarity_matrix.csv` |
| 2 | Topic clustering | What themes exist; what co-clusters that shouldn't? | 2.1s | cluster scatter |
| 4 | Dependencies | Orphans, cycles, broken links, hub docs | 0.8s | dependency graph |
| 8 | MinHash duplicates | Structural copy-paste between documents | 1.0s | ranked pair chart |
| 9 | Coverage gaps | Which topics are under- or over-documented? | 0.5s | coverage chart + CSV |

```bash
python3 -m sop_pipeline.cli run --module 1     # similarity
python3 -m sop_pipeline.cli run --module 4     # dependency graph
```

**Read module 4 first on a new corpus.** Broken cross-references and orphaned documents
are usually the fastest real findings, and if every SOP appears to reference *itself*,
your PDF conversion left page headers in the body — fix that before trusting anything else.

### Per-document — every SOP gets its own assessment

Each produces a corpus rollup **and** an entry per document, written to
`output/mNN_*/sops/` and surfaced in the per-SOP dossiers.

| # | Capability | Answers | Time | Per-SOP output |
|---|---|---|---|---|
| 3 | Readability | Can a floor operator actually read this? | 2.4s | grades per document |
| 6 | Rewriting | What would a clearer version look like? | 2.3s | before/after `.md` each |
| 7 | Quality scorecard | How good is this document, on 5 dimensions? | 2.9s | radar chart each |
| 10 | Visual aids | Can the procedure become a flowchart? | 3.2s | flowchart PNG + Mermaid |
| 11 | Style | Does it follow the house standard? | 0.6s | deviations per document |
| 12 | Multi-language | Do translations match the original? | 0.6s | discrepancies per pair |
| 13 | Training | Operator/supervisor/QA summaries, quizzes, job aids | 0.7s | training package `.md` each |

```bash
python3 -m sop_pipeline.cli run --module 7      # scorecard — the flagship deliverable
python3 -m sop_pipeline.cli run --module 13     # training packages
```

### Both levels

| # | Capability | Answers | Time | Output |
|---|---|---|---|---|
| 5 | Regulatory audit | Is every citation still current? | 0.5s | per-citation → per-SOP → corpus |

```bash
python3 -m sop_pipeline.cli run --module 5
```

Module 5 assesses each citation individually, rolls up per document, then corpus-wide.
It is the fastest capability and usually the most immediately actionable — outdated
citations are unambiguous findings with a clear remediation.

## Where the output lands

```
output/
  mNN_<name>/
    *.png *.csv          corpus-level artifacts
    summary.json         the module's full result (machine-readable)
    sops/                per-document artifacts, one set per SOP
  report/index.html      corpus dashboard (all 13)
  sops/index.html        per-SOP index, worst-first — the remediation queue
  sops/<SOP-ID>.html     one dossier per document
```

`summary.json` is the useful hook for scripting — it holds the same numbers the
dashboard renders:

```bash
python3 -c "import json; d=json.load(open('output/m05_regaudit/summary.json')); print(d['summary'])"
# {'sops_scanned': 40, 'references_extracted': 51, 'current': 44, 'outdated': 7, 'review': 0}
```

## Typical loops

**Tuning the regulatory table.** Edit `config/site_config.json`, then re-check in half a
second instead of re-running everything:

```bash
python3 -m sop_pipeline.cli run --module 5
open output/m05_regaudit/regaudit.csv
```

**Checking a fresh PDF conversion.** Dependencies first (catches leftover page
furniture), then readability (catches broken line-joining):

```bash
python3 -m sop_pipeline.ingest --pdf-dir raw_pdfs/ --out data/sops
python3 -m sop_pipeline.cli run --module 4
python3 -m sop_pipeline.cli run --module 3
```

**Everything, then browse:**

```bash
python3 -m sop_pipeline.cli run
open output/sops/index.html
```

A full run of all 13 takes about 10 seconds on 42 documents — so run individually while
iterating, and run everything before you actually review results.
