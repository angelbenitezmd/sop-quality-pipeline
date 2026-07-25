# 09 — Coverage Gap Analysis

**Question it answers:** For each regulatory topic area, does the site hold roughly the number of English SOPs a site of this type is expected to have — or is a topic missing, thin, or bloated?

**Deck slide:** 23.

**Scope:** Corpus-wide. The module produces **one verdict per topic area** (nine rows for the demo corpus), not a per-SOP score. It looks across the whole English inventory and asks a set-level question — "how many procedures cover each area?" — so its output is a single table and a single chart describing the corpus, with no assessment attached to any individual document.

---

## The source: what it reads

This module deliberately uses **none of the linguistic foundation signals** (ambiguity, passive voice, nominalizations, verb-first steps, readability, citations, style). Those describe the *quality of the prose inside* a document; coverage is a *counting* question about the document set, so it reads two things only:

1. **Document-level metadata, per SOP** — the **department code** (e.g. `CLN`, from the SOP-id prefix / YAML header) and the **language** (`en` vs the `-ES` translated variants). These are the corpus "observations" from the foundations doc, not the derived signals. The module counts how many English SOPs carry each department code. Translated (`-ES`) copies are excluded so a bilingual site is not double-counted.
2. **The expected-band table** from site configuration — `coverage_requirements.topics` in `config/site_config.json` (surfaced to the module as `corpus.manifest["coverage_requirements"]["topics"]`). Each entry pairs a topic area with a department code and an `expected_min`/`expected_max` count band.

**Why this is a defensible proxy.** A GMP site is expected to have documented procedures covering every regulated activity it performs. The simplest, most auditable evidence that an activity is governed is: *a procedure for it exists, and there is neither a conspicuous gap nor unmanaged sprawl.* Counting maintained SOPs per area against a pre-declared expectation is a direct, transparent proxy for "is this area documented at roughly the right depth?" — it makes no claim about how *good* those procedures are, only whether they are present in expected quantity.

---

## How it works

Step by step, in words:

1. **Fix the seed.** `random.seed(42)` is called for determinism. There is no stochastic step; it is an explicit guard so the run is reproducible.
2. **Count actuals per department.** Using Python's `collections.Counter`, the module tallies `department` over `corpus.english()` — i.e. every SOP whose language is `en`. This yields an actual SOP count for each department code.
3. **Walk the expected topics in config order.** For each topic in `coverage_requirements.topics`, it looks up that topic's department code in the counter (defaulting to `0` if the department has no English SOPs), reads `expected_min` and `expected_max`, and classifies the actual against the band (see The scoring).
4. **Roll up the corpus view.** It groups the topics into four status lists (over / under / absent / adequate) and computes summary totals.
5. **Draw the chart** with **matplotlib** — a horizontal bar per topic showing the actual count against a shaded expected-band strip (see the chart encoding below).
6. **Emit a machine-readable table** — `coverage.csv` via Python's `csv.DictWriter` — with one row per topic (`topic, dept, actual, expected_min, expected_max, status`), plus the same rows inside the returned `summary.json`.

No library does any inference here; the only "algorithm" is the four-way comparison of a count against a band.

---

## The scoring (the critical section)

### The expected bands (from `config/site_config.json`, verbatim)

These bands are **site configuration** — a human judgement about how many procedures each area warrants — not something the pipeline derives. They are the yardstick every verdict is measured against, so they are reproduced here exactly:

| Topic area | Dept | expected_min | expected_max |
|---|---|---|---|
| Cleaning & Disinfection | CLN | 3 | 4 |
| Equipment Operation & Qualification | EQP | 5 | 7 |
| QC Analytical Testing | QC | 5 | 7 |
| Aseptic Manufacturing | MFG | 5 | 7 |
| Environmental Monitoring | ENV | 4 | 6 |
| Packaging & Labeling | PKG | 4 | 5 |
| Warehouse & Materials | WHS | 5 | 7 |
| Document & Quality Systems | DOC | 4 | 6 |
| Dispensing & Weighing | DSP | 3 | 4 |

### The classification (the exact cut points)

Each topic's actual count is bucketed by this rule, **in this order** (order matters — the first match wins):

1. **absent** — `actual == 0`.
2. **over-documented** — `actual > expected_max`.
3. **under-documented** — `actual < expected_min`.
4. **adequate** — otherwise, i.e. `expected_min <= actual <= expected_max`.

