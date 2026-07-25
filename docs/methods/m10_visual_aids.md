# 10 — AI-Generated Visual Aids

**Question it answers:** Can this SOP's numbered procedure be turned automatically into a top-down flowchart — process boxes for the steps and a decision diamond for every conditional — so an operator sees the flow instead of reading pages of prose?

**Deck slide:** 24.

**Scope:** Both. There is one corpus-wide **flagship** flowchart (the single procedure chosen to showcase the capability on the slide), *and* a **per-SOP** sweep that attempts its own flowchart for every English SOP under `output/m10_visual_aids/sops/`. The top-level `summary` block reports the flagship; the `per_sop` block reports all 40 documents.

---

## The source: what it reads

Unlike most modules, m10 does **not** consume the derived quality signals (ambiguity, passive voice, readability, citations, style). It is a structural transform, not a scorer, so it reads the SOP body almost raw:

- **Raw body lines.** The step parser works directly on `sop.body` split into lines, so it recognises numbered lists under *any* heading dialect — markdown `##`, ALL-CAPS, or bare Roman-numeral headings. This deliberately sidesteps the shared **Section** splitter from the foundations, which misses Roman-numeral headings; the module re-finds the heading itself by walking up from the first numbered item.
- **The numbered-step structure.** The one text feature it depends on is the existence of a genuine `1. … 2. … 3. …` (or `Step 1: …`) list. That list *is* the procedure; everything else in the document is ignored for drawing purposes.
- **`split_sentences`** from `sop_pipeline/core/corpus` — reused only inside decision detection, to scan a step for a mid-sentence conditional.

Why these are valid proxies: a numbered, sequential list of imperative steps is exactly the shape that maps one-to-one onto a flowchart spine, and an "If … , …" clause is exactly the shape that maps onto a branch. When those shapes are present the diagram is *derived* from the text, not invented; when they are absent (narrative prose, bullet lists) the honest answer is "not drawable", which is why such documents are reported `n/a` rather than forced into a fabricated chart.

---

## How it works

**1. Find the procedure block.** `_numbered_blocks` scans the body line by line with the numbered-step pattern `_NUM_RE`, which matches either `Step N.` / `Step N:` / `Step N)` (case-insensitive on "Step") **or** the plain `N.` form (note: the plain form requires a trailing period — `N)` and `N:` are only accepted after the word "Step"). Rules used while grouping lines into a block:
- The first numbered item remembers the **nearest non-blank line above it** as its section heading.
- An **indented** non-numbered line is treated as a wrapped continuation and appended to the previous step's text.
- An **unindented** prose line ends the block.
- A **blank line** ends the block *unless* the next non-blank line is another numbered item.

`_best_procedure` then returns the **longest** numbered block (most items) as "the procedure", or `("", [])` if there are none.

**2. Detect decision points.** For each step, `_decision_parts` tries to split it into a `(condition, action)` pair:
- First it tries the house-style form directly with `_COND_RE`: `If <cond>, <action>` or `If <cond> then <action>` (the leading cue may be `if`, `when`, `whenever`, or `unless`).
- If that fails, it scans the step's sentences (`split_sentences`) for any decision cue word `_DECISION_RE` = **`if`, `when`, `unless`, `whenever`, `in the event`, `should any`**. A mid-sentence `, if <cond>, <action>` is split the same way; a trailing form like `<action> whenever <cond>` puts the condition after the cue and recovers the governing action from the clause before it (trimming coordinated commentary with `_COORD_RE` and the last conjoined verb phrase with `_ACTION_TAIL_RE`).
- Both clauses must be **substantive** or the step is treated as an ordinary process step (see scoring).

**3. Render two artifacts.**
- **matplotlib PNG** (`matplotlib.patches`): a vertical spine — a START terminator, one rounded box per step, an END terminator — with any decision drawn as an amber diamond that branches "Yes" right to a red out-of-spec box and "No" straight down the spine. The legend ("Key") lists only the shapes actually drawn. All styling comes from the shared `viz` palette.
- **Mermaid source** (`flowchart TD`): the same graph as portable text a QMS or wiki can embed. Node ids follow **position** (`S1`, `S2`, …; decisions `D{i}` with out-of-spec `O{i}`; end `ENDN`), not the printed step number, so a document that restarts its numbering never collapses two steps onto one node.

