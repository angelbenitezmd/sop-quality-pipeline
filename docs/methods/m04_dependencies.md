# 04 — Cross-Reference Dependency Mapping

**Question it answers:** Which SOPs depend on which, and where does that web of cross-references break down — orphaned documents, circular chains, pointers to SOPs that don't exist, and single points of failure whose revision ripples everywhere?

**Deck slide:** 18.

**Scope:** Corpus-wide. There is no per-SOP score. The module builds **one** directed graph of the whole English corpus and reports structural facts about it (node/edge counts and four governance signals). A single document only appears here in relation to the others — as a hub, an orphan, a broken target, or a link in a cycle.

---

## The source: what it reads

This module does **not** use the readability, ambiguity, passive-voice or style signals from the foundations. It reads exactly two things:

- **Cross-references** — the foundation observation defined in `00_foundations.md`: every `SOP-XXX-000` identifier written in a document's body, matched by the pattern `SOP-[A-Z]{2,4}-\d{3}(?:-[A-Z]{2})?`, **excluding the document's own id**, de-duplicated and order-preserving. Because self-ids are filtered out upstream, no document can point at itself here — there are no self-loops in the graph.
- **Department code** — each SOP's `department` (e.g. `CLN`, `QC`, `ENV`), used only to colour nodes, plus `department_name(code)` for the legend.

Cross-references are a valid, defensible proxy for *dependency* because a citation is an explicit, author-written statement that "to do this procedure you must also consult that one." The graph is nothing more than those written statements drawn as arrows — every edge traces to a literal id in the prose, which is the point for an audit.

Only **English** SOPs are included (`corpus.english()` keeps documents whose `language == "en"`); Spanish translations are excluded so a translated pair is not double-counted.

---

## How it works

The engine is **networkx**. The pipeline builds a directed graph and then reads four structural properties off it.

1. **Build the graph (`_build_graph`).** Create an `nx.DiGraph`. Add one node per English SOP, tagged with its `department`. Then, for every SOP, for every id in its `cross_references`, add a directed edge from the citing SOP to the cited id. If a cited id is **not** one of the real SOP ids, it is still added as a node — tagged `department="MISSING"` — so that a pointer to a non-existent SOP stays visible on the map instead of vanishing. The function returns the graph, the set of real ids, and the set of missing ids.

2. **Read the four signals** (defined precisely in *The scoring* below): orphans, cycles, broken references, and hubs, using `in_degree`, `out_degree`, `nx.simple_cycles`, and `nx.strongly_connected_components`.

3. **Lay it out and render (matplotlib).** Position every node with **`nx.spring_layout`** (a force-directed layout: nodes repel, edges pull), then draw nodes, edges and labels, colour by department, and flag missing targets and cycle edges. Node area encodes in-degree. Orphans, which the force layout flings to the margins, are re-parked in a labelled strip under the graph.

---

## The scoring (the critical section)

There is no numeric quality score. What this module "produces" is (a) the four governance signals, each with an exact definition, and (b) a fixed set of visual-encoding constants. Both are given in full below.

### The graph

| Element | Rule (verbatim from code) |
|---|---|
| Nodes | one per English SOP (`department` tag) **plus** one per missing cited id (`department="MISSING"`) |
| Edges | one directed edge `citing_sop → cited_id` per distinct cross-reference |
| Self-loops | impossible — `cross_references` excludes the document's own id |

`summary` reports `nodes = g.number_of_nodes()` and `edges = g.number_of_edges()`.

### Signal 1 — Orphans

A real SOP `n` is an orphan when **`in_degree[n] == 0` and `out_degree(n) == 0`** — nothing cites it and it cites nothing. Computed only over real ids (a MISSING node always has in-degree ≥ 1, so it can never be an orphan). The list is sorted alphabetically. `summary.orphans = len(orphans)`.

### Signal 2 — Circular dependencies (cycles)

Every elementary cycle is enumerated with **`nx.simple_cycles(g)`**. Because `simple_cycles` returns each cycle at an arbitrary starting rotation, each is canonicalised by **`_canonical_cycle`**: rotate the list so it begins at its **lexicographically smallest node** (`i = cycle.index(min(cycle)); cycle[i:] + cycle[:i]`), then the whole list of cycles is sorted. This makes the output identical across machines and runs. `summary.cycles = len(cycles)`.