Two things to hold onto:

- **Absent wins over under-documented.** Because the zero test comes first, a topic with a band of, say, 3–4 and an actual of `0` is labelled **absent**, not under-documented — even though `0 < 3` is also true. This is intentional (the code comment reads "Absent wins over under").
- **The band is inclusive on both ends.** A count exactly equal to `expected_min` or exactly equal to `expected_max` is **adequate**. Only `> max` or `< min` (or `== 0`) trips a flag.

### Status → color (how the chart paints each verdict)

The status maps to a fixed bar color drawn from the shared `viz` palette:

| Status | Meaning | Color constant | Hex |
|---|---|---|---|
| over-documented | redundant sprawl — consolidation candidate | `viz.BAD` (red) | `#C1442E` |
| under-documented | thin coverage | `viz.WARN` (amber) | `#E0A93B` |
| absent | missing topic — no SOP at all | `viz.WARN` (amber) | `#E0A93B` |
| adequate | count sits inside the band | `viz.GOOD` (green) | `#2E7D5B` |

Note the asymmetry the code encodes deliberately: **over-documentation is painted `BAD`/red and under/absent are painted `WARN`/amber.** In this framing a gap is a warning, whereas sprawl is treated as the "bad" (harder to remediate, more places for procedures to drift out of sync). *In practice* an absent topic never renders as an amber bar, because absent means `actual == 0` and no bar is drawn at zero width — it is shown instead as a red "0 — no SOP exists" pill (text color `viz.BAD` `#C1442E`, on a `#FAE8E4` rounded background). So the amber `WARN` color assigned to `absent` is effectively unused on the chart.

### The roll-up totals (what lands in `summary.json`)

- `topics_evaluated` = number of topics in the config band table (the row count).
- `english_sops` = total number of English SOPs in the corpus (`len(corpus.english())`).
- `over_documented`, `under_documented`, `absent` = the lists of topic names in each status.
- `adequate_count` = how many topics are adequate.
- `gaps_total` = `len(under_documented) + len(absent)` — **over-documented is NOT counted as a gap.**

There is **no numeric score and no pass/warn/fail band** for the corpus as a whole — the module reports status *per topic* and a gap tally, not a single rolled-up grade. `key_findings` lists at most **6** lines (absent topics first, then over, then under, then a closing "N of M topics fall below their expected coverage band" sentence, where N = absent + under).

### The chart encoding (exact geometry)

The figure is `9.5` wide by `0.62 × n + 2.2` tall (n = number of topics). Rows are drawn top-to-bottom in config order (`ylim` set to `n − 0.5 … −0.5`). For each topic row at height `bar_h = 0.52`:

- A **grey shaded strip** (`viz.GRID` `#DCE4E9`) spans horizontally from `expected_min` to `expected_max` — this *is* the expected band, drawn behind everything (zorder 1).
- A **solid colored bar** from 0 to `actual`, colored by status (drawn only when `actual > 0`, zorder 3).
- The band is **re-outlined** on top (`viz.MUTED` `#8A9BA8`, linewidth `0.9`, zorder 5) so the expected range stays visible even when a long over-documented bar covers it.
- **Absent rows** get the red "0 — no SOP exists" pill instead of a bar.
- A right-margin annotation prints `actual   (band min–max)` in ink (`#16232E`).

So the visual reading is: **bar ends short of the grey strip → under-documented; bar ends inside the strip → adequate; bar extends past the right edge of the strip → over-documented; no bar (red pill) → absent.** The x-axis is "Number of English SOPs on file," with integer ticks from 0 to the largest value drawn. The legend shows four keys: Expected band, Adequate, Under-documented, Over-documented.

---

## How to read the result

- **A green bar landing inside the grey strip** = adequate. No action; the area is documented at the expected depth. (This says nothing about whether those documents are any *good* — see limitations.)
- **An amber bar shorter than the strip's left edge** = under-documented. There are fewer procedures than expected for that area; a reviewer should ask whether a required procedure is missing or was mis-filed under another department.
- **A red bar running past the strip's right edge** = over-documented. More procedures than expected — a consolidation candidate. The finding text flags it as such, but the module does not check whether the extra documents are truly redundant (that is a similarity question, module 01).
- **A red "0 — no SOP exists" pill** = absent. The strongest finding: the site holds no English procedure for a regulated activity. This is the top of the `key_findings` list.

