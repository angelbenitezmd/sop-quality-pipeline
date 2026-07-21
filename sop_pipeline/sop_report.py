"""Per-SOP assessment dossiers.

The corpus dashboard answers "how is the SOP estate doing?". This module answers
"how is THIS document doing?" — one self-contained page per SOP, because a reviewer
remediating a specific procedure needs that SOP's own scorecard, citations,
readability, style deviations, and job aid in one place.

Renders:
    output/sops/index.html          — every SOP with its rolled-up status
    output/sops/<SOP-ID>.html       — that SOP's full assessment
"""

from __future__ import annotations

import html
from pathlib import Path

from .core.corpus import PROJECT_ROOT, Corpus, SOP
from .report import _data_uri, _esc, _render_table, IMG_EXT

# Worst-first ordering used to roll a document's many module verdicts into one.
_SEVERITY = {"fail": 3, "warn": 2, "pass": 1, "n/a": 0, "": 0}
_LABEL = {"fail": "Action required", "warn": "Review", "pass": "Conforms", "n/a": "Not applicable"}


def _worst(statuses: list[str]) -> str:
    real = [s for s in statuses if s]
    if not real:
        return "n/a"
    return max(real, key=lambda s: _SEVERITY.get(s, 0))


def _badge(status: str) -> str:
    s = (status or "n/a").lower()
    return f'<span class="badge {_esc(s.replace("/", ""))}">{_esc(_LABEL.get(s, s))}</span>'


def _collect(results: list[dict], sop_id: str, parent_id: str | None = None) -> list[dict]:
    """Every module assessment that names this SOP, in module order.

    Translated variants are analysed as part of their English parent (running
    English readability metrics over Spanish prose would be meaningless), so a
    variant inherits the parent's entry from any module that assessed the pair —
    that assessment is literally about this document.
    """
    out = []
    for r in results:
        per_sop = r.get("per_sop") or {}
        entry = per_sop.get(sop_id)
        inherited = False
        if not entry and parent_id:
            candidate = per_sop.get(parent_id)
            # Only inherit an assessment that actually concerns the pair, not the
            # parent's own readability/scorecard verdict.
            if candidate and str(candidate.get("status", "")).lower() != "n/a":
                if any(sop_id in str(v) for v in candidate.get("summary", {}).values()) or \
                   any(sop_id in str(f) for f in candidate.get("findings", [])):
                    entry, inherited = candidate, True
        if not entry:
            continue
        out.append({
            "inherited_from": parent_id if inherited else None,
            "module": r.get("module", ""),
            "title": r.get("title", ""),
            "slide": r.get("slide", ""),
            "status": (entry.get("status") or "n/a").lower(),
            "summary": entry.get("summary") or {},
            "findings": entry.get("findings") or [],
            "artifacts": entry.get("artifacts") or [],
            "table": entry.get("table") or [],
            "table_columns": entry.get("table_columns"),
        })
    return out


def _corpus_context(results: list[dict], sop_id: str) -> list[tuple[str, list[str]]]:
    """Findings from the relational (corpus-scope) modules that mention this SOP.

    Similarity, dependencies and near-duplicate detection are reported once for the
    whole corpus, but a reviewer still wants to know if *their* document is in a
    duplicate cluster or is a broken-reference target.
    """
    ctx: list[tuple[str, list[str]]] = []
    short = sop_id.replace("SOP-", "")
    for r in results:
        if r.get("scope") != "corpus":
            continue
        hits = [f for f in (r.get("key_findings") or [])
                if sop_id in str(f) or short in str(f)]
        if hits:
            ctx.append((r.get("title", r.get("module", "")), hits))
    return ctx


def _chips(summary: dict) -> str:
    if not summary:
        return ""
    parts = []
    for k, v in summary.items():
        if isinstance(v, (dict, list)):
            continue
        parts.append(
            f'<div class="chip"><span class="chip-val">{_esc(v)}</span>'
            f'<span class="chip-lbl">{_esc(str(k).replace("_", " ").title())}</span></div>'
        )
    return '<div class="chips">' + "".join(parts) + "</div>" if parts else ""


def _figures(artifacts: list) -> str:
    imgs, files = [], []
    for a in artifacts:
        p = PROJECT_ROOT / a if not Path(a).is_absolute() else Path(a)
        if p.suffix.lower() in IMG_EXT:
            uri = _data_uri(p)
            if uri:
                imgs.append(f'<img loading="lazy" src="{uri}" alt="{_esc(p.name)}">')
        else:
            files.append(p)
    out = ""
    if imgs:
        out += '<div class="figure">' + "".join(imgs) + "</div>"
    for p in files:
        if p.suffix.lower() in {".md", ".mmd", ".txt"} and p.exists():
            body = p.read_text(encoding="utf-8", errors="replace")
            if len(body) > 20000:
                body = body[:20000] + "\n… (truncated)"
            out += (f'<details class="doc"><summary>{_esc(p.name)}</summary>'
                    f'<pre>{html.escape(body)}</pre></details>')
        else:
            out += f'<div class="artifacts"><span class="afile">{_esc(p.name)}</span></div>'
    return out