Separately, for the *drawing*, the module marks which **edges** lie on a cycle (`_cycle_edges`): an edge `(u, v)` is a cycle edge when `u` and `v` fall in the **same strongly connected component of size > 1** (`nx.strongly_connected_components`, keeping only components with `len(comp) > 1`). These are drawn in the accent colour.

One specific loop is pulled out for the table — the manufacturing/QC feedback loop, found as the cycle whose node set equals exactly **`{"SOP-QC-002", "SOP-MFG-004", "SOP-ENV-001"}`**.

### Signal 3 — Broken references

`broken` maps each missing id to the sorted list of real SOPs that cite it: `{m: sorted(u for u, v in g.in_edges(m)) for m in sorted(missing)}`. These are dangling pointers — an SOP cites an id that is not in the corpus. `summary.broken_refs = len(broken)`. In the drawing, an edge is a broken edge when its **target is a missing id** (`v in missing`); these are drawn dashed in red.

### Signal 4 — Hub documents

Real ids are ranked by `ranked_hubs = sorted(real_ids, key=lambda n: (-in_degree[n], n))` — **descending in-degree, then ascending id** as the tie-break. `top_hub = ranked_hubs[0]`; `summary.top_hub = f"{top_hub} (in-degree {in_degree[top_hub]})"`. The results table lists the **top 5** hubs, each captioned `"cited by {in_degree} SOPs"`.

### Node sizing (the encoding of in-degree)

Marker **area in points²** is:

- **Missing node:** fixed **300**.
- **Real node:** **150 + 100 × in_degree(n)**.

So an uncited SOP is 150 pt², and each additional inbound citation adds 100 pt². The label placer converts area to a radius with `_radius_pt(area) = (area / 3.14159265) ** 0.5` (i.e. radius = √(area/π)) purely to park labels just outside each disc.

### Layout parameters (fixed, for reproducibility)

`nx.spring_layout(g, seed=42, k=6.0, iterations=400)`. The large `k` (target spacing) and 400 iterations spread the corpus out instead of collapsing it into a knot around the top hub; **`seed=42`** makes the picture deterministic.

### Colour and edge encoding (exact constants from `viz.py` / the draw calls)

| Thing | Colour (from `viz`) | Other |
|---|---|---|
| Department nodes | `CATEGORICAL[i % 10]` over **sorted** department codes (10-colour palette, first colour `#0B3C5D`) | edge `INK #16232E`, linewidth 0.6 |
| Missing target | `BAD #C1442E`, marker shape `"X"` | node_size 300, linewidth 0.8 |
| Normal edge | `MUTED #8A9BA8` | width 0.7, arrowsize 7, alpha 0.38, `arc3,rad=0.20` |
| Cycle edge | `ACCENT #E8833A` | width 1.7, arrowsize 11, alpha 0.9, `arc3,rad=0.12` |
| Broken reference edge | `BAD #C1442E`, dashed | width 1.2, arrowsize 9, alpha 0.85, `arc3,rad=0.09` |
| Labels | id with `SOP-` stripped | font size 7.0; box border red if missing else `GRID #DCE4E9` |

Figure size is 17.5 × 12.0 inches. Orphans are re-positioned into a strip below the connected core (a dashed hairline rule plus the caption "orphans — no inbound or outbound cross-references") so a parked node reads as *detached*, not as a bottom row of the graph.

There are **no pass/warn/fail bands** — this is a structural map, not a graded scorecard. The "verdict" is qualitative: an orphan, a broken ref, or a cycle is a finding a human reviews.

---

## How to read the result

- **A big node = a hub.** Size grows with in-degree (times cited), so the largest discs are the SOPs whose revision forces the widest re-review. The single top hub is the corpus's biggest single point of failure.
- **A red "X" node = a broken reference.** Some SOP cites an id that does not exist in the corpus — a typo, a retired document, or a never-created one. The dashed red edges point at it and the table names who cited it.
- **Amber edges forming a loop = a circular dependency.** Document A requires B requires C requires A: there is no clean starting point, and a change anywhere in the loop can force re-validation around the whole ring.
- **A node parked in the bottom strip = an orphan.** It neither cites nor is cited by anything — possibly genuinely standalone, possibly disconnected from the governance web by mistake.