**4. Pick the flagship.** `_select_target` ranks all English SOPs and keeps the single best one to feature (see scoring).

---

## The scoring  (the critical section)

This module produces counts and a status, not a 0–100 score. Every number below is lifted from the code.

### The MIN_STEPS gate and the n/a rule

`MIN_STEPS = 3`. A procedure with **fewer than 3** parsed numbered steps is not drawn. `_assess` returns `status: "n/a"` with `steps`, `decisions: 0`, `pages_replaced_est: 0`, and a finding explaining why:
- if `steps` is 1 or 2 → "only N numbered step(s) could be parsed";
- if `steps` is 0 → "the document is written as narrative prose and bullet lists under topic headings, with no numbered step sequence".

A parse that raises an exception is also downgraded to `n/a` (the sweep never aborts).

### Decision detection thresholds

A candidate `(condition, action)` pair is only accepted if **both** clauses pass `_substantive`:

| Test | Constant |
|---|---|
| Minimum clause length | `len(clause) >= 12` characters |
| Minimum clause words | `len(clause.split()) >= 3` words |

Clause length caps used when extracting the pair: **condition capped at 66 characters, action capped at 84 characters** (`_clause(cond, 66)`, `_clause(action, 84)`). A cue word with no real clause behind it (e.g. "…when tested") fails `_substantive` and the step stays a plain process box.

### Pages-replaced estimate

`_pages_replaced(steps, decisions)` = `max(1, ceil((len(steps) + len(decisions)) / 4))`.

The divisor is **4** — the code's stated assumption of "~4 numbered steps per printed page" once cautions, acceptance lines and sign-offs are included. Note the decision steps are **double-counted**: they appear once in `len(steps)` (the total step count) and again in `len(decisions)` (the branch count), so a branchy procedure is estimated to fill slightly more prose. The result is floored at 1 for any drawable procedure.

### Status bands

| Status | Set when |
|---|---|
| `pass` | Both artifacts were written — `len(artifacts) == 2` (PNG **and** Mermaid) |
| `warn` | A drawable procedure produced only one artifact (a render or export failed) |
| `n/a` | Fewer than `MIN_STEPS` steps parsed, or the parse raised |

### Flagship selection (`_select_target`)

Among English SOPs with at least `MIN_STEPS` steps, each is keyed by the tuple and sorted **descending**:

`(explicit, decisions > 0, len(steps), sop_id)`

- **`explicit`** — True if any step *begins* with the house-style `If <cond>, <action>` form (`_COND_RE.match` on the whole step). This ranks first: an explicit written branch is the cleanest thing to draw.
- **`decisions > 0`** — True if any decision point was detected at all.
- **`len(steps)`** — more steps wins.
- **`sop_id`** — final tie-break; keyed as `[-ord(c) for c in id]` under a reverse sort, which resolves to the **lowest** id.

The determinism seed is set at import (`random.seed(42)`), though the module has no stochastic path — selection and layout are fully deterministic.

### Colours / shapes (from the shared `viz` palette)

| Shape | Meaning | Colour |
|---|---|---|
| Rounded box | Process step | `PRIMARY` `#0B3C5D` |
| Amber diamond | Decision point | `ACCENT` `#E8833A` |
| Box (right of diamond) | Out-of-spec / "Yes" action | `BAD` `#C1442E` |
| START terminator | Section start | `SECONDARY` `#1C7293` |
| END terminator | Section complete | `GOOD` `#2E7D5B` |

`_mermaid_clean` makes labels safe inside quoted Mermaid nodes: `"`→`'`, `±`→`+/-`, newline→space, and crucially `<`→`#60;` / `>`→`#62;` so a compendial reference like `USP <85>` is not swallowed as an HTML tag.

---

## How to read the result

- **`flowcharts_generated` vs `no_numbered_procedure`** (corpus level) tells you what fraction of the corpus is *already written as a step sequence*. A high `n/a` count is not a defect verdict — it flags documents written as prose/bullets that a human might consider restructuring into numbered steps.
- **`decisions`** per SOP tells you how many conditional branches the procedure contains. Zero means a straight-through spine; more than zero means the operator has genuine decision points that a wall of text would hide.
- **`pages_replaced_est`** is a rough "how much reading does one visual aid replace" figure at ~4 steps/page — a communication metric for the value of the conversion, not a quality score.
- **Artifacts.** For each converted SOP: a **`.png`** (the rendered flowchart, for review/print) and a **`.mmd`** (Mermaid `flowchart TD` source, for embedding in a QMS/wiki). Corpus level adds `flowchart.png` + `flowchart.mmd` (the flagship) and `coverage.png` (a per-department stacked bar of converted vs `n/a`).
- **Reviewer action.** Read the diagram against the source text: confirm the decision diamond's condition and its Yes/No routing match the SOP's intent, and confirm no step was dropped or mis-merged. The chart is a draft aid to be verified, not an approved controlled document.