def _section(a: dict) -> str:
    body = _chips(a["summary"])
    if a["findings"]:
        body += '<ul class="findings">' + "".join(
            f"<li>{_esc(f)}</li>" for f in a["findings"]) + "</ul>"
    body += _figures(a["artifacts"])
    body += _render_table(a["table"], a.get("table_columns"))
    slide = f'<span class="slide">deck&nbsp;slide&nbsp;{_esc(a["slide"])}</span>' if a["slide"] else ""
    note = ""
    if a.get("inherited_from"):
        note = (f'<p class="note">Assessed as part of the paired comparison with its English '
                f'parent {_esc(a["inherited_from"])}.</p>')
    return (f'<section class="card">'
            f'<div class="card-head"><h2>{_esc(a["title"])}</h2>{_badge(a["status"])}{slide}</div>'
            f'<div class="card-body">{note}{body}</div></section>')


def _meta_row(sop: SOP) -> str:
    fields = [
        ("Department", sop.department_name), ("Version", sop.version),
        ("Owner", sop.owner), ("Effective", sop.effective_date),
        ("Next review", sop.next_review), ("Language", sop.language.upper()),
    ]
    return "".join(
        f'<div class="meta"><div class="meta-lbl">{_esc(k)}</div>'
        f'<div class="meta-val">{_esc(v or "—")}</div></div>'
        for k, v in fields
    )


def render_sop(sop: SOP, results: list[dict], out_path: Path) -> str:
    assessments = _collect(results, sop.sop_id, sop.parent_id)
    overall = _worst([a["status"] for a in assessments])
    ctx = _corpus_context(results, sop.sop_id)

    ctx_html = ""
    if ctx:
        items = "".join(
            f'<div class="ctx"><div class="ctx-t">{_esc(title)}</div><ul class="findings">'
            + "".join(f"<li>{_esc(f)}</li>" for f in hits) + "</ul></div>"
            for title, hits in ctx
        )
        ctx_html = (
            '<section class="card"><div class="card-head"><h2>Corpus context</h2>'
            '<span class="slide">relational analyses</span></div>'
            f'<div class="card-body"><p class="note">Findings from the corpus-wide '
            f'analyses that name this document.</p>{items}</div></section>'
        )

    sections = "".join(_section(a) for a in assessments) or (
        '<section class="card"><div class="card-body">'
        '<p class="note">No per-document assessments were produced for this SOP.</p>'
        "</div></section>")

    doc = (_TEMPLATE
           .replace("__TITLE__", _esc(f"{sop.sop_id} — {sop.title}"))
           .replace("__SOPID__", _esc(sop.sop_id))
           .replace("__SOPTITLE__", _esc(sop.title))
           .replace("__OVERALL__", _badge(overall))
           .replace("__META__", _meta_row(sop))
           .replace("__CTX__", ctx_html)
           .replace("__SECTIONS__", sections))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return overall


def render_index(rows: list[dict], out_path: Path) -> Path:
    counts = {k: sum(1 for r in rows if r["overall"] == k) for k in ("fail", "warn", "pass", "n/a")}
    stat = "".join(
        f'<div class="hstat"><div class="hstat-val">{v}</div>'
        f'<div class="hstat-lbl">{_esc(_LABEL.get(k, k))}</div></div>'
        for k, v in counts.items() if v
    )
    body = "".join(
        f'<a class="row" href="{_esc(r["file"])}">'
        f'<span class="rid">{_esc(r["sop_id"])}</span>'
        f'<span class="rtitle">{_esc(r["title"])}</span>'
        f'<span class="rdept">{_esc(r["department"])}</span>'
        f'{_badge(r["overall"])}</a>'
        for r in rows
    )
    doc = (_INDEX_TEMPLATE
           .replace("__STATS__", stat)
           .replace("__ROWS__", body)
           .replace("__N__", str(len(rows))))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path


def render_all(corpus: Corpus, results: list[dict], outdir: Path) -> tuple[Path, list[dict]]:
    """Write one dossier per SOP plus the index. Returns (index_path, rows)."""
    sops_dir = Path(outdir) / "sops"
    rows = []
    # Worst documents first — that is the remediation queue.
    for sop in sorted(corpus, key=lambda s: s.sop_id):
        fname = f"{sop.sop_id}.html"
        overall = render_sop(sop, results, sops_dir / fname)
        rows.append({"sop_id": sop.sop_id, "title": sop.title,
                     "department": sop.department_name, "overall": overall, "file": fname})
    rows.sort(key=lambda r: (-_SEVERITY.get(r["overall"], 0), r["sop_id"]))
    index = render_index(rows, sops_dir / "index.html")
    return index, rows


