# Foundations — the shared signals

Every capability is built from a small set of text measurements taken from the SOP body.
The same measurements are reused across modules, so they are defined **once** here; each
module's method card says which of them it uses and how it combines them. Nothing in the
pipeline uses a trained/opaque model — every number traces back to a rule you can read,
which is the point for an audit.

This is the vocabulary. Read it first; the per-module cards assume it.

---

## What the pipeline reads from each SOP

An SOP is a Markdown file with a small YAML header (`sop_id`, `title`, `version`,
`effective_date`, `next_review`, `owner`, `language`, …) and a body. From the body the
loader derives, per document:

- **Words** — tokens matching letters (incl. accented Spanish letters) and apostrophes.
- **Sentences** — split on `.`/`!`/`?` followed by whitespace and a capital, digit, or
  quote. Decimals (`0.5`) and common abbreviations (`e.g.`, `no.`, `approx.`) are protected
  so they don't create false breaks.
- **Sections** — a heading starts a new section. A line is a heading if it is a Markdown
  `#`-heading, a bare **roman-numeral** heading (`I. Purpose`), or an **ALL-CAPS** line of
  ≥ 4 letters. This is why the same corpus can mix heading styles — the parser recognises
  all three, which module 11 then exploits to detect *which* style each department uses.
- **Cross-references** — every `SOP-XXX-000` identifier appearing in the body, excluding
  the document's own id. This is text-based: a reference only counts if the id is actually
  written in the prose. (If PDF page headers carrying the id were not stripped during
  ingest, a document would appear to reference itself — which is why module 4 treats any
  self-reference as a red flag.)

These are **observations**, not judgements. The judgements come from the signals below.

---

## Signal 1 — Ambiguous terms

**What it is.** A fixed list of ~45 vague, non-actionable words and phrases — the ones an
auditor circles because they don't tell the operator what to actually do:

> appropriate, adequate, sufficient, as necessary, as needed, if needed, as required,
> periodically, regularly, routinely, where applicable, reasonable, acceptable, properly,
> suitable, in a timely manner, as soon as possible, approximately, generally, typically,
> as directed … (plus Spanish equivalents for translated variants)

**How it's measured.** Case-insensitive, whole-word matching (so "adequate" matches but
"adequately-sized" is handled by the specific listed forms). The count is usually expressed
**per 100 words** so long and short SOPs compare fairly.

**Why it's a valid proxy.** GMP expects measurable acceptance criteria. "Clean the surface
adequately" cannot be executed or verified consistently; "wipe until no residue is visible"
can. Ambiguous-term density is a direct, defensible proxy for *how much of an SOP is
un-actionable*.