---

## Worked example

**SOP-QC-006 — "Daily Verification"** (the flagship; `summary` block).

Its longest numbered block has **6 steps** under the heading "Daily Verification". Steps 1–5 are plain imperatives ("Confirm that the balance is level…", "Handle reference weights…", "Place a low-range and a high-range reference weight…", "Record each displayed value…", "Confirm that each reading is within ±0.1%…"), so each becomes a `PRIMARY` process box.

Step 6 reads: *"If a reading is out of tolerance, remove the balance from service and notify the QC…"*. Because it **begins with "If"**, `_COND_RE` matches directly:
- condition = "a reading is out of tolerance" — 29 characters, 6 words → passes `_substantive` (≥12 chars, ≥3 words);
- action = "remove the balance from service and notify the QC…" → also substantive.

So `_decision_parts` returns a pair, and step 6 is drawn as an **amber diamond** captioned "A reading is out of tolerance?" with a **Yes** branch to a red out-of-spec box ("Remove the balance from service…") and a **No** branch continuing to the END terminator. This is exactly why SOP-QC-006 wins the flagship ranking: it is `explicit = True` with `decisions > 0` and 6 steps.

Numbers, traced:
- `steps = 6`, `decisions = 1`.
- `pages_replaced_est = max(1, ceil((6 + 1) / 4)) = ceil(1.75) = 2`.
- Two artifacts written → `status = "pass"`.

These match the summary exactly: `SOP-QC-006 → steps 6, decisions 1, pages_replaced_est 2`.

**Corpus roll-up** (all 40 EN SOPs): `flowcharts_generated = 34`, `no_numbered_procedure = 6` (the four PKG SOPs plus SOP-WHS-002 and SOP-WHS-003, all prose/bullet documents), `corpus_pages_replaced_est = 68`, and 10 decision points recovered across the corpus. Contrast SOP-CLN-006 (only 3 steps, 1 decision → `pages_replaced_est = ceil(4/4) = 1`) with SOP-EQP-004 (6 steps, 3 decisions → `pages_replaced_est = ceil(9/4) = 3`).

---

## What it cannot see (limitations)

- **Structure only, never meaning.** The module confirms a procedure is *shaped* like a flowchart; it does not check that the steps are correct, complete, in the right order, or that the branch routes to the right action. A perfectly drawn diagram of a wrong procedure looks just as clean.
- **`n/a` is not a quality judgement.** Six documents are reported `n/a` purely because they lack a numbered list. A well-written prose SOP and a genuinely defective one both land in `n/a` — the signal is "no step sequence to draw", nothing more.
- **Regex decision detection is approximate.** Branches are found only through the fixed cue set (`if`, `when`, `unless`, `whenever`, `in the event`, `should any`) plus the `If …, …` shape. A conditional phrased differently ("Otherwise, quarantine the lot") is missed; a sentence that merely *contains* a cue word can be mis-split. The 12-character / 3-word substantive floor and the 66/84-char clause caps mean some real conditions are dropped as too short and long conditions are truncated with an ellipsis.
- **Only the longest block is drawn.** `_best_procedure` keeps a single, longest numbered list. An SOP with two procedures, or with the real procedure written as a shorter list than an incidental one, will have the other list ignored.
- **Multi-branch / rejoin geometry is simplified.** Every decision is drawn as one Yes→out-of-spec / No→continue pattern; nested conditions, loops, and parallel paths are flattened into that single spine-plus-side-box model.
- **The pages-replaced figure is a heuristic.** The ÷4 (and the double-count of decision steps) is a stated convenience assumption for communicating value on the slide, not a measured property of the source document.
- **A human still decides.** The output is a draft aid: a reviewer must verify the diagram against the SOP before it is used on the floor, and it is not itself a controlled document.