_CSS = """
:root{--ink:#16232E;--muted:#5c6f7d;--line:#dce4e9;--bg:#f4f7f9;--panel:#fff;
 --primary:#0B3C5D;--secondary:#1C7293;--accent:#E8833A;--good:#2E7D5B;--warn:#B9852B;--bad:#C1442E;
 --shadow:0 1px 3px rgba(16,35,46,.08),0 8px 24px rgba(16,35,46,.06);}
@media (prefers-color-scheme:dark){:root{--ink:#e8eef2;--muted:#93a4b1;--line:#243642;--bg:#0e1a22;
 --panel:#152530;--primary:#5AA9C6;--secondary:#7cc0d8;--accent:#F0A15C;--good:#5cbf8f;--warn:#e0b154;--bad:#e08072;
 --shadow:0 1px 3px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);}}
:root[data-theme="dark"]{--ink:#e8eef2;--muted:#93a4b1;--line:#243642;--bg:#0e1a22;--panel:#152530;
 --primary:#5AA9C6;--secondary:#7cc0d8;--accent:#F0A15C;--good:#5cbf8f;--warn:#e0b154;--bad:#e08072;}
:root[data-theme="light"]{--ink:#16232E;--muted:#5c6f7d;--line:#dce4e9;--bg:#f4f7f9;--panel:#fff;
 --primary:#0B3C5D;--secondary:#1C7293;--accent:#E8833A;--good:#2E7D5B;--warn:#B9852B;--bad:#C1442E;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.5;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:inherit;text-decoration:none}
.wrap{max-width:1060px;margin:0 auto;padding:0 20px}
header.top{background:linear-gradient(135deg,var(--primary),var(--secondary));color:#fff;padding:30px 0 26px}
header.top .eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;opacity:.85;font-weight:600}
header.top h1{margin:.25em 0 .1em;font-size:26px;font-weight:750;line-height:1.2}
header.top .sub{opacity:.92;font-size:15px}
.back{display:inline-block;margin-top:14px;font-size:12.5px;opacity:.9;border:1px solid rgba(255,255,255,.35);
 padding:5px 11px;border-radius:20px}
.metas{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}
.meta{background:rgba(255,255,255,.13);border:1px solid rgba(255,255,255,.18);border-radius:10px;padding:8px 13px;min-width:104px}
.meta-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.08em;opacity:.85}
.meta-val{font-size:14px;font-weight:650}
main{padding:26px 0 60px;display:grid;gap:18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}
.card-head{display:flex;align-items:center;gap:12px;padding:15px 20px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.card-head h2{margin:0;font-size:17px;font-weight:700;flex:1}
.card-head .slide{font-size:11px;color:var(--muted);background:var(--bg);border:1px solid var(--line);padding:3px 9px;border-radius:20px}
.card-body{padding:17px 20px}
.badge{font-size:11px;font-weight:700;padding:4px 11px;border-radius:20px;white-space:nowrap;
 text-transform:uppercase;letter-spacing:.04em;border:1px solid}
.badge.fail{color:var(--bad);border-color:var(--bad);background:color-mix(in srgb,var(--bad) 12%,transparent)}
.badge.warn{color:var(--warn);border-color:var(--warn);background:color-mix(in srgb,var(--warn) 12%,transparent)}
.badge.pass{color:var(--good);border-color:var(--good);background:color-mix(in srgb,var(--good) 12%,transparent)}
.badge.na{color:var(--muted);border-color:var(--line);background:var(--bg)}
.chips{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:14px}
.chip{background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:8px 12px;min-width:84px}
.chip-val{display:block;font-size:17px;font-weight:750;color:var(--secondary)}
.chip-lbl{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
ul.findings{margin:0 0 12px;padding-left:0;list-style:none;display:grid;gap:6px}
ul.findings li{position:relative;padding-left:20px;font-size:14px}
ul.findings li:before{content:"";position:absolute;left:3px;top:8px;width:7px;height:7px;border-radius:50%;background:var(--accent)}
.figure{display:flex;flex-wrap:wrap;gap:12px;margin:6px 0 10px}
.figure img{max-width:100%;border:1px solid var(--line);border-radius:10px;background:#fff}
.artifacts{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}
.afile{font-size:11.5px;font-family:ui-monospace,Menlo,Consolas,monospace;background:var(--bg);
 border:1px solid var(--line);border-radius:6px;padding:3px 8px;color:var(--muted)}
details.doc,details.tbl-wrap{margin-top:10px;border:1px solid var(--line);border-radius:9px;overflow:hidden}
details.doc summary,details.tbl-wrap summary{cursor:pointer;padding:9px 13px;font-size:13px;font-weight:600;
 background:var(--bg);color:var(--secondary);list-style:none}
details summary::-webkit-details-marker{display:none}
details.doc summary:before,details.tbl-wrap summary:before{content:"▸ ";color:var(--muted)}
details[open] summary:before{content:"▾ "}
details.doc pre{margin:0;padding:13px;overflow-x:auto;font-size:12px;line-height:1.45;
 font-family:ui-monospace,Menlo,Consolas,monospace;max-height:460px}
.tbl-note{font-size:11px;color:var(--muted);padding:6px 13px 0}
.tbl-scroll{overflow-x:auto;max-height:420px;overflow-y:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px}
thead th{position:sticky;top:0;background:var(--panel);text-align:left;padding:8px 11px;border-bottom:2px solid var(--line);
 font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);white-space:nowrap}
tbody td{padding:7px 11px;border-bottom:1px solid var(--line);vertical-align:top}
td.good{color:var(--good);font-weight:600}td.warn{color:var(--warn);font-weight:600}td.bad{color:var(--bad);font-weight:600}
.note{font-size:13px;color:var(--muted);margin:0 0 10px}
.ctx{margin-bottom:12px}
.ctx-t{font-size:12px;font-weight:700;color:var(--secondary);text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}
footer{border-top:1px solid var(--line);padding:20px 0;color:var(--muted);font-size:12.5px}
.hstats{display:flex;flex-wrap:wrap;gap:12px;margin-top:18px}
.hstat{background:rgba(255,255,255,.13);border:1px solid rgba(255,255,255,.18);border-radius:11px;padding:10px 15px;min-width:104px}
.hstat-val{font-size:22px;font-weight:750}
.hstat-lbl{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;opacity:.85}
.row{display:flex;align-items:center;gap:13px;padding:11px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
.row:hover{background:var(--bg)}
.row:first-of-type{border-top-left-radius:14px;border-top-right-radius:14px}
.row:last-of-type{border-bottom:0;border-bottom-left-radius:14px;border-bottom-right-radius:14px}
.rid{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;font-weight:700;color:var(--secondary);white-space:nowrap}
.rtitle{flex:1;font-size:14px;min-width:180px}
.rdept{font-size:11.5px;color:var(--muted);white-space:nowrap}
.list{border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}
@media(max-width:640px){.rdept{display:none}.rtitle{min-width:0}}
.theme-toggle{position:fixed;bottom:18px;right:18px;z-index:20;background:var(--panel);border:1px solid var(--line);
 border-radius:50%;width:42px;height:42px;box-shadow:var(--shadow);cursor:pointer;font-size:17px}
"""