**Artifacts.** One PNG, `output/m04_dependencies/dependency_graph.png` — the map itself. The machine-readable results live in `summary.json`: the `summary` block (nodes, edges, orphans, cycles, broken_refs, top_hub) and a `table` of every hub, broken ref, orphan and the flagged feedback cycle.

**How a reviewer acts.** Fix broken references first (they are unambiguous defects). Confirm each orphan is intentional. Decide whether each cycle is a legitimate mutual dependency or an accident of over-citation. Treat the top hubs as change-control priorities — put extra review rigour on any revision to them.

---

## Worked example (real numbers from `summary.json`)

The demo corpus produced a graph of **42 nodes** and **97 directed references** across **40 English SOPs** (42 nodes = 40 real SOPs + 2 missing targets). It found **2 orphans, 23 cycles, and 2 broken references**.

**The top hub — `SOP-DOC-001`, in-degree 24.** Twenty-four SOPs cite it, more than any other document. Its node area is `150 + 100 × 24 = 2550` pt² (radius ≈ √(2550/3.14159265) ≈ 28.5 pt) — the largest disc on the map. Ranked next are `SOP-ENV-001` (in-degree 10 → 1150 pt², radius ≈ 19.1 pt), then `SOP-CLN-001`, `SOP-EQP-001`, `SOP-MFG-001` (each in-degree 5 → 650 pt²). The five are tied-broken alphabetically, which is why `CLN-001` precedes `EQP-001` precedes `MFG-001`. Verdict: revising `SOP-DOC-001` should trigger review of two dozen downstream SOPs — the biggest single point of failure in the set.

**Broken references (2).** `SOP-CLN-099` is cited by `SOP-CLN-007` but absent from the corpus; `SOP-VAL-001` is cited by `SOP-MFG-006` but absent. Each is drawn as a red "X" node (fixed 300 pt²) with a dashed red edge from its one citer. Verdict: two concrete, fixable defects — either the target SOP is missing or the id is wrong.

**Orphans (2).** `SOP-ENV-004` and `SOP-WHS-003` each have in-degree 0 **and** out-degree 0, so both drop to the orphan strip. Their node area is the floor `150 + 100 × 0 = 150` pt² (radius ≈ 6.9 pt). Verdict: neither participates in the cross-reference web — confirm that is intentional.

**The flagged cycle.** Among the 23 elementary cycles, the module surfaces the one whose node set is exactly `{SOP-QC-002, SOP-MFG-004, SOP-ENV-001}`. Canonicalised to start at its smallest id (`SOP-ENV-001`), the table renders it `ENV-001 -> QC-002 -> MFG-004 -> ENV-001` — the directed edges ENV-001→QC-002→MFG-004→ENV-001, drawn in amber. Verdict: a genuine three-way feedback loop between QC, manufacturing and environmental monitoring, with no clean entry point for revision.

---

## What it cannot see (limitations)

- **It only sees citations that are written as ids.** A real dependency expressed in prose ("per the cleaning procedure") without the `SOP-XXX-000` id produces no edge — the graph *under-counts* dependencies that authors described in words. Conversely, an id mentioned only historically ("supersedes SOP-CLN-002") still creates an edge, so it can *over-count* by treating a passing mention as a live dependency. The graph is a map of *references*, not of true logical need.
- **Direction is citation, not causation.** An edge means "A's text names B," which usually implies A depends on B — but the module cannot tell a mandatory prerequisite from an informational "see also." A human judges which cycles and hubs actually matter.
- **Broken ≠ always an error.** A dangling reference may be a deliberately external document (a corporate policy outside this corpus) rather than a defect. The module flags all missing targets identically; it cannot know which are legitimately out of scope.
- **Orphan ≠ always a problem.** A standalone SOP that genuinely stands alone is correctly isolated but flagged the same as one accidentally disconnected.
- **Self-references are invisible here.** Because `cross_references` strips the document's own id upstream, a document that cites itself (e.g. from un-stripped PDF page headers) produces no self-loop on this map — that condition has to be caught before the graph is built, not from it.
- **English-only, and department is cosmetic.** Spanish documents are excluded entirely, so a dependency that exists only in a translated variant is not shown. Department colour and the palette assignment (sorted order, mod-10 cycling) are display only and never affect any signal.
- **The picture is deterministic but the coordinates are meaningless.** `seed=42` makes the layout reproducible, and node *area* faithfully encodes in-degree, but the x/y positions are arbitrary force-layout output — distance and axis position on the map carry no measurement.
