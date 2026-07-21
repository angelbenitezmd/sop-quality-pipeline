# Module Authoring Contract

Every pipeline module lives at `sop_pipeline/modules/mNN_<name>.py` and exposes a
single `run(corpus, outdir)` function. The orchestrator (`cli.py`) imports and calls it.

## Required signature

```python
from pathlib import Path
from sop_pipeline.core.corpus import Corpus

def run(corpus: Corpus, outdir: Path) -> dict:
    ...
    return {
        "module": "m01_similarity",          # matches the file stem
        "title": "SOP Similarity Analysis",  # human title (match the deck slide)
        "slide": 15,                          # deck slide number this implements
        "summary": {                          # small dict of headline numbers/strings
            "documents_analyzed": 40,
            "high_overlap_pairs": 7,
        },
        "key_findings": [                     # 3-6 short bullet strings for the dashboard
            "High-overlap cluster (0.90-0.96): SOP-CLN-003 / 004 / 005",
        ],
        "artifacts": ["output/m01_similarity/heatmap.png"],  # paths RELATIVE TO PROJECT ROOT
        "table": [                            # OPTIONAL list-of-dicts rendered as an HTML table
            {"pair": "CLN-003 / CLN-004", "similarity": 0.94},
        ],
        "table_columns": ["pair", "similarity"],  # OPTIONAL explicit column order
        "scope": "corpus",                    # "corpus" | "per_sop" | "both"
        "per_sop": {...},                     # REQUIRED unless scope == "corpus" — see below
    }
```

## Per-SOP assessments (`scope` and `per_sop`)

**Every SOP needs its own assessment.** A corpus average is not actionable when a reviewer
is remediating one specific document. Each module declares its `scope`:

| `scope` | Meaning | Modules |
|---|---|---|
| `"corpus"` | Inherently relational — one view covers the set; no `per_sop` needed | m01 similarity, m02 topics, m04 dependencies, m08 minhash, m09 coverage |
| `"per_sop"` | Describes a single document | m03 readability, m06 rewriter, m07 scorecard, m10 visual aids, m11 style, m12 multilang, m13 training |
| `"both"` | Assess individually, then roll up | m05 regulatory audit |

Modules with scope `per_sop` or `both` MUST also return:

```python
"per_sop": {
    "SOP-CLN-001": {
        "summary": {"mean_grade": 18.4, "flag": "above Grade 12"},  # this SOP's numbers
        "findings": ["Reads at Grade 18.4 — 6 grades above the floor target."],
        "artifacts": ["output/m07_scorecard/sops/SOP-CLN-001.png"],  # per-SOP files
        "table": [...],                    # OPTIONAL rows scoped to this SOP
        "status": "fail",                  # OPTIONAL: "pass" | "warn" | "fail" | "n/a"
    },
    ...
}
```

Rules for `per_sop`:

1. **Cover every applicable SOP** — normally all of `corpus.english()`. If a document
   genuinely has nothing to assess (e.g. no numbered procedure to draw a flowchart from,
   no translated variant to compare), still include the entry with
   `"status": "n/a"` and a one-line finding explaining why. Never silently omit an SOP.
2. **Per-SOP artifacts go in `outdir/sops/`** (e.g. `output/m07_scorecard/sops/SOP-CLN-001.png`)
   so the module's top-level directory stays readable. Paths are still relative to project root.
3. **Keep the corpus-level keys too.** `summary`, `key_findings`, and the corpus chart
   remain — `per_sop` is additive, the rollup is still wanted.
4. `status` drives colour-coding in the per-SOP dossier; use it wherever a pass/fail
   judgement is meaningful.
5. **Watch the runtime.** Rendering one chart per SOP across several modules adds up —
   only emit a per-SOP image where it genuinely helps (a scorecard radar, a flowchart);
   text/table findings are enough elsewhere.

- `outdir` is your module's own directory, e.g. `output/m01_similarity/` — already created
  for you by the orchestrator. Write ALL files there.
- `artifacts` paths are **relative to the project root** (`output/mNN_.../file.png`), because
  the dashboard embeds them from the root. Compute them as
  `str(path.relative_to(PROJECT_ROOT))` or just build the string.
