# 13 — Training Content Auto-Generation

**Question it answers:** For every English SOP, can we automatically produce a self-contained training package — role-based summaries, a knowledge check with an answer key, and a quick-reference/decision aid — drawn entirely from the SOP's own text?

**Deck slide:** 13.

**Scope:** per-SOP. Each English SOP gets its own Markdown package written to `output/m13_training/sops/training_<SOP-ID>.md`, its own row in the module table and `per_sop` block, and a status of `pass` or `n/a`. One corpus-wide chart (`training.png`) rolls the per-SOP item counts up; there are no per-SOP images — the Markdown *is* the deliverable.

---

## The source: what it reads

This module is a **generator**, not a scorer: it re-reads each SOP's raw structure and reassembles it into teaching material. It consumes:

- **The SOP body, re-split into (heading, text) sections** by its own splitter that recognises all three heading styles from the foundations (`#`-markdown, bare **roman-numeral** `V. PROCEDURE`, and **ALL-CAPS** lines of ≥ 4 letters). This mirrors the loader's Sections observation but is self-contained so a roman-numeral or all-caps SOP still splits correctly.
- **Procedure steps**, extracted from whichever of four drafting conventions the SOP actually uses: numbered lists, `Step N:` paragraphs, bulleted procedures, or directive prose. The prose fallback leans directly on **Signal 4 — Verb-first steps** (`lexicon.STRONG_IMPERATIVES` and `lexicon.sentence_starts_with_verb`) plus a directive-modal regex (`shall|should|must|will|is/are required to|is/are to be`) to decide which sentences are actionable.
- **Numeric parameters** mined from the prose — contact times, temperatures, particle sizes, concentrations, conductivities — via a units regex.
- **Regulatory citations**, via **Signal 6 — Regulatory citations & currency** (`RegKB.extract`), including each citation's `current / outdated / review / unknown` status.
- **Cross-references** (`SOP-XXX-000` ids in the body) from the loader.
- **Conditional language** (`If …, …` and escalation verbs) to seed the IF/THEN decision aid.
- **YAML header fields** — owner, version, effective date, department — and the manifest's `complexity` label, used only as descriptive metadata (the manifest/RegKB supply ground-truth labels, never the content).

Why these are defensible proxies for "trainable content": the house standard is verb-first imperative steps and measurable acceptance criteria, so the steps and numeric specs a well-written SOP already contains *are* the things an operator must be tested on. Pulling questions and summaries straight from the SOP text (never inventing facts) keeps the training faithful to the controlled document — the audit-critical property here.

---

## How it works

Everything runs in pure Python with regex and the shared `lexicon`/`RegKB`/`viz` helpers — **no trained model, no NLP library** does the reasoning. The one external library is **matplotlib** (via `sop_pipeline.core.viz`) for the single roll-up chart. Determinism is fixed with `random.seed(42)` (`RANDOM_STATE = 42`); question order is fully deterministic, so the same corpus always yields identical packages.

Per SOP the builder:

1. **Splits the body** into (heading, text) sections across markdown/roman/all-caps styles.
2. **Extracts operator steps.** For each non-boilerplate section it tries, in order, *numbered → step-prefixed → bulleted*, keeping a convention only if it yields ≥ 2 items (each ≥ 2 words, not a table row). A bulleted block must also look like a procedure, not a taxonomy: at least half its items must be directive or "substantial" (≥ 8 words). If no list survives, it falls back to **directive prose** sentences (≥ 2 of them). A section named for the procedure (see keywords below) that carries an explicit numbered or step-prefixed list *wins outright*; otherwise every section's steps are consolidated.
3. **Mines numeric parameters** — a number (optionally a range) immediately followed by a recognised unit — from every section except revision-history/reference tables, de-duplicating by value and keeping the shortest containing sentence for a clean fill-in-the-blank.
4. **Assembles three role summaries** (Operator / Supervisor / QA).
5. **Builds a 3–5 item knowledge check** with an answer key.
6. **Derives an IF/THEN decision aid** from the SOP's conditional language, topped up from a fixed escalation template.
7. **Renders Markdown**, decides `pass`/`n/a`, and appends a row for the index and chart.

The corpus chart is a stacked bar per SOP (role summaries + quiz questions + aids), grouped by department with dividers.

---

## The scoring (the critical section)

This module produces **counts and generated text**, not a 0–100 score. Every count is defined exactly below.

### Role-based summaries (always exactly 3 per package)

`summaries` is the constant **3**. The three blocks are assembled as:

- **Operator — key steps.** The consolidated procedure steps, each passed through a light plain-language cleanup (`_plainify`): it strips `**bold**`, removes a leading "The operator will/The operator", rewrites `will be → is` and `shall be → must be`, and capitalises. If the SOP has no extractable steps, the block prints "No procedural steps could be extracted from this document."
- **Supervisor — oversight & acceptance.** Oversight = lines from the Responsibilities section matching `supervisor | manager | lead | quality assurance | review | verif | confirm | approv | ensur | oversee | responsib` (case-insensitive). Acceptance = lines from the first section whose heading contains `acceptance | in-process | limits | criteria`. Each falls back to a single generic sentence if empty.
- **QA — references, records & data integrity.** Citations with their status; the list of related controlled documents (cross-references); and **data-integrity points** = readable lines from the first `documentation | records | data` section, or, if none, up to **3** body lines matching `record | document | logbook | data integrity | SOP-DOC-001`. Either way the DI list is capped at **4**.

A "readable line" (`_section_lines`) is a list item or sentence of **≥ 4 words** that is not a table row.

### Knowledge check (`questions` = 3–5)

Questions are appended in this fixed order, then the list is **capped at 5** (`quiz[:5]`):

| Order | Condition | Question | Answer key |
| --- | --- | --- | --- |
| 1–2 | First **2** mined numeric params (`numeric[:2]`) | "Fill in the blank: …" with the value blanked to `_____` (first occurrence only) | the numeric value (e.g. `70%`) |
| 3 | steps exist | "What is the first step performed under \"\<heading>\"?" | plain-language `steps[0]` |
| 4 | steps exist | 1 stage → "How many steps does the \<SOP-ID> procedure contain?"; ≥ 2 stages → "Across its \<N> operational stages, how many steps does \<SOP-ID> define in total?" | `str(total step count)` |
| 5 | citations exist | "Which regulatory reference(s) does \<SOP-ID> cite?" | citation names, comma-joined |
| 5' | else if cross-refs exist | "Name a related SOP that \<SOP-ID> cross-references." | related ids |
| 6 | acceptance lines exist | "State one acceptance criterion this procedure must meet." | first acceptance line |

Two floor guarantees enforce a **minimum of 3** questions: if fewer than 3 exist and cross-references are present, a related-SOP question is added; if still fewer than 3, a last-resort ownership question ("Which function owns \<SOP-ID>, and who is the document owner?") is added. Because the numeric questions use `numeric[:2]`, an SOP can report `numeric_params = 3` yet anchor only **2** fill-in-the-blank items.

### Decision aid & quick reference (together = `aids`)

- **IF/THEN decision aid.** `_conditionals` scans readable lines for two patterns: a sentence starting `If <cond>, <action>` → `IF <cond> THEN <action>.`; or a sentence containing an escalation verb (`notify | escalate | discard | evacuate | stop | report | reject | repeat | open an investigation`) followed by `when|if <cond>` → `IF <cond> THEN <action>.`. Derived lines are de-duplicated and **capped at 4**. The count kept here is recorded as `derived_decisions`. **If fewer than 2 were derived**, two fixed template lines are appended and the list is re-capped at 4:
  - "IF a step cannot be performed as written THEN stop and notify the shift supervisor before proceeding."
  - "IF acceptance criteria are not met THEN document the excursion and escalate to Quality Assurance (per SOP-DOC-001)."
- **Quick reference.** Always exactly **6** lines: owner/version/effective date; primary references; related SOPs; key numeric specs; number of procedure steps to master; estimated session length.

`aids = len(quick_ref) + len(decision) = 6 + (2…4)`, so **aids is 8, 9, or 10**.

### Estimated session length

`est_minutes = 5 × ⌈(10 + 2·steps + 2·questions) / 5⌉` — a 10-minute base briefing plus **2 min per step** and **2 min per quiz question**, rounded **up to the nearest 5**.

### Status band (per SOP)

| `usable` test | Status | Effect |
| --- | --- | --- |
| has ≥ 1 extracted step **OR** ≥ 3 quiz questions | **pass** | package file written; counts reported |
| neither | **n/a** | no file; counts zeroed; finding tells the author to remediate document structure first |

The index links the package only for `pass` rows; `n/a` rows show "—". `source_style` reports the drafting convention detected (`numbered`, `step-prefixed`, `bulleted`, `prose`, `mixed`, or `none`). Corpus roll-ups are plain sums: `packages_generated` = count of `pass`, `est_curriculum_hours = round(total_minutes / 60, 1)`.

---

## How to read the result

