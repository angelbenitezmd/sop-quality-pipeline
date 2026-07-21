"""Render the pipeline results into a single self-contained HTML dashboard.

The dashboard embeds every chart PNG as a base64 data URI so the file is portable
(no external assets). It is theme-aware (light/dark) and responsive.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from .core.corpus import PROJECT_ROOT

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
}


def _data_uri(path: Path) -> str | None:
    if not path.exists():
        return None
    mime = MIME.get(path.suffix.lower(), "application/octet-stream")
    b = path.read_bytes()
    return f"data:{mime};base64," + base64.b64encode(b).decode("ascii")


def _esc(x) -> str:
    return html.escape(str(x), quote=True)


def _render_summary_chips(summary: dict) -> str:
    if not summary:
        return ""
    chips = []
    for k, v in summary.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, default=str)
        label = _esc(k.replace("_", " ").title())
        val = _esc(v)
        chips.append(f'<div class="chip"><span class="chip-val">{val}</span><span class="chip-lbl">{label}</span></div>')
    return '<div class="chips">' + "".join(chips) + "</div>"


def _render_findings(findings: list) -> str:
    if not findings:
        return ""
    items = "".join(f"<li>{_esc(f)}</li>" for f in findings)
    return f'<ul class="findings">{items}</ul>'


def _render_table(table: list, columns: list | None) -> str:
    if not table:
        return ""
    if not columns:
        columns = list(table[0].keys())
    thead = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in columns)
    rows = []
    for r in table:
        cells = []
        for c in columns:
            val = r.get(c, "")
            if isinstance(val, float):
                val = f"{val:.3f}" if abs(val) < 100 else f"{val:.1f}"
            cell = _esc(val)
            cls = ""
            low = str(val).strip().lower()
            if low in ("outdated", "fail", "broken", "absent", "over-documented", "deviating"):
                cls = ' class="bad"'
            elif low in ("review", "under-documented", "warn"):
                cls = ' class="warn"'
            elif low in ("current", "pass", "adequate", "conforming", "none"):
                cls = ' class="good"'
            cells.append(f"<td{cls}>{cell}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    n = len(table)
    body = "".join(rows)
    detail = ""
    if n > 12:
        # keep it compact: show all but wrap in a scroll box
        detail = f'<div class="tbl-note">{n} rows</div>'
    return (
        f'<details class="tbl-wrap"><summary>Data table ({n} rows)</summary>'
        f'{detail}<div class="tbl-scroll"><table><thead><tr>{thead}</tr></thead>'
        f"<tbody>{body}</tbody></table></div></details>"
    )


def _render_artifacts(artifacts: list) -> str:
    """Embed images; list non-image artifacts as chips."""
    img_html = []
    other = []
    for a in artifacts or []:
        p = (PROJECT_ROOT / a) if not Path(a).is_absolute() else Path(a)
        ext = p.suffix.lower()
        if ext in IMG_EXT:
            uri = _data_uri(p)
            if uri:
                img_html.append(f'<img loading="lazy" src="{uri}" alt="{_esc(p.name)}">')
        else:
            other.append(p.name)
    out = ""
    if img_html:
        out += '<div class="figure">' + "".join(img_html) + "</div>"
    if other:
        out += '<div class="artifacts">' + "".join(
            f'<span class="afile">{_esc(name)}</span>' for name in other
        ) + "</div>"
    return out


def _card(result: dict) -> str:
    num = str(result.get("module", "")).split("_")[0].replace("m", "").lstrip("0") or "0"
    title = _esc(result.get("title", result.get("module", "")))
    slide = result.get("slide", "")
    slide_badge = f'<span class="slide">deck&nbsp;slide&nbsp;{_esc(slide)}</span>' if slide else ""
    # Show whether this capability also produces a per-document assessment.
    scope = str(result.get("scope", "")).lower()
    n_per_sop = len(result.get("per_sop") or {})
    if scope in ("per_sop", "both") and n_per_sop:
        label = "per-SOP + corpus" if scope == "both" else "per-SOP"
        slide_badge = (f'<span class="slide scoped">{label} · {n_per_sop} assessed</span>'
                       + slide_badge)
    elif scope == "corpus":
        slide_badge = '<span class="slide">corpus-wide</span>' + slide_badge
    err = result.get("_error")
    body = ""
    if err:
        body = f'<div class="err">Module error: {_esc(err)}</div>'
    else:
        body += _render_summary_chips(result.get("summary", {}))
        body += _render_findings(result.get("key_findings", []))
        body += _render_artifacts(result.get("artifacts", []))
        body += _render_table(result.get("table", []), result.get("table_columns"))
    return (
        f'<section class="card" id="{_esc(result.get("module",""))}">'
        f'<div class="card-head"><span class="num">{_esc(num)}</span>'
        f'<h2>{title}</h2>{slide_badge}</div>'
        f'<div class="card-body">{body}</div></section>'
    )


def render(results: list, corpus_stats: dict, out_path: Path) -> Path:
    cards = "\n".join(_card(r) for r in results)
    nav = "".join(
        f'<a href="#{_esc(r.get("module",""))}">'
        f'<span>{_esc(str(r.get("module","")).split("_")[0].replace("m","").lstrip("0") or "0")}</span>'
        f'{_esc(r.get("title", r.get("module","")))}</a>'
        for r in results
    )
    stat_chips = "".join(
        f'<div class="hstat"><div class="hstat-val">{_esc(v)}</div><div class="hstat-lbl">{_esc(k)}</div></div>'
        for k, v in corpus_stats.items()
    )
    tpl = _TEMPLATE
    doc = (
        tpl.replace("__CARDS__", cards)
        .replace("__NAV__", nav)
        .replace("__STATS__", stat_chips)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meridian Pharmaceuticals — SOP Quality Transformation Pipeline</title>
<style>
:root{
  --ink:#16232E; --muted:#5c6f7d; --line:#dce4e9; --bg:#f4f7f9; --panel:#ffffff;
  --primary:#0B3C5D; --secondary:#1C7293; --tertiary:#5AA9C6; --accent:#E8833A;
  --good:#2E7D5B; --warn:#B9852B; --bad:#C1442E; --shadow:0 1px 3px rgba(16,35,46,.08),0 8px 24px rgba(16,35,46,.06);
}
@media (prefers-color-scheme: dark){
  :root{ --ink:#e8eef2; --muted:#93a4b1; --line:#243642; --bg:#0e1a22; --panel:#152530;
    --primary:#5AA9C6; --secondary:#7cc0d8; --tertiary:#9fd0e0; --accent:#F0A15C;
    --good:#5cbf8f; --warn:#e0b154; --bad:#e08072; --shadow:0 1px 3px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);}
}
:root[data-theme="dark"]{ --ink:#e8eef2; --muted:#93a4b1; --line:#243642; --bg:#0e1a22; --panel:#152530;
  --primary:#5AA9C6; --secondary:#7cc0d8; --tertiary:#9fd0e0; --accent:#F0A15C; --good:#5cbf8f; --warn:#e0b154; --bad:#e08072;}
:root[data-theme="light"]{ --ink:#16232E; --muted:#5c6f7d; --line:#dce4e9; --bg:#f4f7f9; --panel:#ffffff;
  --primary:#0B3C5D; --secondary:#1C7293; --tertiary:#5AA9C6; --accent:#E8833A; --good:#2E7D5B; --warn:#B9852B; --bad:#C1442E;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;line-height:1.5}
a{color:inherit;text-decoration:none}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
header.top{background:linear-gradient(135deg,var(--primary),var(--secondary));color:#fff;padding:44px 0 38px}
:root[data-theme="dark"] header.top,@media (prefers-color-scheme:dark){}
header.top .eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:12px;opacity:.85;font-weight:600}
header.top h1{margin:.3em 0 .15em;font-size:30px;font-weight:750;line-height:1.15}
header.top .sub{opacity:.9;font-size:15px;max-width:70ch}
.hstats{display:flex;flex-wrap:wrap;gap:14px;margin-top:26px}
.hstat{background:rgba(255,255,255,.13);border:1px solid rgba(255,255,255,.18);border-radius:12px;
  padding:12px 16px;min-width:120px}
.hstat-val{font-size:24px;font-weight:750}
.hstat-lbl{font-size:11px;text-transform:uppercase;letter-spacing:.08em;opacity:.85}
nav.toc{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);
  box-shadow:var(--shadow)}
nav.toc .wrap{display:flex;gap:6px;overflow-x:auto;padding:10px 20px}
nav.toc a{flex:0 0 auto;font-size:12px;color:var(--muted);padding:6px 10px;border-radius:8px;white-space:nowrap;
  display:flex;align-items:center;gap:6px;border:1px solid transparent}
nav.toc a:hover{background:var(--bg);color:var(--ink);border-color:var(--line)}
nav.toc a span{display:inline-flex;width:20px;height:20px;align-items:center;justify-content:center;
  background:var(--primary);color:#fff;border-radius:50%;font-size:11px;font-weight:700}
main{padding:30px 0 60px;display:grid;gap:22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);overflow:hidden}
.card-head{display:flex;align-items:center;gap:14px;padding:18px 22px;border-bottom:1px solid var(--line)}
.card-head .num{flex:0 0 auto;width:34px;height:34px;border-radius:10px;background:var(--primary);color:#fff;
  display:flex;align-items:center;justify-content:center;font-weight:750;font-size:16px}
.card-head h2{margin:0;font-size:19px;font-weight:700;flex:1}
.card-head .slide{font-size:11px;color:var(--muted);background:var(--bg);border:1px solid var(--line);
  padding:4px 9px;border-radius:20px;white-space:nowrap}
.card-head .scoped{color:var(--secondary);border-color:var(--secondary);font-weight:600;margin-right:6px}
.jump{display:inline-block;margin-top:18px;font-size:13px;font-weight:600;color:#fff;
  border:1px solid rgba(255,255,255,.4);padding:8px 15px;border-radius:22px;text-decoration:none}
.jump:hover{background:rgba(255,255,255,.14)}
.card-body{padding:20px 22px}
.chips{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.chip{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:9px 13px;min-width:90px}
.chip-val{display:block;font-size:19px;font-weight:750;color:var(--secondary)}
.chip-lbl{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
ul.findings{margin:0 0 16px;padding-left:0;list-style:none;display:grid;gap:7px}
ul.findings li{position:relative;padding-left:22px;font-size:14px}
ul.findings li:before{content:"";position:absolute;left:4px;top:8px;width:8px;height:8px;border-radius:50%;
  background:var(--accent)}
.figure{display:flex;flex-wrap:wrap;gap:14px;justify-content:flex-start;margin:6px 0 10px}
.figure img{max-width:100%;width:100%;border:1px solid var(--line);border-radius:12px;background:#fff}
.artifacts{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}
.afile{font-size:11.5px;font-family:ui-monospace,Menlo,Consolas,monospace;background:var(--bg);
  border:1px solid var(--line);border-radius:6px;padding:3px 8px;color:var(--muted)}
details.tbl-wrap{margin-top:12px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
details.tbl-wrap summary{cursor:pointer;padding:10px 14px;font-size:13px;font-weight:600;background:var(--bg);
  color:var(--secondary);list-style:none}
details.tbl-wrap summary::-webkit-details-marker{display:none}
details.tbl-wrap summary:before{content:"▸ ";color:var(--muted)}
details.tbl-wrap[open] summary:before{content:"▾ "}
.tbl-note{font-size:11px;color:var(--muted);padding:6px 14px 0}
.tbl-scroll{overflow-x:auto;max-height:440px;overflow-y:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px}
thead th{position:sticky;top:0;background:var(--panel);text-align:left;padding:9px 12px;border-bottom:2px solid var(--line);
  font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);white-space:nowrap}
tbody td{padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:hover{background:var(--bg)}
td.good{color:var(--good);font-weight:600}
td.warn{color:var(--warn);font-weight:600}
td.bad{color:var(--bad);font-weight:600}
.err{color:var(--bad);font-weight:600;font-size:14px}
footer{border-top:1px solid var(--line);padding:24px 0;color:var(--muted);font-size:12.5px}
.theme-toggle{position:fixed;bottom:18px;right:18px;z-index:20;background:var(--panel);border:1px solid var(--line);
  border-radius:50%;width:44px;height:44px;box-shadow:var(--shadow);cursor:pointer;font-size:18px}
@media(min-width:820px){ .figure img{max-width:640px} }
</style>
</head>
<body>
<header class="top"><div class="wrap">
  <div class="eyebrow">Meridian Pharmaceuticals · Building 4 · Sterile Fill-Finish</div>
  <h1>AI-Powered SOP Quality Transformation — Pipeline Results</h1>
  <div class="sub">Thirteen capabilities run against a mock manufacturing SOP corpus. AI suggests; humans decide.
    Every finding below is computed from the SOP text — similarity, readability, regulatory currency, dependencies,
    coverage, and quality scoring.</div>
  <div class="hstats">__STATS__</div>
  <a class="jump" href="../sops/index.html">View per-SOP assessments &rarr;</a>
</div></header>
<nav class="toc"><div class="wrap">__NAV__</div></nav>
<div class="wrap"><main>__CARDS__</main></div>
<footer><div class="wrap">Confidential · Illustrative results on a fictional corpus for demonstration.
  Generated by the SOP Quality Transformation pipeline.</div></footer>
<button class="theme-toggle" title="Toggle light/dark" onclick="(function(){var r=document.documentElement;
  var cur=r.getAttribute('data-theme')|| (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
  r.setAttribute('data-theme', cur==='dark'?'light':'dark');})()">◑</button>
</body>
</html>"""