**Artifacts.** `coverage.png` is the chart above — the one-glance view for the slide. `coverage.csv` is the same nine rows in machine-readable form (`topic, dept, actual, expected_min, expected_max, status`) for filtering or import. `summary.json` carries the status lists and the `gaps_total` tally. A reviewer should act on absent topics first, then investigate under-documented areas for mis-filing, then treat over-documented areas as a housekeeping (consolidation) backlog.

---

## Worked example

Real numbers from the demo corpus (`output/m09_coverage/summary.json`): `topics_evaluated = 9`, `english_sops = 40`.

**Dispensing & Weighing (DSP) — absent.** Actual English SOPs = `0`; band = `3–4`. The classifier tests `actual == 0` first → **absent** (it never reaches the `0 < 3` under-documented test). On the chart, no bar is drawn; a red "0 — no SOP exists" pill sits at the origin. It is the first line of `key_findings`: *"ABSENT: Dispensing & Weighing (DSP) has 0 SOPs vs 3–4 expected — no documented procedure."* This single number — zero — is the module's highest-priority verdict.

**Cleaning & Disinfection (CLN) — over-documented.** Actual = `8`; band = `3–4`. `8 == 0`? no. `8 > 4`? yes → **over-documented**, painted red (`#C1442E`), the bar running four units past the right edge of the 3–4 grey strip. Finding: *"Over-documented: Cleaning & Disinfection (CLN) has 8 SOPs vs 3–4 expected — consolidation candidate."*

**Environmental Monitoring (ENV) — adequate (a boundary case).** Actual = `4`; band = `4–6`. `4 == 0`? no. `4 > 6`? no. `4 < 4`? no → falls through to **adequate**, because the band is inclusive at both ends. A count sitting exactly on `expected_min` still reads green. Its bar ends flush with the left edge of the grey strip.

**The roll-up.** Over = `[Cleaning & Disinfection]`; under = `[Warehouse & Materials, Document & Quality Systems]` (WHS: 3 vs 5–7; DOC: 3 vs 4–6); absent = `[Dispensing & Weighing]`; `adequate_count = 5` (EQP 6, QC 6, MFG 6, ENV 4, PKG 4). Therefore `gaps_total = len(under) + len(absent) = 2 + 1 = 3`, and the closing finding reads *"3 of 9 topics fall below their expected coverage band"* — note this **3** counts absent + under only; the over-documented Cleaning area is a finding but is **not** a "gap" and is **not** in that 3.

---

## What it cannot see (limitations)

- **It counts documents, not coverage of content.** "8 cleaning SOPs" could be eight genuinely distinct, high-quality procedures or eight overlapping fragments of one. The module reads only the tally against the band; whether those documents are redundant (module 01, similarity), well-written, or even about the right sub-topics is invisible to it. "Adequate" is a statement about *quantity*, never quality.
- **The bands are human judgement, and the analysis is only as right as they are.** `expected_min`/`expected_max` are hand-set site configuration. A wrong band produces a confident-but-wrong verdict (garbage in, garbage out). These numbers must be maintained and defended by a person; the module does not derive or validate them.
- **Topic = one department code.** The mapping assumes each regulatory topic corresponds to exactly one department prefix. If a department's SOPs actually span several topics, or one topic is split across departments, or a procedure is filed under the "wrong" department, the count is misattributed. It cannot see *which specific* procedures exist within an area — only how many carry that dept code.
- **"Over-documented" is a raw count, not a redundancy proof.** Flagging a "consolidation candidate" does not mean the extra documents duplicate each other; the module runs no similarity check. Confirming true redundancy requires module 01.
- **English-only.** Only `language == "en"` SOPs are counted; `-ES` translated variants are excluded. A procedure that exists solely in Spanish would read as absent or under-documented here.
- **Absent triggers only at exactly zero.** A band of 3–4 with a single SOP is "under-documented," not "absent" — the strongest flag is reserved for a literal count of 0. A near-empty area (1 of an expected 5–7) is amber, not red.
- **Departments not listed in the band table are invisible.** Any SOP whose department has no entry in `coverage_requirements.topics` is simply not evaluated — it contributes to `english_sops` but appears in no row. Coverage of an unlisted area is neither confirmed nor flagged.
- **It confirms presence, not compliance.** Having the expected number of procedures for an area is not evidence that those procedures are current, correct, or actually followed. A human still judges everything past "the right number of documents exist."