- **Status `pass` with high `numeric_params`** = the best case: the SOP carried measurable specs, so the answer key is anchored on real numbers an operator must know (a contact time, a temperature). **`numeric_params = 0`** means the quiz fell back to step/reference/acceptance recall — often a *drafting gap* (the SOP states no measurable acceptance criteria) worth flagging to the author.
- **`source_style`** tells you how the SOP was written. `prose` or `bulleted` packages are just as complete as `numbered` ones — the point of the four-convention extractor — but a `prose` result is a hint the SOP isn't in the house numbered-step style.
- **QA block statuses** matter most for release: a citation marked `outdated` or `review` (e.g. *EU GMP Annex 15*, *ISO 14644-1*, *ICH Q2(R1)*) is surfaced in the finding as "must be corrected before the package is released for training." Do not train from a package that cites a superseded standard.
- **`derived_decisions`** vs template: if the finding says "0 IF/THEN line(s) auto-derived … 2 added from the standard escalation template," the SOP contained little explicit conditional/escalation language — the decision aid is generic, not procedure-specific.
- **Artifacts.** `training_<SOP-ID>.md` is the trainer-ready handout (3 summaries, numbered knowledge check + answer key, quick reference + decision aid). `training_index.md` is the one-line-per-SOP table (style, steps, questions, aids, est. min, status, link). `training.png` shows every SOP's item counts stacked and grouped by department — a quick read of coverage across the corpus.
- **A reviewer should** open the package, confirm the extracted steps match the SOP's intent, verify the answer key against the source text, correct any stale citation, and only then release it for training.

---

## Worked example

**SOP-CLN-001 — Cleaning and Disinfection** (`numbered` style, status `pass`).

From `summary.json` this SOP produced: **3** summaries, **5** questions, **8** aids, **6** steps, **3** numeric params, `est_minutes = 35`.

Trace:

- **Steps.** Six numbered steps were extracted from a single section, "CLEANING AND DISINFECTION PROCEDURE" (`groups = 1` stage). The Operator block lists all six in plain language.
- **Numeric params.** Three distinct measured specs were mined; the quiz uses the first two (`numeric[:2]`): **`70%`** (IPA concentration) and **`0.5 minutes`** (contact time). Each became a fill-in-the-blank: e.g. "…wiped with `_____` isopropyl alcohol and … a contact time of not less than 0.5 minutes…" → answer `70%`.
- **Questions (5).** Q1–Q2 the two cloze items; Q3 "What is the first step performed under \"CLEANING AND DISINFECTION PROCEDURE\"?" (answer = the plain-language first step); Q4 "How many steps does the SOP-CLN-001 procedure contain?" → `6` (single stage, so the singular phrasing); Q5 "Which regulatory reference(s) does SOP-CLN-001 cite?" → `21 CFR 211.67`. The finding notes the one citation is "all current," so this package is clean to release.
- **Aids (8).** 6 quick-reference lines + decision aid. The SOP had **0** derivable IF/THEN lines, so both were pulled from the escalation template (2 lines) → `6 + 2 = 8`.
- **Session length.** `10 + 2·6 + 2·5 = 32`; `⌈32/5⌉ = 7`; `5·7 = 35` → **35 min**, exactly as reported.

Contrast **SOP-CLN-003**: same shape (6 steps, 3 numeric params, 5 questions, 35 min) but its single citation is *EU GMP Annex 15*, flagged **outdated/under review** — the finding says it "must be corrected before the package is released." Same generator, opposite release verdict, driven entirely by the citation status.

---

## What it cannot see (limitations)

- **Extraction is regex/keyword-based, not comprehension.** It reproduces what the SOP *says*; it cannot tell whether a step is correct, complete, or safe. A wrong instruction in the SOP becomes a wrong "correct answer" in the quiz. A human must verify the answer key against reality, not just against the text.
- **`numeric_params = 0` is not "no parameters exist"** — only that none matched the units regex. A spec written in an unusual unit or phrased without a number is missed, and only the first **2** mined values ever become questions even when more exist.
- **Question difficulty is shallow.** Fill-in-the-blank, first-step recall, step-count, and citation-name questions test recall, not judgement or troubleshooting. "How many steps" and "who owns this SOP" are testable facts, not competence.
- **The decision aid is often generic.** When the SOP lacks explicit `If …`/escalation language, both IF/THEN lines come from a fixed template — useful boilerplate, but not procedure-specific reasoning, and it should not be read as evidence the SOP handles those contingencies.
- **Summaries can be thin or mis-slotted.** Oversight, acceptance, and data-integrity content are found by heading keyword and word-matching; an SOP that files acceptance criteria under an unrecognised heading yields a generic fallback line. The Operator "plainify" is cosmetic (a few substitutions), not true simplification — long, passive sentences survive largely intact.
- **`pass` means "package could be built," not "package is good."** The bar is one step or three questions. A `pass` SOP can still cite a superseded standard, contain no measurable criteria, or read above operator grade level — those judgements live in other modules and with a human reviewer.
- **English corpus only**, and the manifest's ground-truth labels are used solely for metadata — the training content is never validated against them.