**What it can't see.** It is a fixed list, not comprehension. A vague instruction phrased
without a listed word ("do the usual prep") is missed; a listed word used precisely ("adjust
to the appropriate setpoint of 21 °C") is still counted. It flags candidates for a human, it
does not adjudicate.

---

## Signal 2 — Passive voice

**What it is.** An approximate detector: a "to be" verb (`is`, `are`, `was`, `shall be`,
`must be`, `has been`, …) followed within a couple of tokens by a past participle
(`-ed`/`-en` endings plus common irregulars like `made`, `done`, `taken`, `written`).

**Why it's a valid proxy.** "The vial shall be inspected" hides *who* inspects; "Inspect the
vial" assigns the action. Passive constructions correlate with unclear responsibility and
harder reading, both of which matter on a manufacturing floor.

**What it can't see.** It is a regex heuristic, not a parser — it will miss unusual
constructions and can over-count an adjective that looks like a participle. Used as a
relative density, not an absolute grammatical truth.

---

## Signal 3 — Nominalizations

**What it is.** Abstract noun forms that bury a verb — words ending `-tion`, `-sion`,
`-ment`, `-ance`, `-ence`, `-ility`, `-ization`. "Perform verification of the calibration"
instead of "verify the calibration."

**Why it matters.** Nominalized prose reads several grades harder and distances the reader
from the action. It is a hallmark of the QC-lab writing style.

**What it can't see.** Suffix-only: legitimate nouns ("solution", "station") are counted
too, so it is a style-density signal, not a defect list.

---

## Signal 4 — Verb-first steps (imperatives)

**What it is.** A step is "verb-first" if its first word is one of ~70 strong operational
imperatives (record, verify, measure, inspect, remove, install, wipe, calibrate, incubate,
weigh, dispense, reconcile, quarantine, release, …).

**Why it's a valid proxy.** The house standard is verb-first imperative steps ("Record the
value"), which are the clearest form for an operator following a procedure. The *fraction*
of steps that are verb-first measures how directive the procedure actually is.

**What it can't see.** A fixed verb list — a valid instruction opening with an unlisted verb
reads as non-verb-first. Deliberately narrow so it rewards genuinely operational language.

---

## Signal 5 — Reading grade (readability)

**What it is.** US school-grade readability. Two forms appear in the pipeline:

- Modules 3 and 6 use the **`textstat`** library: Flesch-Kincaid Grade, Gunning Fog, and
  Coleman-Liau, averaged.
- Module 7 uses a **self-contained Flesch-Kincaid** grade
  (`0.39·(words/sentence) + 11.8·(syllables/word) − 15.59`) with a bullet-aware sentence
  count, so a fully bulleted SOP isn't scored as one giant sentence.

All are driven by the same two levers: **sentence length** and **word complexity**
(syllables). Grade 8–10 ≈ general audience; Grade 13+ ≈ college level.

**Why it's a valid proxy.** The deck's thesis — operators can't reliably follow SOPs written
above their reading level. Grade level is the standard, defensible measure of that.

**What it can't see.** It's a surface formula: it counts syllables and sentence length, not
meaning. Necessary technical terms ("chromatography") raise the grade legitimately, so a
high grade is a *flag to review*, not proof of a defect. (This is exactly why raw,
un-cleaned PDF text can score a *normal* grade while being garbage — the ratio is stable
even when the text is fragmented; see the ingest notes.)

---

## Signal 6 — Regulatory citations & currency

**What it is.** A citation extractor recognises regulatory references in prose — 21 CFR
parts, ICH (Q2/Q9/Q10…), EU GMP Annexes, USP chapters, ISO standards, PDA technical reports,
GAMP 5 — and any version/edition/year written next to them. Each is then compared against a
**current-version table** in `config/site_config.json`.

Each citation is classified **current / outdated / review / unknown**. "ICH Q2(R1)" is
flagged outdated because the table's current entry is Q2(R2); "EU GMP Annex 15 (2001)" is
outdated against the 2015 revision; and so on.

**Why it's a valid proxy.** Citing a superseded standard is a concrete, common audit
finding. This makes it mechanical and complete rather than reliant on an SME remembering
every revision.

**What it can't see.** It knows what the table knows. **The table is site configuration you
must maintain** — a standard revised after your table was last updated will read as current.
It checks the *version cited*, not whether the SOP's content actually complies with it.

---

## Signal 7 — Style profile

**What it is.** Three observable style attributes per SOP: dominant **heading style**
(markdown / ALL-CAPS / roman / Step N: / bulleted), dominant **obligation modal**
(`must` / `shall` / `should` / `will` / `responsible for`), and step format. The **house
standard** is defined in config (`env_doc_standard`: markdown headings, `must`, verb-first).

**Why it's a valid proxy.** When five departments each write in their own dialect, operators
must re-learn document conventions per area instead of learning one pattern. Consistency is
a genuine usability property, and these three attributes are the measurable part of it.

**What it can't see.** It measures form (headings, modal word), not tone or content quality.

---

## A note on determinism and traceability

Every module is deterministic (fixed random seeds; a fixed analysis date of **1 Jul 2026**
for "overdue review" checks) so the same corpus always yields the same numbers — required
for anything an auditor might re-run. And every score decomposes into these named signals:
there is no step where a number appears that you cannot trace back to counted words,
matched patterns, or a config table. That is the whole design intent — the pipeline
*suggests*, with its reasons exposed; a human *decides*.

---

**Next:** the per-module method cards in this folder (`m01_similarity.md` …
`m13_training.md`) each follow the same structure — *question · source signal · method ·
scoring/thresholds · how to read it · worked example · limitations* — and reference the
signals above by name.
