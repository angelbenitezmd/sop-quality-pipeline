#!/usr/bin/env python3
"""Turn the mock Markdown SOP corpus into digital-native pharmaceutical SOP PDFs.

These are *test fixtures* for validating a PDF ingest stage: they are real,
text-extractable PDFs (Type42 embedded fonts, so ``pdftotext`` recovers the text
rather than seeing a scanned image), and they deliberately reproduce the page
furniture that makes real SOP PDFs painful to parse:

  * a controlled-document cover page with labelled metadata fields
    ("Document No.: SOP-CLN-001", "Version: 4.1", ...) and an approval table
  * a table of contents with dotted leaders and page numbers
  * a running header on EVERY page:  "<SOP-ID>   Rev <version>   <title...>"
  * a running footer on EVERY page:  "Page N of M   Effective <date>
    CONFIDENTIAL - Meridian Pharmaceuticals"
  * body text that reflows across page boundaries, with at least one numbered
    procedure whose steps SPLIT across a page break
  * soft hyphenation, so at least one word is broken across a line break
    ("steriliza-" / "tion") -- the classic de-hyphenation trap

Everything is deterministic: no timestamps, no randomness, fixed PDF metadata,
so the same Markdown input always yields the same extracted text.

Usage
-----
    python3 tools/make_test_pdfs.py --out <dir> [--limit N] [--verify]

Nothing is ever written into the repository: fixtures belong in a scratch dir.
This script only *reads* data/sops/ and sop_pipeline/; it never modifies them.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Project wiring
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_OUT = Path(
    "/private/tmp/claude-501/-Users-angelbenitez-Desktop-SOP-Project/"
    "16175c83-1c11-4c7a-a1a1-5ffbdc8fb488/scratchpad/test_pdfs"
)

try:
    from sop_pipeline.core.corpus import SOP, load_corpus
except Exception as exc:  # pragma: no cover - environment problem
    raise SystemExit(
        f"Cannot import sop_pipeline.core.corpus from {PROJECT_ROOT}: {exc}"
    )

import matplotlib

matplotlib.use("Agg")
# fonttype 42 => embed TrueType subsets with a ToUnicode CMap, so the PDF holds
# real selectable text instead of vector paths.  This is the whole reason the
# fixtures are "digital native".
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
matplotlib.rcParams["pdf.use14corefonts"] = False
matplotlib.rcParams["pdf.compression"] = 6

from matplotlib.backends.backend_pdf import FigureCanvasPdf, PdfPages  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

try:  # matplotlib >= 3.10
    from matplotlib.ft2font import FT2Font, LoadFlags

    _NO_HINTING = LoadFlags.NO_HINTING
except ImportError:  # pragma: no cover - older matplotlib
    from matplotlib.ft2font import FT2Font, LOAD_NO_HINTING as _NO_HINTING

# --------------------------------------------------------------------------
# Page geometry -- US Letter, all units in PostScript points (1/72 in)
# --------------------------------------------------------------------------

PAGE_W, PAGE_H = 612.0, 792.0
MARGIN_L = 84.0          # slightly wide: binding margin, like a real QMS doc
MARGIN_R = 72.0
TEXT_W = PAGE_W - MARGIN_L - MARGIN_R          # 456 pt
RIGHT_X = PAGE_W - MARGIN_R

HEADER_BASE = 750.0      # baseline of the running header
HEADER_RULE_Y = 742.0
CONTENT_TOP = 722.0      # baseline of the first body line on a page
CONTENT_BOTTOM = 84.0    # lowest allowed baseline
FOOTER_RULE_Y = 66.0
FOOTER_BASE = 52.0

BODY_SIZE = 10.5
BODY_LEAD = 14.6
HEAD_SIZE = 12.0
HEAD_LEAD = 16.0
FURNITURE_SIZE = 8.0
TABLE_SIZE = 9.0
TABLE_LEAD = 12.4
TOC_SIZE = 10.0
TOC_LEAD = 14.0

INK = "#111111"
RULE = "#555555"
FAINT = "#777777"

COMPANY = "Meridian Pharmaceuticals"
CONFIDENTIALITY = f"CONFIDENTIAL — {COMPANY}"

# Fixed metadata date: determinism beats freshness for a test fixture.
FIXED_DATE = datetime(2024, 1, 1, 0, 0, 0)

FONT_FILES = {
    "serif": "DejaVuSerif.ttf",
    "serif-b": "DejaVuSerif-Bold.ttf",
    "serif-i": "DejaVuSerif-Italic.ttf",
    "sans": "DejaVuSans.ttf",
    "sans-b": "DejaVuSans-Bold.ttf",
}


# --------------------------------------------------------------------------
# Font metrics
# --------------------------------------------------------------------------


class FontBook:
    """Deterministic text measurement against matplotlib's bundled DejaVu fonts.

    Widths come straight from the font's horizontal advances, so measurement and
    rendering agree and never depend on system font availability.  Kerning is
    ignored, which only ever makes the rendered line *narrower* than measured --
    safe for line breaking.
    """

    def __init__(self) -> None:
        ttf_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        self._paths = {k: ttf_dir / v for k, v in FONT_FILES.items()}
        for key, path in self._paths.items():
            if not path.exists():  # pragma: no cover
                raise SystemExit(f"Missing bundled font for {key!r}: {path}")
        self._faces: dict[str, FT2Font] = {}
        self._advances: dict[tuple[str, float], dict[str, float]] = {}
        self._props: dict[tuple[str, float], FontProperties] = {}

    def path(self, key: str) -> Path:
        return self._paths[key]

    def props(self, key: str, size: float) -> FontProperties:
        ck = (key, size)
        if ck not in self._props:
            self._props[ck] = FontProperties(fname=str(self._paths[key]), size=size)
        return self._props[ck]

    def _face(self, key: str) -> FT2Font:
        if key not in self._faces:
            self._faces[key] = FT2Font(str(self._paths[key]))
        return self._faces[key]

    def _advance(self, ch: str, key: str, size: float) -> float:
        table = self._advances.setdefault((key, size), {})
        if ch not in table:
            face = self._face(key)
            face.set_size(size, 72)
            try:
                glyph = face.load_char(ord(ch), flags=_NO_HINTING)
                table[ch] = glyph.linearHoriAdvance / 65536.0
            except Exception:  # pragma: no cover - undefined glyph
                table[ch] = size * 0.5
        return table[ch]

    def width(self, text: str, key: str = "serif", size: float = BODY_SIZE) -> float:
        return sum(self._advance(c, key, size) for c in text)


FONTS = FontBook()


# --------------------------------------------------------------------------
# Line breaking + soft hyphenation
# --------------------------------------------------------------------------

_VOWELS = set("aeiouyAEIOUYáéíóúüÁÉÍÓÚÜ")
# A token that is one run of letters, optionally wrapped in punctuation.
# Deliberately rejects "strike-through" and "SOP-QC-006": already-hyphenated and
# identifier-like tokens must never be broken again.
_WORD_CORE = re.compile(r"^(\W*)([^\W\d_]+)(\W*)$")


def _is_vowel(ch: str) -> bool:
    return ch in _VOWELS


@dataclass
class WrapConfig:
    """How eagerly to break words across lines."""

    min_fill: float = 0.62   # only hyphenate once the line is this full
    min_word: int = 9        # only hyphenate words at least this long
    min_head: int = 3        # minimum characters left before the hyphen
    min_tail: int = 3        # minimum characters carried to the next line
    relaxed: bool = False    # last resort: allow breaks the rules would reject


def _hyphen_split(
    word: str, avail: float, key: str, size: float, cfg: WrapConfig
) -> tuple[str, str] | None:
    """Split ``word`` into ("stem-", "tail") if a sensible break fits in ``avail``.

    A two-rule imitation of English hyphenation rather than a dictionary
    hyphenator -- enough to produce breaks a reader would accept:

      VC|CV  split between two consonants that sit between vowels
             ("accor-dance", "elec-tronic", "confir-mation")
      V|CV   split after a vowel followed by a single consonant
             ("steriliza-tion", "sporici-dal")

    Positions matching neither rule are rejected outright, so the fixture never
    contains nonsense like "clea-nrooms" -- unless ``cfg.relaxed`` is set, which
    is the last-resort pass used on terse SOPs that would otherwise contain no
    hyphenated break at all.  Real SOP PDFs are full of these breaks and any
    ingest stage has to stitch them back together.
    """
    # Strip surrounding punctuation so "records," can still break as "rec-ords,".
    m = _WORD_CORE.match(word)
    if not m:
        return None                           # digits, "strike-through", "SOP-QC-006"
    lead, core, trail = m.groups()
    if len(core) < cfg.min_word or core.isupper():
        return None
    lead_w = FONTS.width(lead, key, size)
    hyphen_w = FONTS.width("-", key, size)
    best: tuple[int, int] | None = None       # (rank, k)
    upper = len(core) - cfg.min_tail
    for k in range(max(cfg.min_head, 2), upper + 1):
        if lead_w + FONTS.width(core[:k], key, size) + hyphen_w > avail:
            break
        if not (set(core[:k]) & _VOWELS) or not (set(core[k:]) & _VOWELS):
            continue
        rank = 0
        if _is_vowel(core[k - 2]) and not _is_vowel(core[k - 1]) \
                and not _is_vowel(core[k]):
            rank = 2                          # VC|CV
        elif _is_vowel(core[k - 1]) and not _is_vowel(core[k]) \
                and k + 1 < len(core) and _is_vowel(core[k + 1]):
            rank = 1                          # V|CV
        if (rank or cfg.relaxed) and (best is None or (rank, k) > best):
            best = (rank, k)
    if best is None:
        return None
    k = best[1]
    return lead + core[:k] + "-", core[k:] + trail


def wrap(
    text: str,
    width: float,
    key: str = "serif",
    size: float = BODY_SIZE,
    cfg: WrapConfig | None = None,
    counter: list[int] | None = None,
) -> list[str]:
    """Greedy line breaker with optional soft hyphenation.

    ``cfg=None`` disables hyphenation entirely -- used for page furniture
    (cover title, table cells) where a broken word would look wrong.
    ``counter`` (a one-element list) is incremented once per hyphenated break so
    the caller can assert the fixture really contains one.
    """
    words = text.split()
    if not words:
        return [""]
    space_w = FONTS.width(" ", key, size)
    lines: list[str] = []
    cur: list[str] = []
    cur_w = 0.0

    def flush() -> None:
        nonlocal cur, cur_w
        if cur:
            lines.append(" ".join(cur))
        cur, cur_w = [], 0.0

    i = 0
    while i < len(words):
        word = words[i]
        w = FONTS.width(word, key, size)
        gap = space_w if cur else 0.0
        if cur_w + gap + w <= width:
            cur.append(word)
            cur_w += gap + w
            i += 1
            continue
        avail = width - cur_w - gap
        if cfg is not None and cur and cur_w >= width * cfg.min_fill:
            split = _hyphen_split(word, avail, key, size, cfg)
            if split is not None:
                head, tail = split
                cur.append(head)
                flush()
                if counter is not None:
                    counter[0] += 1
                words[i] = tail
                continue
        if not cur:
            # A single unbreakable token wider than the column: let it overhang.
            cur.append(word)
            i += 1
        flush()
    flush()
    return lines


# --------------------------------------------------------------------------
# Markdown -> block model
# --------------------------------------------------------------------------

_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")
_ROMAN_HEADING = re.compile(r"^\s{0,3}([IVXL]{1,6}\.)\s+(\S.*)$")
_ITEM = re.compile(r"^(\s*)(\d{1,2})[.)]\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*•]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


def _is_caps_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if sum(c.isalpha() for c in s) < 4:
        return False
    if s != s.upper():
        return False
    return bool(re.match(r"^(\d+(\.\d+)*\.?\s+)?[A-ZÁÉÍÓÚÑ"
                         r"0-9][A-ZÁÉÍÓÚÑ0-9 &/\-,()+.]*$", s))


@dataclass
class Block:
    kind: str                     # heading | para | item | bullet | table
    text: str = ""
    marker: str = ""
    group: str = ""
    rows: list[list[str]] = field(default_factory=list)


def parse_blocks(body: str) -> list[Block]:
    """Parse an SOP body into renderable blocks.

    Handles all three heading dialects present in the corpus (``## 3. Title``,
    all-caps ``PURPOSE AND APPLICABILITY``, roman ``VII. Calculation``) plus
    numbered steps, bullets and pipe tables.
    """
    blocks: list[Block] = []
    mode: str | None = None
    buf: list[str] = []
    marker = ""
    rows: list[list[str]] = []
    list_seq = 0
    group = ""

    def flush() -> None:
        nonlocal mode, buf, marker, rows
        if mode in ("para", "item", "bullet") and buf:
            text = " ".join(x.strip() for x in buf).strip()
            if text:
                # Only list items carry list identity; a paragraph that happens to
                # follow a list must not be mistaken for part of it.
                grp = group if mode in ("item", "bullet") else ""
                blocks.append(Block(kind=mode, text=text, marker=marker, group=grp))
        elif mode == "table" and rows:
            blocks.append(Block(kind="table", rows=list(rows)))
        mode, buf, marker, rows = None, [], "", []

    for raw in body.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            flush()
            continue

        if stripped.startswith("|"):
            if mode != "table":
                flush()
                mode = "table"
            if not _TABLE_SEP.match(stripped):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                rows.append(cells)
            continue

        md = _MD_HEADING.match(line)
        if md:
            flush()
            blocks.append(Block(kind="heading", text=md.group(1).strip()))
            continue

        if _is_caps_heading(line):
            flush()
            blocks.append(Block(kind="heading", text=stripped))
            continue

        rom = _ROMAN_HEADING.match(line)
        if rom and len(stripped) <= 80:
            flush()
            blocks.append(Block(kind="heading", text=f"{rom.group(1)} {rom.group(2)}".strip()))
            continue

        item = _ITEM.match(line)
        if item and not item.group(1):
            flush()
            list_seq += 1
            if not blocks or blocks[-1].kind != "item":
                group = f"list-{list_seq}"        # a fresh numbered procedure
            mode = "item"
            marker = f"{item.group(2)}."
            buf = [item.group(3)]
            continue

        bullet = _BULLET.match(line)
        if bullet and not bullet.group(1):
            flush()
            list_seq += 1
            if not blocks or blocks[-1].kind != "bullet":
                group = f"list-{list_seq}"        # a fresh bulleted run
            mode = "bullet"
            marker = "•"
            buf = [bullet.group(2)]
            continue

        if mode in ("item", "bullet") and raw[:1].isspace():
            buf.append(stripped)
            continue

        if mode not in ("para",):
            flush()
            mode = "para"
            buf = []
        buf.append(stripped)

    flush()
    return blocks


# --------------------------------------------------------------------------
# Atom model -- one atom is one baseline's worth of page
# --------------------------------------------------------------------------


@dataclass
class Piece:
    x: float                      # offset from MARGIN_L, or from right edge if ha='right'
    text: str
    font: str = "serif"
    size: float = BODY_SIZE
    ha: str = "left"
    color: str = INK


@dataclass
class Atom:
    kind: str                     # line | rule | gap | break
    height: float = 0.0
    pieces: list[Piece] = field(default_factory=list)
    x0: float = 0.0
    x1: float = TEXT_W
    lw: float = 0.6
    color: str = RULE
    keep_next: int = 0            # keep this many following atoms on the same page
    group: str = ""               # numbered-list identity, for the split check
    item_start: bool = False
    heading_ref: int = -1         # index into the headings list (for the TOC)
    toc_ref: int = -1             # TOC row -> heading index (page number patched later)


def line_atom(text: str, x: float = 0.0, font: str = "serif", size: float = BODY_SIZE,
              lead: float = BODY_LEAD, **kw) -> Atom:
    return Atom(kind="line", height=lead, pieces=[Piece(x, text, font, size)], **kw)


def gap(height: float) -> Atom:
    return Atom(kind="gap", height=height)


# --------------------------------------------------------------------------
# Body layout
# --------------------------------------------------------------------------

ITEM_INDENT = 24.0
BULLET_INDENT = 16.0


def _table_atoms(rows: list[list[str]]) -> list[Atom]:
    """Lay out a pipe table as a ruled grid of column-aligned text."""
    if not rows:
        return []
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    pad = 8.0
    natural = [
        max(FONTS.width(r[c], "serif", TABLE_SIZE) for r in rows) + pad * 2
        for c in range(ncols)
    ]
    total = sum(natural)
    if total > TEXT_W:
        widest = natural.index(max(natural))
        natural[widest] -= total - TEXT_W
        natural[widest] = max(natural[widest], 90.0)
    xs, acc = [], 0.0
    for w in natural:
        xs.append(acc)
        acc += w

    atoms: list[Atom] = [gap(4.0), Atom(kind="rule", height=2.0, lw=0.9)]
    for ri, row in enumerate(rows):
        font = "serif-b" if ri == 0 else "serif"
        cells = [
            wrap(row[c], natural[c] - pad * 2, font, TABLE_SIZE)
            for c in range(ncols)
        ]
        depth = max(len(c) for c in cells)
        for li in range(depth):
            pieces = [
                Piece(xs[c] + pad, cells[c][li] if li < len(cells[c]) else "",
                      font, TABLE_SIZE)
                for c in range(ncols)
            ]
            atoms.append(Atom(kind="line", height=TABLE_LEAD, pieces=pieces,
                              keep_next=1 if li < depth - 1 else 0))
        atoms.append(Atom(kind="rule", height=2.0,
                          lw=0.9 if ri == 0 else 0.4,
                          color=RULE if ri == 0 else "#999999"))
    atoms.append(gap(6.0))
    return atoms


def _toc_atoms(headings: list[str]) -> list[Atom]:
    atoms: list[Atom] = [
        line_atom("TABLE OF CONTENTS", font="sans-b", size=11.0, lead=18.0, keep_next=2),
        Atom(kind="rule", height=8.0, lw=0.9),
    ]
    for idx, title in enumerate(headings):
        atoms.append(Atom(
            kind="line",
            height=TOC_LEAD,
            pieces=[
                Piece(10.0, title, "serif", TOC_SIZE),
                Piece(0.0, "", "serif", TOC_SIZE),          # dotted leader (filled later)
                Piece(0.0, "--", "serif", TOC_SIZE, ha="right"),
            ],
            toc_ref=idx,
        ))
    atoms.append(gap(10.0))
    atoms.append(Atom(kind="rule", height=14.0, lw=0.9))
    return atoms


def build_body_atoms(sop: SOP, cfg: WrapConfig) -> tuple[list[Atom], list[str], int]:
    """Flow the SOP body into atoms.  Returns (atoms, heading titles, hyphen count)."""
    blocks = parse_blocks(sop.body)
    headings = [b.text for b in blocks if b.kind == "heading"]
    counter = [0]
    atoms: list[Atom] = _toc_atoms(headings)

    hidx = 0
    for block in blocks:
        if block.kind == "heading":
            atoms.append(gap(9.0))
            lines = wrap(block.text, TEXT_W, "serif-b", HEAD_SIZE, cfg, counter)
            for i, ln in enumerate(lines):
                atoms.append(line_atom(
                    ln, font="serif-b", size=HEAD_SIZE, lead=HEAD_LEAD,
                    keep_next=(len(lines) - i) + 1,
                    heading_ref=hidx if i == 0 else -1,
                ))
            atoms.append(gap(3.0))
            hidx += 1

        elif block.kind == "para":
            for ln in wrap(block.text, TEXT_W, "serif", BODY_SIZE, cfg, counter):
                atoms.append(line_atom(ln))
            atoms.append(gap(5.0))

        elif block.kind in ("item", "bullet"):
            indent = ITEM_INDENT if block.kind == "item" else BULLET_INDENT
            lines = wrap(block.text, TEXT_W - indent, "serif", BODY_SIZE, cfg, counter)
            for i, ln in enumerate(lines):
                pieces = []
                if i == 0:
                    pieces.append(Piece(0.0, block.marker, "serif", BODY_SIZE))
                pieces.append(Piece(indent, ln, "serif", BODY_SIZE))
                atoms.append(Atom(
                    kind="line", height=BODY_LEAD, pieces=pieces,
                    group=block.group, item_start=(i == 0),
                    keep_next=1 if i == 0 and len(lines) > 1 else 0,
                ))
            atoms.append(gap(3.0))

        elif block.kind == "table":
            atoms.extend(_table_atoms(block.rows))

    atoms.append(gap(12.0))
    atoms.append(Atom(kind="rule", height=10.0, lw=0.9))
    atoms.append(line_atom("END OF PROCEDURE — " + sop.sop_id,
                           font="sans-b", size=9.0, lead=13.0))
    atoms.append(line_atom(
        "Printed copies of this document are uncontrolled. Verify the revision "
        "status in the electronic",
        font="serif-i", size=8.5, lead=11.5))
    atoms.append(line_atom(
        "document management system before use.", font="serif-i", size=8.5, lead=11.5))
    return atoms, headings, counter[0]


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------


def paginate(atoms: list[Atom]) -> list[list[tuple[Atom, float]]]:
    pages: list[list[tuple[Atom, float]]] = [[]]
    y = CONTENT_TOP
    i = 0
    n = len(atoms)
    while i < n:
        a = atoms[i]
        if a.kind == "break":
            if pages[-1]:
                pages.append([])
                y = CONTENT_TOP
            i += 1
            continue
        if a.kind == "gap" and not pages[-1]:
            i += 1                       # never start a page with whitespace
            continue
        need = 0.0
        if a.keep_next:
            for j in range(i, min(i + a.keep_next, n - 1)):
                need += atoms[j].height
        if y - need < CONTENT_BOTTOM and pages[-1]:
            pages.append([])
            y = CONTENT_TOP
            continue
        pages[-1].append((a, y))
        y -= a.height
        i += 1
    return pages


def _has_split_list(pages: list[list[tuple[Atom, float]]]) -> bool:
    seen: dict[str, set[int]] = {}
    for pi, page in enumerate(pages):
        for atom, _ in page:
            if atom.group:
                seen.setdefault(atom.group, set()).add(pi)
    return any(len(v) > 1 for v in seen.values())


def force_list_split(atoms: list[Atom]) -> list[Atom]:
    """Guarantee that at least one numbered procedure straddles a page break.

    Natural reflow usually does this on its own; when it does not (short SOPs),
    push the tail of the longest numbered list onto the next page.  That is the
    single nastiest real-world case for an ingest stage, so the fixture must
    always contain it.
    """
    counts: dict[str, int] = {}
    for a in atoms:
        if a.group:
            counts[a.group] = counts.get(a.group, 0) + 1
    if not counts:
        return atoms
    target = max(sorted(counts), key=lambda g: counts[g])
    starts = [i for i, a in enumerate(atoms) if a.group == target and a.item_start]
    if len(starts) < 2:
        return atoms
    order = sorted(range(1, len(starts)), key=lambda k: (abs(k - len(starts) // 2), k))
    for k in order:
        trial = list(atoms)
        trial.insert(starts[k], Atom(kind="break"))
        if _has_split_list(paginate(trial)):
            return trial
    return atoms


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _new_page() -> Figure:
    fig = Figure(figsize=(PAGE_W / 72.0, PAGE_H / 72.0), dpi=72)
    FigureCanvasPdf(fig)
    fig.patch.set_facecolor("white")
    return fig


def T(fig: Figure, x: float, y: float, s: str, font: str = "serif",
      size: float = BODY_SIZE, ha: str = "left", color: str = INK) -> None:
    if not s:
        return
    fig.text(x / PAGE_W, y / PAGE_H, s,
             fontproperties=FONTS.props(font, size),
             ha=ha, va="baseline", color=color, parse_math=False)


def R(fig: Figure, x0: float, x1: float, y: float, lw: float = 0.6,
      color: str = RULE) -> None:
    fig.add_artist(Line2D([x0 / PAGE_W, x1 / PAGE_W], [y / PAGE_H, y / PAGE_H],
                          transform=fig.transFigure, color=color, lw=lw,
                          solid_capstyle="butt"))


def BOX(fig: Figure, x: float, y: float, w: float, h: float, lw: float = 0.8,
        color: str = RULE) -> None:
    fig.add_artist(Rectangle((x / PAGE_W, y / PAGE_H), w / PAGE_W, h / PAGE_H,
                             transform=fig.transFigure, fill=False,
                             edgecolor=color, lw=lw))


def _truncate(text: str, width: float, font: str, size: float) -> str:
    if FONTS.width(text, font, size) <= width:
        return text
    ell = "..."
    budget = width - FONTS.width(ell, font, size)
    out = ""
    for ch in text:
        if FONTS.width(out + ch, font, size) > budget:
            break
        out += ch
    return out.rstrip() + ell


def draw_furniture(fig: Figure, sop: SOP, page_no: int, total: int) -> None:
    """The running header and footer -- on EVERY page, cover included."""
    # Deliberately tight: most titles get clipped to "Cleaning and Disinfe..." ,
    # which is exactly the header noise an ingest stage must learn to drop.
    head_title = _truncate(sop.title, 176.0, "sans", FURNITURE_SIZE)

    T(fig, MARGIN_L, HEADER_BASE, sop.sop_id, "sans-b", FURNITURE_SIZE)
    T(fig, MARGIN_L + TEXT_W * 0.42, HEADER_BASE, f"Rev {sop.version}",
      "sans", FURNITURE_SIZE)
    T(fig, RIGHT_X, HEADER_BASE, head_title, "sans", FURNITURE_SIZE, ha="right")
    R(fig, MARGIN_L, RIGHT_X, HEADER_RULE_Y, lw=0.9)

    R(fig, MARGIN_L, RIGHT_X, FOOTER_RULE_Y, lw=0.9)
    T(fig, MARGIN_L, FOOTER_BASE, f"Page {page_no} of {total}", "sans", FURNITURE_SIZE)
    T(fig, MARGIN_L + TEXT_W * 0.36, FOOTER_BASE,
      f"Effective {sop.effective_date}", "sans", FURNITURE_SIZE)
    T(fig, RIGHT_X, FOOTER_BASE, CONFIDENTIALITY, "sans", FURNITURE_SIZE,
      ha="right", color=FAINT)


def draw_cover(fig: Figure, sop: SOP, total_pages: int) -> None:
    """Controlled-document cover page: labelled metadata fields + approval table."""
    fm = sop.frontmatter
    dept = str(fm.get("department", sop.department_name or sop.department))
    site = str(fm.get("site", f"{COMPANY} — Building 4"))
    lang = sop.language.upper()

    # -- masthead ---------------------------------------------------------
    BOX(fig, MARGIN_L, 652.0, TEXT_W, 68.0, lw=1.1)
    T(fig, MARGIN_L + 12, 698.0, COMPANY.upper(), "sans-b", 15.0)
    T(fig, MARGIN_L + 12, 680.0, "Building 4 — Quality Management System",
      "sans", 9.0, color=FAINT)
    T(fig, RIGHT_X - 12, 698.0, "CONTROLLED DOCUMENT", "sans-b", 9.0, ha="right")
    T(fig, RIGHT_X - 12, 680.0, "QMS Form F-002 Rev 3", "sans", 8.0,
      ha="right", color=FAINT)

    # -- title band -------------------------------------------------------
    BOX(fig, MARGIN_L, 528.0, TEXT_W, 118.0, lw=1.1)
    T(fig, MARGIN_L + 12, 624.0, "STANDARD OPERATING PROCEDURE", "sans-b", 10.5)
    R(fig, MARGIN_L, RIGHT_X, 612.0, lw=0.5, color="#999999")

    tsize = 17.0
    tlines = wrap(sop.title, TEXT_W - 24, "serif-b", tsize)
    if len(tlines) > 2:
        tsize = 14.0
        tlines = wrap(sop.title, TEXT_W - 24, "serif-b", tsize)
    ty = 586.0
    for ln in tlines[:3]:
        T(fig, MARGIN_L + 12, ty, ln, "serif-b", tsize)
        ty -= tsize + 6.0

    # -- labelled metadata fields ----------------------------------------
    BOX(fig, MARGIN_L, 362.0, TEXT_W, 160.0, lw=1.1)
    col1 = MARGIN_L + 12
    col2 = MARGIN_L + TEXT_W * 0.52 + 12
    fig.add_artist(Line2D(
        [(MARGIN_L + TEXT_W * 0.52) / PAGE_W] * 2, [406.0 / PAGE_H, 514.0 / PAGE_H],
        transform=fig.transFigure, color="#999999", lw=0.5))

    rows = [
        (f"Document No.: {sop.sop_id}", f"Version: {sop.version}"),
        (f"Department: {_truncate(dept, TEXT_W * 0.52 - 24, 'serif', 10.0)}",
         f"Status: {sop.status}"),
        (f"Effective Date: {sop.effective_date}", f"Next Review Date: {sop.next_review}"),
        ("Document Type: SOP", f"Language: {lang}"),
        (f"Total Pages: {total_pages}", f"Supersedes: Rev {_prior_rev(sop.version)}"),
    ]
    y = 498.0
    for left, right in rows:
        T(fig, col1, y, left, "serif", 10.0)
        T(fig, col2, y, right, "serif", 10.0)
        y -= 20.0
    R(fig, MARGIN_L, RIGHT_X, y + 8.0, lw=0.5, color="#999999")
    T(fig, col1, y - 6.0, f"Owner: {sop.owner}", "serif", 10.0)
    T(fig, col1, y - 24.0, f"Site: {site}", "serif", 10.0)

    # -- approval record --------------------------------------------------
    T(fig, MARGIN_L, 342.0, "APPROVAL RECORD", "sans-b", 10.0)
    ax = [0.0, 108.0, 268.0, 380.0]
    aw = TEXT_W
    top = 330.0
    rowh = 22.0
    approvals = [
        ("Role", "Name and Title", "Signature", "Date"),
        ("Prepared By", _short_owner(sop.owner), "/s/ electronic", sop.effective_date),
        ("Reviewed By", "Quality Assurance Designee", "/s/ electronic", sop.effective_date),
        ("Approved By", "Head of Quality Assurance", "/s/ electronic", sop.effective_date),
    ]
    BOX(fig, MARGIN_L, top - rowh * len(approvals), aw, rowh * len(approvals), lw=0.9)
    for ri, row in enumerate(approvals):
        by = top - rowh * ri - 15.0
        font = "sans-b" if ri == 0 else "serif"
        size = 8.5 if ri == 0 else 9.0
        for ci, cell in enumerate(row):
            limit = (ax[ci + 1] if ci + 1 < len(ax) else aw) - ax[ci] - 12
            T(fig, MARGIN_L + ax[ci] + 6, by,
              _truncate(cell, limit, font, size), font, size)
        if ri < len(approvals) - 1:
            R(fig, MARGIN_L, RIGHT_X, top - rowh * (ri + 1),
              lw=0.9 if ri == 0 else 0.4, color="#999999")
    for cx in ax[1:]:
        fig.add_artist(Line2D(
            [(MARGIN_L + cx) / PAGE_W] * 2,
            [(top - rowh * len(approvals)) / PAGE_H, top / PAGE_H],
            transform=fig.transFigure, color="#999999", lw=0.4))

    # -- distribution note -------------------------------------------------
    note = (
        "This document is the property of " + COMPANY + ". Printed copies are "
        "uncontrolled unless stamped CONTROLLED COPY in red ink. The current "
        "revision status shall be verified in the electronic document management "
        "system prior to use. Distribution of this document outside " + COMPANY +
        " requires written authorisation from Quality Assurance."
    )
    y = 218.0
    for ln in wrap(note, TEXT_W, "serif-i", 9.0):
        T(fig, MARGIN_L, y, ln, "serif-i", 9.0, color="#333333")
        y -= 12.5
    R(fig, MARGIN_L, RIGHT_X, y + 4.0, lw=0.5, color="#999999")
    T(fig, MARGIN_L, y - 12.0,
      f"Document Control Reference: {sop.sop_id}/R{sop.version}/B4", "sans", 8.5,
      color=FAINT)


def _prior_rev(version: str) -> str:
    try:
        major, _, minor = version.partition(".")
        if minor and int(minor) > 0:
            return f"{major}.{int(minor) - 1}"
        return f"{max(int(major) - 1, 0)}.0"
    except Exception:
        return "previous"


def _short_owner(owner: str) -> str:
    return owner.split(",")[0].strip() if owner else "Document Owner"


def render_page(fig: Figure, page: list[tuple[Atom, float]]) -> None:
    for atom, y in page:
        if atom.kind == "line":
            for p in atom.pieces:
                if not p.text:
                    continue
                x = RIGHT_X - p.x if p.ha == "right" else MARGIN_L + p.x
                T(fig, x, y, p.text, p.font, p.size, ha=p.ha, color=p.color)
        elif atom.kind == "rule":
            R(fig, MARGIN_L + atom.x0, MARGIN_L + atom.x1, y + 4.0,
              lw=atom.lw, color=atom.color)


# --------------------------------------------------------------------------
# Document assembly
# --------------------------------------------------------------------------


def patch_toc(atoms: list[Atom], pages: list[list[tuple[Atom, float]]],
              page_offset: int) -> None:
    """Fill in real page numbers + dotted leaders once pagination is known."""
    heading_page: dict[int, int] = {}
    for pi, page in enumerate(pages):
        for atom, _ in page:
            if atom.heading_ref >= 0 and atom.heading_ref not in heading_page:
                heading_page[atom.heading_ref] = pi + page_offset
    for atom in atoms:
        if atom.toc_ref < 0:
            continue
        num = str(heading_page.get(atom.toc_ref, page_offset))
        title_piece, dot_piece, num_piece = atom.pieces
        num_piece.text = num
        title_w = FONTS.width(title_piece.text, title_piece.font, title_piece.size)
        num_w = FONTS.width(num, num_piece.font, num_piece.size)
        start = title_piece.x + title_w + 5.0
        end = TEXT_W - num_w - 5.0
        dot_w = FONTS.width(" .", "serif", TOC_SIZE)
        count = max(int((end - start) / dot_w), 0)
        dot_piece.x = start
        dot_piece.text = " ." * count
        dot_piece.color = FAINT


def build_pdf(sop: SOP, out_path: Path) -> dict:
    hyphens = 0
    atoms: list[Atom] = []
    headings: list[str] = []
    # Escalating passes: keep hyphenation tasteful when the prose allows it, and
    # only get desperate on terse SOPs that would otherwise have no break at all.
    for cfg in (WrapConfig(),
                WrapConfig(min_fill=0.50, min_word=8),
                WrapConfig(min_fill=0.35, min_word=7),
                WrapConfig(min_fill=0.12, min_word=7, relaxed=True),
                WrapConfig(min_fill=0.05, min_word=6, min_head=2, relaxed=True),
                WrapConfig(min_fill=0.0, min_word=5, min_head=2, min_tail=2,
                           relaxed=True)):
        atoms, headings, hyphens = build_body_atoms(sop, cfg)
        if hyphens:
            break

    pages = paginate(atoms)
    if not _has_split_list(pages):
        atoms = force_list_split(atoms)
        pages = paginate(atoms)

    total = len(pages) + 1                       # + cover
    patch_toc(atoms, pages, page_offset=2)       # body starts on page 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "Title": f"{sop.sop_id} — {sop.title}",
        "Author": sop.owner or COMPANY,
        "Subject": f"Standard Operating Procedure, Rev {sop.version}",
        "Keywords": f"{sop.sop_id}, {sop.department}, SOP, {COMPANY}",
        "Creator": "make_test_pdfs.py",
        "Producer": "make_test_pdfs.py (matplotlib pdf backend)",
        "CreationDate": FIXED_DATE,
    }
    with PdfPages(out_path, metadata=metadata) as pdf:
        cover = _new_page()
        draw_furniture(cover, sop, 1, total)
        draw_cover(cover, sop, total)
        pdf.savefig(cover, facecolor="white")
        cover.clear()

        for pi, page in enumerate(pages):
            fig = _new_page()
            draw_furniture(fig, sop, pi + 2, total)
            render_page(fig, page)
            pdf.savefig(fig, facecolor="white")
            fig.clear()

    return {
        "sop_id": sop.sop_id,
        "path": out_path,
        "pages": total,
        "hyphen_breaks": hyphens,
        "split_list": _has_split_list(pages),
        "headings": len(headings),
    }


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

_HYPHEN_LINE = re.compile(r"[A-Za-z]{2,}-[ \t]*$", re.MULTILINE)


def verify(pdf_path: Path, sop: SOP, expect_pages: int) -> list[str]:
    """Round-trip the fixture through pdftotext and assert the furniture survived."""
    exe = shutil.which("pdftotext")
    if not exe:
        return ["pdftotext not found; skipped verification"]
    text = subprocess.run(
        [exe, "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    problems: list[str] = []
    required = [
        f"Document No.: {sop.sop_id}",
        f"Version: {sop.version}",
        f"Effective Date: {sop.effective_date}",
        f"Next Review Date: {sop.next_review}",
        f"Owner: {sop.owner}",
        "APPROVAL RECORD",
        "TABLE OF CONTENTS",
        f"Page 1 of {expect_pages}",
        f"Page {expect_pages} of {expect_pages}",
        CONFIDENTIALITY,
        f"Rev {sop.version}",
    ]
    for needle in required:
        if needle not in text:
            problems.append(f"missing {needle!r}")
    if text.count(f"Effective {sop.effective_date}") < expect_pages:
        problems.append("running footer not on every page")
    if text.count(sop.sop_id) < expect_pages:
        problems.append("running header not on every page")
    if not _HYPHEN_LINE.search(text):
        problems.append("no hyphenated line break found")
    if re.search(r"^\s*1[.)]\s", sop.body, re.MULTILINE) and \
            not re.search(r"^\s*1\.\s", text, re.MULTILINE):
        problems.append("source has numbered steps but the PDF text has none")
    if len(text.strip()) < 1500:
        problems.append("suspiciously little extractable text")
    return problems


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate digital-native SOP PDF test fixtures from data/sops/*.md",
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"output directory (default: {DEFAULT_OUT})")
    ap.add_argument("--limit", type=int, default=None,
                    help="only convert the first N SOPs (sorted by id)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="only convert these SOP ids")
    ap.add_argument("--verify", action="store_true",
                    help="round-trip each PDF through pdftotext and check the furniture")
    args = ap.parse_args(argv)

    out_dir: Path = args.out.expanduser().resolve()
    if PROJECT_ROOT in out_dir.parents or out_dir == PROJECT_ROOT:
        ap.error(
            f"refusing to write fixtures inside the repo ({out_dir}); "
            "pick a scratch directory"
        )

    corpus = load_corpus()
    sops = sorted(corpus.sops, key=lambda s: s.sop_id)
    if args.only:
        wanted = set(args.only)
        sops = [s for s in sops if s.sop_id in wanted]
    if args.limit is not None:
        sops = sops[: args.limit]
    if not sops:
        print("No SOPs selected.", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    failures = 0
    for sop in sops:
        info = build_pdf(sop, out_dir / f"{sop.sop_id}.pdf")
        note = ""
        if args.verify:
            problems = verify(info["path"], sop, info["pages"])
            if not info["split_list"]:
                problems.append("no procedure list straddles a page break")
            note = "  OK" if not problems else "  FAIL: " + "; ".join(problems)
            failures += bool(problems)
        results.append(info)
        print(
            f"{info['sop_id']:<16} {info['pages']} pages  "
            f"{info['headings']:>2} sections  "
            f"hyphen-breaks={info['hyphen_breaks']:<3} "
            f"split-list={'yes' if info['split_list'] else 'no'}{note}"
        )

    pages = [r["pages"] for r in results]
    print(
        f"\n{len(results)} PDFs -> {out_dir}\n"
        f"pages: min={min(pages)} max={max(pages)} "
        f"mean={sum(pages) / len(pages):.1f}"
    )
    if args.verify:
        print("verification: " + ("ALL PASSED" if not failures
                                  else f"{failures} FAILED"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