_TOGGLE = ("""<button class="theme-toggle" title="Toggle light/dark" onclick="(function(){var r=document.documentElement;"""
           """var c=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');"""
           """r.setAttribute('data-theme',c==='dark'?'light':'dark');})()">◑</button>""")

_TEMPLATE = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title><style>{_CSS}</style></head><body>
<header class="top"><div class="wrap">
  <div class="eyebrow">SOP Assessment · Meridian Pharmaceuticals · Building 4</div>
  <h1>__SOPID__ &nbsp;__OVERALL__</h1>
  <div class="sub">__SOPTITLE__</div>
  <div class="metas">__META__</div>
  <a class="back" href="index.html">&larr; All SOP assessments</a>
</div></header>
<div class="wrap"><main>__SECTIONS____CTX__</main></div>
<footer><div class="wrap">Confidential · Per-document assessment generated by the SOP Quality
 Transformation pipeline. AI suggests; humans decide.</div></footer>
{_TOGGLE}</body></html>"""

_INDEX_TEMPLATE = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Per-SOP Assessments — Meridian Pharmaceuticals</title><style>{_CSS}</style></head><body>
<header class="top"><div class="wrap">
  <div class="eyebrow">Meridian Pharmaceuticals · Building 4 · Sterile Fill-Finish</div>
  <h1>Per-SOP Assessments</h1>
  <div class="sub">__N__ documents, each with its own quality record. Ordered worst-first —
    this is the remediation queue.</div>
  <div class="hstats">__STATS__</div>
  <a class="back" href="../report/index.html">&larr; Corpus dashboard</a>
</div></header>
<div class="wrap"><main><div class="list">__ROWS__</div></main></div>
<footer><div class="wrap">Confidential · Illustrative results on a fictional corpus.</div></footer>
{_TOGGLE}</body></html>"""