- Also write a machine-readable `outdir/summary.json` is NOT your job — the orchestrator
  saves your returned dict. But you MAY write extra CSV/JSON artifacts and list them.

## Available core APIs (read the files for full detail)

`from sop_pipeline.core.corpus import Corpus, SOP, Section, load_corpus, split_sentences, PROJECT_ROOT`
- `corpus` is iterable → yields `SOP`. `len(corpus)`, `corpus["SOP-CLN-001"]`, `corpus.get(id)`.
- `corpus.english()` → list of EN SOPs (exclude `-ES` variants for corpus-wide NLP).
- `corpus.by_department()` → `{dept_code: [SOP, ...]}`. `corpus.department_name(code)`.
- `corpus.manifest` → the full manifest dict (ground truth). `corpus.manifest_entry(id)`.
- `SOP`: `.sop_id .title .department .department_name .version .language .owner`
  `.effective_date .next_review .body .full_text .parent_id`
  `.sections` (list[Section] with `.heading .body .text .index`)
  `.sentences` (list[str]) `.words` (list[str]) `.cross_references` (list[str], self excluded).

`from sop_pipeline.core import lexicon`
- `lexicon.find_ambiguous_terms(text, spanish=False)` → list of matched vague terms.
- `lexicon.count_passive(text)`, `lexicon.count_nominalizations(text)`.
- `lexicon.sentence_starts_with_verb(sentence)`, `lexicon.STRONG_IMPERATIVES`.
- `lexicon.STYLE_PROFILES` (dict), `lexicon.HOUSE_STYLE` ("env_doc_standard"),
  `lexicon.modal_counts(text)`, `lexicon.detect_heading_style(headings)`.

`from sop_pipeline.core.regkb import RegKB, Citation`
- `kb = RegKB.from_manifest(corpus.manifest)`; `kb.extract(sop_id, text)` → list[Citation].
- `Citation`: `.canonical .as_written .status ("current"|"outdated"|"review"|"unknown")`
  `.current_version .action .topic`; `.as_row()`.

`from sop_pipeline.core import viz`  (matplotlib is preconfigured headless)
- `fig, ax = viz.new_fig(w, h)`; `viz.finish(ax)`; `viz.save(fig, path)`.
- Colors: `viz.PRIMARY viz.SECONDARY viz.TERTIARY viz.ACCENT viz.GOOD viz.WARN viz.BAD viz.MUTED`.
- `viz.SEQUENTIAL` (heatmap ramp list), `viz.CATEGORICAL` (series list), `viz.status_color(s)`.

## Rules

1. **Only create your own module file.** Never modify `sop_pipeline/core/*`, the manifest,
   `data/sops/*`, `cli.py`, or another module. If a core API seems missing, work within
   what exists.
2. **Deterministic.** Seed any randomness (`random_state=42`). No network calls, EXCEPT
   `m06_rewriter` may optionally call the Anthropic API guarded by
   `if os.environ.get("ANTHROPIC_API_KEY")` and MUST fall back to its rule-based path
   (there is no key in this environment, so the rule-based path is what actually runs).
3. **Use the manifest as ground truth** where helpful (e.g. near-duplicate groups, coverage
   requirements), but the *detection* should be real — compute similarity, parse refs, score
   readability from the text. The manifest is for labeling/validation, not for faking results.
4. **Every visual module writes at least one PNG** into `outdir` via `viz.save(...)` and lists
   it in `artifacts`. Charts must have titles, labeled axes, and use the `viz` palette.
5. **Self-test before finishing** by running:
   ```
   python3 -c "from pathlib import Path; from sop_pipeline.core.corpus import load_corpus, PROJECT_ROOT; \
     from sop_pipeline.modules.mNN_name import run; \
     o=PROJECT_ROOT/'output'/'mNN_name'; o.mkdir(parents=True, exist_ok=True); \
     import json; print(json.dumps(run(load_corpus(), o)['summary'], indent=2, default=str))"
   ```
   Fix any error until it prints cleanly and the PNG exists.
6. Keep it readable: module-level docstring, typed function, comments only where non-obvious.
   Aim for 60-160 lines.
```
