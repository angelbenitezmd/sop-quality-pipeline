"""SOP Quality Transformation pipeline — orchestrator.

Discovers every module under ``sop_pipeline/modules/mNN_*.py``, runs each against
the loaded corpus, saves per-module ``summary.json``, and renders the HTML dashboard.

Usage:
    python3 -m sop_pipeline.cli run              # run all modules + build dashboard
    python3 -m sop_pipeline.cli run --module 03  # run a single module
    python3 -m sop_pipeline.cli list             # list discovered modules
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import traceback
from pathlib import Path

from .core.corpus import OUTPUT_DIR, PROJECT_ROOT, load_corpus
from . import report, sop_report

MODULES_DIR = Path(__file__).resolve().parent / "modules"
MODULE_RE = re.compile(r"^m(\d{2})_[a-z0-9_]+$")


def discover_modules() -> list[str]:
    """Return module stems (e.g. 'm01_similarity') sorted by number."""
    stems = []
    for p in MODULES_DIR.glob("m*.py"):
        if MODULE_RE.match(p.stem):
            stems.append(p.stem)
    return sorted(stems, key=lambda s: int(s[1:3]))


def run_module(stem: str, corpus, quiet: bool = False) -> dict:
    outdir = OUTPUT_DIR / stem
    outdir.mkdir(parents=True, exist_ok=True)
    mod = importlib.import_module(f"sop_pipeline.modules.{stem}")
    if not hasattr(mod, "run"):
        return {"module": stem, "title": stem, "_error": "no run() function"}
    try:
        result = mod.run(corpus, outdir)
        if not isinstance(result, dict):
            result = {"module": stem, "title": stem, "_error": "run() did not return a dict"}
        result.setdefault("module", stem)
        result.setdefault("title", stem)
    except Exception as exc:  # keep the pipeline going; record the failure
        if not quiet:
            traceback.print_exc()
        result = {"module": stem, "title": stem, "_error": f"{type(exc).__name__}: {exc}"}
    # persist the machine-readable result
    (outdir / "summary.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result


def corpus_stats(corpus) -> dict:
    en = corpus.english()
    depts = corpus.by_department()
    return {
        "SOPs": len(corpus),
        "EN / ES": f"{len(en)} / {len(corpus) - len(en)}",
        "Departments": len(depts),
        "Capabilities": len(discover_modules()),
    }


def cmd_run(args) -> int:
    sop_dir = Path(args.sops).expanduser() if args.sops else None
    if sop_dir and not sop_dir.is_dir():
        print(f"SOP directory not found: {sop_dir}")
        return 1
    corpus = load_corpus(sop_dir)
    if len(corpus) == 0:
        where = sop_dir or "data/sops/"
        print(f"No SOPs (*.md) found under {where}.")
        return 1
    stems = discover_modules()
    if args.module:
        want = args.module.zfill(2)
        stems = [s for s in stems if s[1:3] == want]
        if not stems:
            print(f"No module matches number {args.module!r}. Available: {discover_modules()}")
            return 1

    print(f"Loaded {len(corpus)} SOPs · running {len(stems)} module(s)\n" + "-" * 60)
    results = []
    for stem in stems:
        r = run_module(stem, corpus, quiet=args.quiet)
        status = "ERROR" if r.get("_error") else "ok"
        findings = len(r.get("key_findings", []))
        arts = len(r.get("artifacts", []))
        print(f"  [{status:5s}] {stem:22s} {r.get('title',''):42s} findings={findings} artifacts={arts}")
        if r.get("_error"):
            print(f"          -> {r['_error']}")
        results.append(r)

    # Always (re)render from whatever ran. If a single module was run, merge with
    # previously saved summaries so both reports stay complete.
    all_results = _merge_with_saved(results)
    report_path = report.render(all_results, corpus_stats(corpus), OUTPUT_DIR / "report" / "index.html")
    # Every SOP also gets its own assessment dossier — a corpus average is not
    # actionable when remediating one specific document.
    sop_index, rows = sop_report.render_all(corpus, all_results, OUTPUT_DIR)

    print("-" * 60)
    ok = sum(1 for r in results if not r.get("_error"))
    print(f"{ok}/{len(results)} module(s) succeeded.")
    flagged = sum(1 for r in rows if r["overall"] in ("fail", "warn"))
    print(f"Per-SOP assessments: {len(rows)} ({flagged} flagged for action or review)")
    print(f"Dashboard:  {report_path}")
    print(f"Per-SOP:    {sop_index}")
    return 0 if ok == len(results) else 2


def _merge_with_saved(fresh: list[dict]) -> list[dict]:
    """Combine freshly-run results with any previously saved summary.json files,
    preferring fresh, ordered by module number."""
    by_stem: dict[str, dict] = {}
    for stem in discover_modules():
        sp = OUTPUT_DIR / stem / "summary.json"
        if sp.exists():
            try:
                by_stem[stem] = json.loads(sp.read_text(encoding="utf-8"))
            except Exception:
                pass
    for r in fresh:
        by_stem[r.get("module", "")] = r
    ordered = [by_stem[s] for s in discover_modules() if s in by_stem]
    return ordered


def cmd_verify(args) -> int:
    """Self-test: run every module over the bundled demo corpus.

    The point is to prove the install works — dependencies present, all 13
    capabilities executing — before anyone trusts the pipeline on real,
    regulated documents.
    """
    from .core.corpus import EXAMPLE_SOP_DIR

    if not EXAMPLE_SOP_DIR.is_dir() or not any(EXAMPLE_SOP_DIR.glob("*.md")):
        print(f"Demo corpus not found at {EXAMPLE_SOP_DIR}")
        return 1
    corpus = load_corpus(EXAMPLE_SOP_DIR)
    print(f"Self-test on the bundled demo corpus ({len(corpus)} SOPs)\n" + "-" * 60)
    failures = []
    for stem in discover_modules():
        r = run_module(stem, corpus, quiet=True)
        ok = not r.get("_error")
        print(f"  [{'ok' if ok else 'FAIL':4s}] {stem}")
        if not ok:
            failures.append((stem, r["_error"]))
    print("-" * 60)
    if failures:
        print(f"{len(failures)} module(s) failed:")
        for stem, err in failures:
            print(f"  {stem}: {err}")
        return 1
    print(f"All {len(discover_modules())} capabilities ran. The install is good.")
    print("Next: put your SOPs in data/sops/ (or use `ingest` for PDFs), then `run`.")
    return 0


def cmd_list(args) -> int:
    stems = discover_modules()
    print(f"{len(stems)} module(s) discovered under {MODULES_DIR}:")
    for s in stems:
        print(f"  {s}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sop_pipeline", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run modules and build the dashboard")
    r.add_argument("--module", help="run only this module number, e.g. 03")
    r.add_argument("--sops", metavar="DIR",
                   help="directory of SOP .md files to analyze (default: data/sops)")
    r.add_argument("--quiet", action="store_true", help="suppress tracebacks")
    r.set_defaults(func=cmd_run)
    v = sub.add_parser("verify", help="self-test the install against the bundled demo corpus")
    v.set_defaults(func=cmd_verify)
    l = sub.add_parser("list", help="list discovered modules")
    l.set_defaults(func=cmd_list)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
