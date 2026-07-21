"""PDF ingest stage: digital-native SOP PDFs -> pipeline-ready Markdown.

The pipeline (``sop_pipeline.core.corpus.load_corpus``) reads Markdown files with
YAML frontmatter.  Real SOPs arrive as PDFs exported from a DMS or from Word.
This module converts them **without touching anything downstream**: the output of
``--out`` is a drop-in replacement for ``data/sops/``.

    python3 -m sop_pipeline.ingest --pdf-dir <dir> --out <dir> [--report <path>]

What actually determines conversion quality is the cleanup, not the extraction:

1. **Extraction** — Poppler ``pdftotext -layout`` (no new pip dependencies).
   ``-layout`` keeps column geometry, which is what lets us recognise running
   headers/footers, table rows and list indentation.
2. **Scanned-PDF detection** — a PDF whose pages yield ~no text is never emitted
   as an empty document; it is reported as ``needs_ocr`` and skipped (an optional
   ``--ocr`` fallback shells out to pdftoppm + tesseract when they exist).
3. **Page furniture** — the running header/footer (SOP id, revision, page number,
   CONFIDENTIAL marking) is detected *by recurrence at the same relative position
   across pages*, never by matching known wording.  Left in, it adds dozens of
   fragment "sentences" to every readability metric and makes each SOP look like
   it cites itself on every page.
4. **Reflow** — soft hyphens are stitched back together using vocabulary evidence
   from the corpus itself (``steriliza-/tion`` fuses because "sterilization"
   occurs elsewhere; ``system-/suitability`` keeps its hyphen because the intact
   compound does), and wrapped body lines are re-joined into flowing paragraphs
   without merging separate steps, headings or list items.
5. **Frontmatter recovery** — labelled cover-page fields ("Document No.:",
   "Version:", "Effective Date:", "Owner:") plus the running header.  Dates are
   normalised to ISO.  A field that cannot be found is *omitted* and recorded as
   missing — never guessed.
6. **Structure** — headings keep their own dialect (ALL-CAPS stays ALL-CAPS,
   numbered/roman/title-case headings keep their text verbatim and are marked
   with ``##`` so the loader can see them), numbered steps stay numbered, and
   inline SOP cross-references and regulatory citations survive untouched.
7. **Quality report** — JSON + console table, with a high/medium/low confidence
   and the reason.  In a GMP context a human must be able to see which
   conversions need review before the analysis is trusted.

Deterministic and offline: same PDFs in, byte-identical Markdown out.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sop_pipeline.core.corpus import (
    SOP_ID_RE,
    load_manifest,
    load_sop,
)

try:  # optional: gives the report the same citation count m05 will compute
    from sop_pipeline.core.regkb import RegKB
except Exception:  # pragma: no cover - core is expected to be present
    RegKB = None  # type: ignore[assignment]


class IngestError(RuntimeError):
    """Fatal, user-actionable ingest problem (missing binary, unreadable PDF)."""


# ---------------------------------------------------------------------------
# Tunables — every threshold the cleanup depends on, in one place.
# ---------------------------------------------------------------------------

ZONE_DEPTH = 3            # lines from the top/bottom of a page that can be furniture
FURNITURE_SHARE = 0.6     # a zone line recurring on this share of pages is furniture
BOILERPLATE_SHARE = 0.75  # an edge line recurring on this share of DOCS is boilerplate
EDGE_LINES = 8            # lines at each end of a document eligible for that check
MIN_PAGE_CHARS = 40       # below this a page counts as "no extractable text"
MIN_DOC_CHARS = 200       # below this the whole document counts as scanned
MIN_BODY_CHARS = 400      # below this the conversion is low confidence
WRAP_WIDTH = 92

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
_DIGITS_RE = re.compile(r"\d+")
_ITEM_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})[.)]\s+(\S.*)$")
_BULLET_RE = re.compile(r"^[•▪◦‣·∙*–—-]\s+(\S.*)$")
# "Step 4: ..." — a numbered step written as a paragraph (a real SOP house style,
# and one the flowchart module reads).  Consecutive steps often run together with
# no blank line between them, so they have to be split apart explicitly.
_STEP_RE = re.compile(r"^(?:step|paso|etapa)\s+\d{1,2}\s*[.:)]\s+\S", re.IGNORECASE)
_ROMAN_HEAD_RE = re.compile(r"^\(?([IVXLC]{1,7})[.)]\s+(\S.*)$")
_NUM_HEAD_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(\S.*)$")
_TOC_LINE_RE = re.compile(r"^(?P<title>.*?\S)(?P<lead>[ .·․…]{6,})(?P<page>\d{1,4})$")
_PAGE_OF_RE = re.compile(
    r"\b(?:page|p\.|pág(?:ina)?|seite)\s*\d+\s*(?:of|/|de|von)\s*\d+\b", re.IGNORECASE
)
_BARE_NUM_RE = re.compile(r"^[-–—\s]*\d{1,4}[-–—\s]*$")
_REV_IN_TEXT_RE = re.compile(r"\bRev(?:ision)?\.?\s*:?\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_EFFECTIVE_IN_TEXT_RE = re.compile(
    r"\beffective\b[^0-9A-Za-z]{0,3}(\d{4}-\d{2}-\d{2}|\d{1,2}[/-][A-Za-z0-9]{1,9}[/-]\d{2,4})",
    re.IGNORECASE,
)
_WORD_TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
_LOWER_START_RE = re.compile(r"^[a-zà-ÿ(]")
_SENT_END_RE = re.compile(r"[.!?:;]$")
_COL_GAP_RE = re.compile(r"\S {2,}\S")
# Any hint of a regulatory citation protects a line from boilerplate removal.
_CITATION_HINT_RE = re.compile(
    r"\b(CFR|ICH|Annex|USP|ISO|GAMP|PDA|EudraLex|GMP|21\s*CFR)\b", re.IGNORECASE
)
_CAPS_HEADING_RE = re.compile(
    r"^\s{0,3}(\d+(\.\d+)*\.?\s+)?[A-ZÁÉÍÓÚÜÑ0-9]"
    r"[A-ZÁÉÍÓÚÜÑ0-9 &/\-,()]{4,}\s*$"
)

# Frontmatter labels we know how to read off a controlled-document cover page.
# Matching is case-insensitive on a normalised label (punctuation stripped).
_LABELS: dict[str, tuple[str, ...]] = {
    "sop_id": (
        "document no", "document number", "document id", "doc no", "doc id",
        "sop no", "sop number", "procedure no", "procedure number",
        "documento no", "numero de documento", "n de documento",
    ),
    "title": ("title", "document title", "sop title", "titulo"),
    "version": ("version", "revision", "rev", "revision no", "version no", "version number"),
    "effective_date": (
        "effective date", "effective", "date effective", "fecha de vigencia",
        "fecha efectiva", "vigente desde",
    ),
    "next_review": (
        "next review date", "next review", "review date", "next periodic review",
        "proxima revision", "fecha de proxima revision",
    ),
    "owner": (
        "owner", "document owner", "process owner", "responsible person",
        "propietario", "responsable",
    ),
    "department": (
        "department", "dept", "functional area", "department name",
        "departamento", "area",
    ),
    "status": ("status", "document status", "estado"),
    "language": ("language", "idioma"),
    "site": ("site", "facility", "location", "sitio"),
}
_LABEL_LOOKUP = {alias: key for key, aliases in _LABELS.items() for alias in aliases}
_MAX_LABEL_LEN = max(len(a) for a in _LABEL_LOOKUP)

_PAIR_RE = re.compile(
    r"(?:^\s*|\s{2,})(?P<label>[^\W\d_][\w .&/À-ÿ-]{1,%d}?)\s*:\s*(?P<value>.*?)"
    r"(?=\s{2,}[^\W\d_][\w .&/À-ÿ-]{1,%d}?\s*:|$)" % (_MAX_LABEL_LEN, _MAX_LABEL_LEN)
)

_MONTHS = {
    "jan": 1, "january": 1, "ene": 1, "enero": 1,
    "feb": 2, "february": 2, "febrero": 2,
    "mar": 3, "march": 3, "marzo": 3,
    "apr": 4, "april": 4, "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "june": 6, "junio": 6,
    "jul": 7, "july": 7, "julio": 7,
    "aug": 8, "august": 8, "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "september": 9, "septiembre": 9, "setiembre": 9,
    "oct": 10, "october": 10, "octubre": 10,
    "nov": 11, "november": 11, "noviembre": 11,
    "dec": 12, "december": 12, "dic": 12, "diciembre": 12,
}

# Cheap language sniff, used only when the document does not print a language
# field.  Recorded in the report as a heuristic so a reviewer can override it.
_ES_STOPWORDS = frozenset(
    "de la el los las que se debe deberan del para por con una un en y o "
    "procedimiento limpieza personal segun conforme".split()
)
_EN_STOPWORDS = frozenset(
    "the of and to in is are shall must be this that for with by as from "
    "procedure cleaning personnel per".split()
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _collapse(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _norm_key(text: str) -> str:
    """Recurrence key: identical page furniture collapses to one key.

    Digits and SOP ids are masked so "Page 2 of 5" and "Page 3 of 5", or a footer
    carrying the document id, still compare equal.
    """
    masked = SOP_ID_RE.sub("<ID>", text)
    masked = _DIGITS_RE.sub("#", masked)
    return _collapse(masked).casefold()


def _toc_key(text: str) -> str:
    """Comparison key for matching a body line against a table-of-contents entry."""
    t = _collapse(text).rstrip(".").strip()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", " ", t.casefold()).strip()


def _is_caps_line(text: str) -> bool:
    """True for the ALL-CAPS heading dialect the corpus loader recognises."""
    s = text.strip()
    if not s or len(s) > 90 or sum(c.isalpha() for c in s) < 4:
        return False
    return s == s.upper() and bool(_CAPS_HEADING_RE.match(s))


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _has_prose(text: str) -> bool:
    """True when a line carries words of its own, not just a document id.

    A line that is nothing but "SOP-QC-004." is the tail of a wrapped sentence
    that a Word/DMS export happened to bold or index — never a real heading.
    Treating it as one both invents a section and hides a cross-reference.
    """
    residue = SOP_ID_RE.sub(" ", text)
    return len(re.sub(r"[^A-Za-zÀ-ÿ]", "", residue)) >= 3


def _words(text: str) -> list[str]:
    return _WORD_TOKEN_RE.findall(text)


# ---------------------------------------------------------------------------
# 1. Extraction
# ---------------------------------------------------------------------------


def require_binary(name: str, purpose: str) -> str:
    exe = shutil.which(name)
    if not exe:
        raise IngestError(
            f"{name!r} is required {purpose} but was not found on PATH.\n"
            f"  Install Poppler:  macOS 'brew install poppler'  |  "
            f"Debian/Ubuntu 'apt-get install poppler-utils'"
        )
    return exe


def poppler_version() -> str:
    """Version string of pdftotext, recorded in the report for traceability."""
    try:
        exe = shutil.which("pdftotext")
        if not exe:
            return "not found"
        proc = subprocess.run([exe, "-v"], capture_output=True, text=True)
        blob = (proc.stderr or "") + (proc.stdout or "")
        m = re.search(r"pdftotext version ([\w.]+)", blob)
        return m.group(1) if m else "unknown"
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def extract_pages(pdf: Path) -> list[str]:
    """Return one string per page, using ``pdftotext -layout``."""
    exe = require_binary("pdftotext", "to extract text from PDFs")
    # Page breaks (\f) are kept deliberately: the page boundary is what makes
    # header/footer detection possible.
    proc = subprocess.run(
        [exe, "-layout", "-enc", "UTF-8", "-eol", "unix", "-q", str(pdf), "-"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise IngestError(f"pdftotext failed on {pdf.name}: {proc.stderr.strip() or proc.returncode}")
    text = proc.stdout.replace("\r\n", "\n").replace("\r", "\n")
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages or [""]


def ocr_page(pdf: Path, page_no: int, dpi: int = 300) -> str:
    """Optional OCR fallback for an image-only page (``--ocr``)."""
    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not (pdftoppm and tesseract):
        raise IngestError(
            "--ocr needs both 'pdftoppm' (poppler) and 'tesseract' on PATH; "
            f"pdftoppm={'ok' if pdftoppm else 'missing'} "
            f"tesseract={'ok' if tesseract else 'missing'}"
        )
    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / "page"
        subprocess.run(
            [pdftoppm, "-r", str(dpi), "-f", str(page_no), "-l", str(page_no),
             "-png", str(pdf), str(stem)],
            capture_output=True, check=False,
        )
        images = sorted(Path(tmp).glob("page*.png"))
        if not images:
            return ""
        proc = subprocess.run(
            [tesseract, str(images[0]), "stdout", "--psm", "6"],
            capture_output=True, text=True, check=False,
        )
        return proc.stdout


# ---------------------------------------------------------------------------
# 2. Page furniture (running headers / footers)
# ---------------------------------------------------------------------------


@dataclass
class Line:
    """One physical line of extracted text plus where it came from."""

    raw: str
    page: int
    idx: int
    drop: str = ""            # non-empty => removed, value is the reason

    @property
    def text(self) -> str:
        return self.raw.strip()

    @property
    def indent(self) -> int:
        return _indent_of(self.raw)

    @property
    def blank(self) -> bool:
        return not self.raw.strip()


def _zone_positions(lines: list[Line]) -> dict[int, str]:
    """Map line index -> "top"/"bottom" for the furniture bands of one page."""
    filled = [ln.idx for ln in lines if not ln.blank]
    zones: dict[int, str] = {}
    for i in filled[:ZONE_DEPTH]:
        zones[i] = "top"
    for i in filled[-ZONE_DEPTH:]:
        zones.setdefault(i, "bottom")
    return zones


def strip_furniture(pages: list[list[Line]]) -> tuple[int, list[str]]:
    """Drop running headers/footers.  Returns (lines dropped, sample of them).

    Detection is purely by *recurrence at the same relative position*: a line in
    the top or bottom band of a page whose masked form also appears in the same
    band on most other pages is page furniture, whatever it happens to say.  A
    single generic pattern ("Page 3 of 12" / a bare page number) is used as a
    secondary signal so one- and two-page documents are handled too.
    """
    n_pages = len(pages)
    seen: Counter[tuple[str, str]] = Counter()
    for page in pages:
        zones = _zone_positions(page)
        per_page: set[tuple[str, str]] = set()
        for ln in page:
            zone = zones.get(ln.idx)
            if zone and not ln.blank:
                per_page.add((zone, _norm_key(ln.raw)))
        seen.update(per_page)

    threshold = max(2, math.ceil(FURNITURE_SHARE * n_pages))
    recurring = {key for key, count in seen.items() if count >= threshold}

    dropped = 0
    samples: list[str] = []
    for page in pages:
        zones = _zone_positions(page)
        for ln in page:
            zone = zones.get(ln.idx)
            if not zone or ln.blank:
                continue
            key = (zone, _norm_key(ln.raw))
            reason = ""
            if key in recurring:
                reason = "repeated-furniture"
            elif _PAGE_OF_RE.search(ln.text) or _BARE_NUM_RE.match(ln.text):
                reason = "page-number"
            if reason:
                ln.drop = reason
                dropped += 1
                if len(samples) < 6 and ln.text not in samples:
                    samples.append(ln.text)
    return dropped, samples


# ---------------------------------------------------------------------------
# 3. Table of contents
# ---------------------------------------------------------------------------


def strip_toc(pages: list[list[Line]]) -> tuple[set[str], int]:
    """Remove dotted-leader TOC rows; return the heading titles they name.

    The TOC is the document telling us its own heading list, which is the single
    most reliable heading signal available in extracted text.
    """
    titles: set[str] = set()
    rows: list[Line] = []
    for page in pages:
        for ln in page:
            if ln.drop or ln.blank:
                continue
            m = _TOC_LINE_RE.match(ln.text)
            if not m or m.group("lead").count(".") < 4:
                continue
            title = m.group("title").strip()
            if len(title) < 2:
                continue
            rows.append(ln)
            if _has_prose(title):
                titles.add(_toc_key(title))
    if len(rows) < 3:
        return set(), 0

    dropped = 0
    for ln in rows:
        ln.drop = "toc-entry"
        dropped += 1
    # The "TABLE OF CONTENTS" caption itself: the short line immediately above
    # the first row on the same page (detected by position, not by wording).
    first = rows[0]
    page = pages[first.page]
    for prev in reversed(page[: first.idx]):
        if prev.blank or prev.drop:
            continue
        if len(prev.text) <= 40 and not _TOC_LINE_RE.match(prev.text):
            prev.drop = "toc-caption"
            dropped += 1
        break
    return titles, dropped


# ---------------------------------------------------------------------------
# 4. Cover page and frontmatter recovery
# ---------------------------------------------------------------------------


def _label_pairs(raw_line: str) -> list[tuple[str, str]]:
    """Split one physical line into (canonical_key, value) pairs.

    ``-layout`` preserves the two-column cover grid, so a single line can hold
    "Document No.: SOP-CLN-003        Version: 2.2".
    """
    out: list[tuple[str, str]] = []
    for m in _PAIR_RE.finditer(raw_line):
        key = _LABEL_LOOKUP.get(_label_key(m.group("label")))
        value = _clean_value(_collapse(m.group("value")))
        if key and value:
            out.append((key, value))
    return out


def _label_key(label: str) -> str:
    label = re.sub(r"[^\w\s]", " ", label)
    label = unicodedata.normalize("NFKD", label)
    label = "".join(c for c in label if not unicodedata.combining(c))
    return _collapse(label).casefold()


def _clean_value(value: str) -> str:
    """Cut a value short where the next labelled field starts.

    ``-layout`` normally leaves a wide gap between cover-grid columns, but a
    narrow grid (or OCR) can collapse it to a single space, which would
    otherwise glue "Status: Effective" onto the department name.
    """
    for m in re.finditer(r":\s", value):
        words = value[: m.start()].split()
        for n in (1, 2, 3):
            if len(words) > n and _label_key(" ".join(words[-n:])) in _LABEL_LOOKUP:
                return " ".join(words[:-n]).strip()
    return value


def parse_iso_date(raw: str) -> tuple[str, str]:
    """Normalise a printed date to ISO ``YYYY-MM-DD``.

    Returns ``(iso, note)``; ``iso`` is "" when the string cannot be parsed as a
    date, and ``note`` flags a day/month ambiguity a reviewer should confirm.
    """
    s = _collapse(raw).strip(" .,;")
    if not s:
        return "", ""
    s = re.sub(r"^\w+day,?\s+", "", s, flags=re.IGNORECASE)

    def _mk(y: int, mo: int, d: int) -> str:
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return ""

    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))), ""
    m = re.match(r"^(\d{1,2})[\s-]([A-Za-zÀ-ÿ]{3,12})\.?[\s,-]+(\d{4})$", s)
    if m:
        mo = _MONTHS.get(m.group(2).casefold().rstrip("."))
        if mo:
            return _mk(int(m.group(3)), mo, int(m.group(1))), ""
    m = re.match(r"^([A-Za-zÀ-ÿ]{3,12})\.?\s+(\d{1,2}),?\s+(\d{4})$", s)
    if m:
        mo = _MONTHS.get(m.group(1).casefold().rstrip("."))
        if mo:
            return _mk(int(m.group(3)), mo, int(m.group(2))), ""
    m = re.match(r"^(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]{3,12})\s+de\s+(\d{4})$", s, re.IGNORECASE)
    if m:
        mo = _MONTHS.get(m.group(2).casefold())
        if mo:
            return _mk(int(m.group(3)), mo, int(m.group(1))), ""
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
        if a > 12 and b <= 12:
            return _mk(y, b, a), ""
        if b > 12 and a <= 12:
            return _mk(y, a, b), ""
        return _mk(y, a, b), f"ambiguous day/month in {raw!r} (read as MM/DD/YYYY)"
    return "", ""


@dataclass
class Meta:
    """Recovered frontmatter plus provenance for the quality report."""

    values: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def set(self, key: str, value: str, source: str) -> None:
        value = _collapse(value)
        if value and key not in self.values:
            self.values[key] = value
            self.sources[key] = source


def _cover_title(page: list[Line], first_meta_idx: int) -> str:
    """The title block sitting above the metadata grid on a controlled cover page.

    Qualifying lines are single-column (no wide gap) and carry no label; the last
    such run of adjacent lines before the metadata grid is the document title.
    A run that is entirely ALL-CAPS is masthead boilerplate ("CONTROLLED
    DOCUMENT", "STANDARD OPERATING PROCEDURE") — but an ALL-CAPS *line* inside a
    mixed-case run is part of the title ("... Salas Limpias" / "ISO 7").
    """
    runs: list[list[str]] = []
    current: list[str] = []
    for ln in page[:first_meta_idx]:
        text = ln.text
        ok = (
            not ln.drop
            and text
            and len(text) <= 90
            and ":" not in text
            and not _COL_GAP_RE.search(ln.raw.strip())
            and sum(c.isalpha() for c in text) >= 3
        )
        if ok:
            current.append(text)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    for run in reversed(runs):
        joined = _collapse(" ".join(run))
        if joined != joined.upper():
            return joined
    return ""


def recover_metadata(
    pages: list[list[Line]],
    furniture_text: str,
    pdf_path: Path,
) -> tuple[Meta, int]:
    """Read frontmatter off the cover page + running header.

    Returns the metadata and the index of the cover page (-1 when there is none).
    Nothing is invented: a field that is not printed anywhere is simply absent.
    """
    meta = Meta()
    cover_idx = -1
    first_meta_idx = 0

    # Cover page = the first page (of the first two) carrying >= 3 labelled fields.
    for pi, page in enumerate(pages[:2]):
        found: list[tuple[int, str, str]] = []
        for ln in page:
            if ln.drop or ln.blank:
                continue
            for key, value in _label_pairs(ln.raw):
                found.append((ln.idx, key, value))
        if len({k for _, k, _ in found}) >= 3:
            cover_idx = pi
            first_meta_idx = found[0][0]
            for _, key, value in found:
                meta.set(key, value, "cover label")
            break

    # Fallbacks that read the running header/footer, then the filename.
    if "version" not in meta.values:
        m = _REV_IN_TEXT_RE.search(furniture_text)
        if m:
            meta.set("version", m.group(1), "running header")
    if "effective_date" not in meta.values:
        m = _EFFECTIVE_IN_TEXT_RE.search(furniture_text)
        if m:
            meta.set("effective_date", m.group(1), "running footer")

    if "sop_id" in meta.values:
        m = SOP_ID_RE.search(meta.values["sop_id"])
        if m:
            meta.values["sop_id"] = m.group(0)
    if "sop_id" not in meta.values:
        head = "\n".join(ln.raw for ln in pages[0]) if pages else ""
        m = SOP_ID_RE.search(head) or SOP_ID_RE.search(furniture_text)
        if m:
            meta.set("sop_id", m.group(0), "document text")
    if "sop_id" not in meta.values:
        stem = pdf_path.stem.strip()
        m = SOP_ID_RE.search(stem.upper())
        meta.set("sop_id", m.group(0) if m else stem, "filename")

    if "title" not in meta.values and cover_idx >= 0:
        title = _cover_title(pages[cover_idx], first_meta_idx)
        if title and title.casefold() != meta.values.get("sop_id", "").casefold():
            meta.set("title", title, "cover title block")

    # Normalise what we found.
    for key in ("effective_date", "next_review"):
        if key in meta.values:
            iso, note = parse_iso_date(meta.values[key])
            if iso:
                meta.values[key] = iso
                if note:
                    meta.notes.append(note)
            else:
                meta.notes.append(f"{key}: could not parse {meta.values[key]!r} as a date")
                del meta.values[key]
                meta.sources.pop(key, None)
    if "version" in meta.values:
        m = re.search(r"\d+(?:\.\d+)*", meta.values["version"])
        if m:
            meta.values["version"] = m.group(0)
    if "language" in meta.values:
        lang = meta.values["language"].strip().casefold()
        lang = {"english": "en", "spanish": "es", "espanol": "es",
                "español": "es", "ingles": "en"}.get(lang, lang)[:2]
        if re.fullmatch(r"[a-z]{2}", lang):
            meta.values["language"] = lang
        else:
            del meta.values["language"]
            meta.sources.pop("language", None)
    return meta, cover_idx


def sniff_language(text: str) -> str:
    """Stopword-ratio language sniff, used only when no language field is printed."""
    tokens = [w.casefold() for w in _words(text)][:800]
    if not tokens:
        return ""
    es = sum(1 for t in tokens if t in _ES_STOPWORDS)
    en = sum(1 for t in tokens if t in _EN_STOPWORDS)
    if es >= 8 and es > en * 1.5:
        return "es"
    if en >= 8:
        return "en"
    return ""


# ---------------------------------------------------------------------------
# 5. Block model — headings, steps, bullets, tables, paragraphs
# ---------------------------------------------------------------------------


@dataclass
class Block:
    kind: str                     # heading | para | item | bullet | table
    lines: list[str] = field(default_factory=list)
    caps: bool = False            # heading dialect: ALL-CAPS stays ALL-CAPS
    marker: str = ""              # "3." for numbered steps
    toc_listed: bool = False
    text: str = ""                # joined, de-hyphenated body
    rows: list[list[str]] = field(default_factory=list)   # table cells
    col_starts: list[int] = field(default_factory=list)   # table column offsets

    # -- table helpers -----------------------------------------------------
    def add_row(self, raw: str) -> None:
        cells = _split_cells(raw)
        if not self.col_starts:
            self.col_starts = [x for x, _ in cells]
        row = [""] * len(self.col_starts)
        for x, cell in cells:
            col = min(range(len(self.col_starts)), key=lambda i: abs(self.col_starts[i] - x))
            row[col] = f"{row[col]} {cell}".strip() if row[col] else cell
        self.rows.append(row)

    def add_cell_continuation(self, raw: str) -> None:
        """A table cell that wrapped onto the next line belongs to its own column."""
        if not self.rows:
            return
        for x, cell in _split_cells(raw):
            col = min(range(len(self.col_starts)), key=lambda i: abs(self.col_starts[i] - x))
            prev = self.rows[-1][col]
            self.rows[-1][col] = f"{prev} {cell}".strip() if prev else cell


class Dehyphenator:
    """Re-joins words broken across a line break, using corpus vocabulary.

    ``steriliza-`` + ``tion`` fuses because "sterilization" occurs elsewhere in
    the batch; ``system-`` + ``suitability`` keeps its hyphen because the intact
    compound occurs elsewhere, and ``photodiode-`` + ``array`` keeps it because
    the corpus uses both halves as words.  No dictionary, no network — the corpus
    is its own evidence.
    """

    def __init__(self, vocab: set[str], hyphenated: set[str]):
        self.vocab = vocab
        self.hyphenated = hyphenated
        self.joined = 0      # soft hyphens removed
        self.kept = 0        # hyphens judged part of a real compound

    def reset(self) -> None:
        self.joined = self.kept = 0

    def _keep(self, head: str, tail: str) -> str:
        self.kept += 1
        return head + tail

    def _fuse(self, stem: str, tail: str) -> str:
        self.joined += 1
        return stem + tail

    def join(self, head: str, tail: str) -> str:
        if not head:
            return tail
        if not head.endswith("-") or head.endswith("--"):
            return f"{head} {tail}"
        stem = head[:-1]
        last = _WORD_TOKEN_RE.findall(stem)
        first = _WORD_TOKEN_RE.findall(tail)
        # Identifier-ish breaks ("SOP-" / "CLN-003") always keep the hyphen.
        if not last or not first or not _LOWER_START_RE.match(tail):
            return head + tail
        if not stem.endswith(last[-1]) or not tail.startswith(first[0]):
            return head + tail
        a, b = last[-1].casefold(), first[0].casefold()
        if a.upper() == last[-1] or any(ch.isdigit() for ch in last[-1] + first[0]):
            return head + tail
        if f"{a}-{b}" in self.hyphenated:
            return self._keep(head, tail)      # the compound occurs intact elsewhere
        if f"{a}{b}" in self.vocab:
            return self._fuse(stem, tail)      # the fused word occurs elsewhere
        if a in self.vocab and b in self.vocab:
            return self._keep(head, tail)      # two words the corpus knows: a compound
        # No evidence either way: assume a soft hyphen.  Measured on the fixture
        # batch this is right ~6 times out of 7; the residue is a compound whose
        # halves the corpus never uses anywhere else.
        return self._fuse(stem, tail)


def build_vocabulary(all_lines: list[str]) -> tuple[set[str], set[str]]:
    """Vocabulary + intact hyphenated compounds, from line-interior tokens only.

    The first and last token of a line are exactly the halves of a word broken
    across that break ("per-" / "centage"), so admitting them as evidence would
    teach the vocabulary the fragments it is supposed to detect.
    """
    vocab: set[str] = set()
    hyphenated: set[str] = set()
    for line in all_lines:
        tokens = line.split()
        for tok in tokens[1:-1]:
            tok = tok.strip(".,;:()[]—–\"'")
            if "-" in tok:
                parts = _WORD_TOKEN_RE.findall(tok)
                if len(parts) >= 2 and all(p.isalpha() for p in parts):
                    hyphenated.add("-".join(p.casefold() for p in parts[:2]))
                continue
            if tok.isalpha() and len(tok) > 2:
                vocab.add(tok.casefold())
    return vocab, hyphenated


def _is_table_row(raw: str) -> bool:
    """Two or more wide column gaps: a laid-out table row, not flowing prose."""
    return len(_COL_GAP_RE.findall(raw.strip())) >= 2


def _split_cells(raw: str) -> list[tuple[int, str]]:
    """Split a laid-out row into (start column, cell text) on runs of 2+ spaces."""
    return [(m.start(), m.group().strip()) for m in re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", raw)]


def _heading_kind(
    text: str,
    toc_titles: set[str],
    prev_blank: bool,
    lookahead: str,
) -> tuple[bool, bool, bool]:
    """Decide whether a line is a heading.

    Returns ``(is_heading, is_caps, toc_listed)``.  Heading *text* is never
    rewritten: the caller keeps ALL-CAPS as ALL-CAPS and everything else
    verbatim, because per-department heading style is what m11 measures.
    """
    if not text or len(text) > 100 or not _has_prose(text):
        return False, False, False
    key = _toc_key(text)
    if key and key in toc_titles:
        return True, _is_caps_line(text), True
    joined = _toc_key(f"{text} {lookahead}") if lookahead else ""
    if joined and joined in toc_titles:
        return True, _is_caps_line(f"{text} {lookahead}"), True
    if _is_caps_line(text):
        return True, True, False

    # Heuristics for documents without a usable TOC.
    if toc_titles or not prev_blank:
        return False, False, False
    words = text.split()
    if len(words) > 9 or len(text) > 70 or _SENT_END_RE.search(text.rstrip()):
        return False, False, False
    if _ROMAN_HEAD_RE.match(text) or _NUM_HEAD_RE.match(text):
        return True, False, False
    if text[0].isupper():
        capitalish = sum(1 for w in words if w[:1].isupper() or w.casefold() in
                         {"and", "of", "the", "for", "to", "in", "a", "y", "de", "la"})
        if capitalish >= max(1, int(0.6 * len(words))):
            return True, False, False
    return False, False, False


def build_blocks(pages: list[list[Line]], toc_titles: set[str], dehy: Dehyphenator) -> list[Block]:
    """Reflow surviving lines into blocks, joining wrapped prose only."""
    stream: list[tuple[Line, bool]] = []   # (line, starts_a_new_page)
    for page in pages:
        kept = [ln for ln in page if not ln.drop]
        while kept and kept[0].blank:
            kept.pop(0)
        while kept and kept[-1].blank:
            kept.pop()
        for i, ln in enumerate(kept):
            stream.append((ln, i == 0))

    base_indent = min(
        (ln.indent for ln, _ in stream if not ln.blank and not _is_table_row(ln.raw)),
        default=0,
    )

    blocks: list[Block] = []
    cur: Block | None = None
    expected_item = 1
    prev_blank = True

    def flush() -> None:
        nonlocal cur
        if cur is not None:
            if cur.kind == "table":
                cur.text = " ".join(c for row in cur.rows for c in row if c)
            else:
                text = ""
                for piece in cur.lines:
                    text = dehy.join(text, piece) if text else piece
                cur.text = _collapse(text)
            if cur.text:
                blocks.append(cur)
        cur = None

    for pos, (ln, new_page) in enumerate(stream):
        if ln.blank:
            flush()
            prev_blank = True
            continue

        text = _collapse(ln.text)
        indent = max(ln.indent - base_indent, 0)
        lookahead = ""
        for nxt, _ in stream[pos + 1: pos + 2]:
            lookahead = _collapse(nxt.text)

        if _is_table_row(ln.raw):
            if cur is None or cur.kind != "table":
                flush()
                cur = Block(kind="table")
            cur.add_row(ln.raw)
            expected_item = 1
            prev_blank = False
            continue

        # A wrapped table cell: indented, no column gaps of its own, directly
        # under a table.  Keep it with the table instead of starting a paragraph.
        if cur is not None and cur.kind == "table" and indent >= 4 and not prev_blank:
            cur.add_cell_continuation(ln.raw)
            continue

        is_heading, caps, toc_listed = _heading_kind(text, toc_titles, prev_blank, lookahead)
        if is_heading:
            flush()
            cur = Block(kind="heading", caps=caps, toc_listed=toc_listed, lines=[text])
            flush()
            expected_item = 1
            prev_blank = False
            continue

        item = _ITEM_RE.match(text)
        bullet = _BULLET_RE.match(text)
        if item and indent <= 4:
            num = item.group(1)
            simple = "." not in num
            n = int(num.split(".")[0])
            if not simple or n == 1 or n == expected_item:
                flush()
                cur = Block(kind="item", marker=f"{num}.", lines=[item.group(2)])
                expected_item = (n + 1) if simple else expected_item
                prev_blank = False
                continue
        if bullet and indent <= 4:
            flush()
            cur = Block(kind="bullet", lines=[bullet.group(1)])
            expected_item = 1
            prev_blank = False
            continue

        # "Step 4: ..." always starts a new block, even mid-paragraph-run.
        if _STEP_RE.match(text) and indent <= 4:
            flush()
            cur = Block(kind="para", lines=[text])
            prev_blank = False
            continue

        # Plain body line: continues the current block, unless a page boundary
        # makes continuation implausible.  A paragraph that runs off the bottom
        # of a page mid-sentence must be stitched back together; one that ended
        # its sentence there is left as a separate block.
        if cur is not None and new_page:
            tail = cur.lines[-1] if cur.lines else ""
            unfinished = tail.endswith("-") or not _SENT_END_RE.search(tail)
            if not (unfinished or _LOWER_START_RE.match(text)):
                flush()
        if cur is None or cur.kind == "table":
            flush()
            cur = Block(kind="para")
        cur.lines.append(text)
        prev_blank = False

    flush()
    return _merge_orphans(blocks)


def _merge_orphans(blocks: list[Block]) -> list[Block]:
    """Re-attach a stray fragment to the block it was split from.

    Exports routinely give the tail of a wrapped sentence its own visual block —
    typically a cross-reference that landed alone ("... in accordance with" /
    "SOP-QC-004.").  Left alone it becomes a bogus one-line section; joined, the
    sentence and its cross-reference are both intact.
    """
    out: list[Block] = []
    for block in blocks:
        prev = out[-1] if out else None
        if (
            prev is not None
            and block.kind == "para"
            and not block.toc_listed
            and prev.kind in ("para", "item", "bullet")
            and not _SENT_END_RE.search(prev.text)
            and len(block.text.split()) <= 6
        ):
            prev.text = f"{prev.text} {block.text}"
            prev.lines.append(block.text)
            continue
        out.append(block)
    return out


# ---------------------------------------------------------------------------
# 6. Cross-document boilerplate (cover/tail matter that survived page cleanup)
# ---------------------------------------------------------------------------


def drop_shared_boilerplate(docs: list["DocResult"]) -> None:
    """Drop opening/closing matter that recurs across the whole batch.

    Same principle as page-furniture detection, one level up: the closing
    "END OF PROCEDURE / printed copies are uncontrolled" matter is identical in
    every export from a given DMS, while real content is not.  Guards, because
    deleting content from a GMP record is far worse than leaving boilerplate in:

    * only lines at the very edge of the document are eligible, and the scan
      stops at the first line that does not recur — so a recurring line in the
      middle of the text is never touched;
    * a line naming another SOP or a regulation is never dropped (that would
      silently corrupt the dependency graph and the citation audit);
    * table rows and table-of-contents headings are never dropped;
    * the recurrence bar is high (most of the batch), because two document
      templates in one corpus should fail closed, not delete each other's text.
    """
    n_docs = len(docs)
    if n_docs < 3:
        return

    zones: dict[int, tuple[list[Line], list[Line]]] = {}
    counts: Counter[str] = Counter()
    for doc in docs:
        kept = [ln for page in doc._pages for ln in page if not ln.drop and not ln.blank]
        head, tail = kept[:EDGE_LINES], kept[-EDGE_LINES:]
        zones[id(doc)] = (head, tail)
        counts.update({
            _norm_key(ln.raw) for ln in head + tail if _boilerplate_candidate(ln, doc)
        })

    threshold = max(3, math.ceil(BOILERPLATE_SHARE * n_docs))
    for doc in docs:
        head, tail = zones[id(doc)]
        for sequence in (list(reversed(tail)), head):
            for ln in sequence:
                if not _boilerplate_candidate(ln, doc) or counts[_norm_key(ln.raw)] < threshold:
                    break
                ln.drop = "shared-boilerplate"
                doc.boilerplate_lines += 1


def _boilerplate_candidate(line: Line, doc: "DocResult") -> bool:
    text = line.text
    if not text or _is_table_row(line.raw):
        return False
    if _toc_key(text) in doc._toc_titles:
        return False
    if any(ref != doc.sop_id for ref in SOP_ID_RE.findall(text)):
        return False
    return not _CITATION_HINT_RE.search(text)


# ---------------------------------------------------------------------------
# 7. Markdown rendering
# ---------------------------------------------------------------------------


def _safe_wrap(text: str, width: int = WRAP_WIDTH, indent: str = "  ") -> list[str]:
    """Wrap a list item for readability, without inventing structure.

    Only list items are wrapped, and their continuation lines are indented —
    that is how the corpus marks "still the same item", and modules that parse
    numbered procedures out of the raw body rely on it.  Paragraphs are left as
    one line each: a paragraph that begins "Step 4: ..." would otherwise look
    like a numbered step whose unindented second line ends the procedure.

    A wrapped line that would read as an ALL-CAPS heading or a new step to the
    loader defeats the purpose, so in that case the item stays on one line.
    """
    lines = textwrap.wrap(text, width=width, subsequent_indent=indent,
                          break_long_words=False, break_on_hyphens=False)
    if not lines:
        return [text]
    for ln in lines[1:]:
        if _is_caps_line(ln) or _ITEM_RE.match(ln.strip()) or _BULLET_RE.match(ln.strip()):
            return [text]
    return lines


def _markdown_table(rows: list[list[str]]) -> list[str]:
    """Render recovered table cells as a Markdown pipe table.

    A revision-history grid that stays as space-aligned columns reads to the
    loader as a run of sentence fragments; as a pipe table it is a table again.
    """
    if not rows:
        return []
    width = max(len(r) for r in rows)
    padded = [[c.replace("|", "\\|") for c in r] + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(padded[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in padded[1:]]
    return out


def _yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_markdown(meta: dict[str, str], blocks: list[Block]) -> str:
    order = ["sop_id", "title", "department", "department_code", "site", "version",
             "effective_date", "next_review", "owner", "language", "parent", "status",
             "source_pdf"]
    out: list[str] = ["---"]
    for key in order:
        value = meta.get(key)
        if not value:
            continue
        if key in ("effective_date", "next_review"):
            out.append(f"{key}: {value}")           # plain ISO scalar, as in data/sops
        else:
            out.append(f"{key}: {_yaml_scalar(value)}")
    out.append("---")
    out.append("")

    body: list[str] = []
    prev_kind = ""
    for block in blocks:
        if block.kind == "heading":
            if body and body[-1] != "":
                body.append("")
            body.append(block.text if block.caps else f"## {block.text}")
            body.append("")
        elif block.kind == "item":
            if prev_kind != "item" and body and body[-1] != "":
                body.append("")
            body.extend(_safe_wrap(f"{block.marker} {block.text}", indent="   "))
        elif block.kind == "bullet":
            if prev_kind != "bullet" and body and body[-1] != "":
                body.append("")
            body.extend(_safe_wrap(f"- {block.text}", indent="  "))
        elif block.kind == "table":
            if body and body[-1] != "":
                body.append("")
            body.extend(_markdown_table(block.rows))
        else:
            if body and body[-1] != "":
                body.append("")
            body.append(block.text)
        prev_kind = block.kind

    out.extend(body)
    text = "\n".join(out).rstrip() + "\n"
    return re.sub(r"\n{3,}", "\n\n", text)


# ---------------------------------------------------------------------------
# 8. Per-document conversion + quality assessment
# ---------------------------------------------------------------------------


@dataclass
class DocResult:
    pdf: Path
    sop_id: str = ""
    status: str = "converted"          # converted | needs_ocr | error
    meta: Meta = field(default_factory=Meta)
    blocks: list[Block] = field(default_factory=list)
    pages: int = 0
    empty_pages: int = 0
    raw_chars: int = 0
    body_chars: int = 0
    furniture_lines: int = 0
    furniture_samples: list[str] = field(default_factory=list)
    toc_rows: int = 0
    cover_dropped: bool = False
    boilerplate_lines: int = 0
    sections: int = 0
    numbered_steps: int = 0
    cross_refs: list[str] = field(default_factory=list)
    self_refs: int = 0
    citations: int = 0
    sentences: int = 0
    words: int = 0
    fragments: int = 0
    hyphen_leftovers: int = 0
    hyphens_joined: int = 0
    hyphens_kept: int = 0
    furniture_leftovers: int = 0
    missing_fields: list[str] = field(default_factory=list)
    confidence: str = "low"
    reasons: list[str] = field(default_factory=list)
    out_path: Path | None = None
    # working state carried between stages
    _pages: list[list[Line]] = field(default_factory=list, repr=False)
    _toc_titles: set[str] = field(default_factory=set, repr=False)

    @property
    def needs_review(self) -> bool:
        return self.confidence != "high" or self.status != "converted"


REQUIRED_FIELDS = ("sop_id", "title")
RECOMMENDED_FIELDS = ("department", "version", "effective_date", "next_review", "owner", "status")


def stage_one(pdf: Path, use_ocr: bool) -> DocResult:
    """Extract, strip furniture/TOC/cover, recover frontmatter.  No writing yet."""
    doc = DocResult(pdf=pdf)
    raw_pages = extract_pages(pdf)
    doc.pages = len(raw_pages)
    doc.raw_chars = sum(len(_WS_RE.sub("", p)) for p in raw_pages)
    doc.empty_pages = sum(1 for p in raw_pages if len(_WS_RE.sub("", p)) < MIN_PAGE_CHARS)

    if use_ocr and doc.empty_pages:
        for i, page in enumerate(raw_pages):
            if len(_WS_RE.sub("", page)) < MIN_PAGE_CHARS:
                raw_pages[i] = ocr_page(pdf, i + 1)
        doc.raw_chars = sum(len(_WS_RE.sub("", p)) for p in raw_pages)
        doc.empty_pages = sum(1 for p in raw_pages if len(_WS_RE.sub("", p)) < MIN_PAGE_CHARS)
        doc.reasons.append("OCR fallback used on image-only pages")

    if doc.raw_chars < MIN_DOC_CHARS or doc.empty_pages == doc.pages:
        doc.status = "needs_ocr"
        doc.sop_id = _fallback_id(pdf)
        doc.confidence = "low"
        doc.reasons.append(
            f"only {doc.raw_chars} extractable characters across {doc.pages} page(s) — "
            "the PDF looks scanned/image-only; re-export it with a text layer or run --ocr"
        )
        return doc

    pages = [
        [Line(raw=raw, page=pi, idx=li) for li, raw in enumerate(page.split("\n"))]
        for pi, page in enumerate(raw_pages)
    ]
    doc.furniture_lines, doc.furniture_samples = strip_furniture(pages)
    furniture_text = "\n".join(ln.raw for page in pages for ln in page if ln.drop)
    toc_titles, doc.toc_rows = strip_toc(pages)
    doc.meta, cover_idx = recover_metadata(pages, furniture_text, pdf)
    doc.sop_id = doc.meta.values.get("sop_id", _fallback_id(pdf))

    if cover_idx >= 0 and len(pages) > 1:
        cover = pages[cover_idx]
        # Only content *below* the metadata grid counts: the title printed above
        # it often repeats a section name and must not keep the cover alive.
        last_meta = max(
            (ln.idx for ln in cover if not ln.drop and _label_pairs(ln.raw)), default=-1
        )
        body_signals = sum(
            1 for ln in cover
            if ln.idx > last_meta and not ln.drop and not ln.blank
            and (_toc_key(ln.text) in toc_titles or _ITEM_RE.match(ln.text))
        )
        if body_signals < 2:
            for ln in cover:
                if not ln.drop and not ln.blank:
                    ln.drop = "cover-page"
            doc.cover_dropped = True
    doc._pages = pages
    doc._toc_titles = toc_titles
    return doc


def _fallback_id(pdf: Path) -> str:
    m = SOP_ID_RE.search(pdf.stem.upper())
    return m.group(0) if m else pdf.stem.strip()


def stage_two(doc: DocResult, dehy: Dehyphenator) -> None:
    """Reflow the surviving lines into blocks."""
    if doc.status != "converted":
        return
    dehy.reset()
    doc.blocks = build_blocks(doc._pages, doc._toc_titles, dehy)
    doc.hyphens_joined, doc.hyphens_kept = dehy.joined, dehy.kept
    # A hyphen can only survive un-adjudicated where a block ended: everything
    # inside a block went through the de-hyphenator.
    doc.hyphen_leftovers = sum(1 for b in doc.blocks if b.text.endswith("-"))


def finalize(doc: DocResult, out_dir: Path, dept_names: dict[str, str], kb,
             known_ids: set[str] | None = None) -> None:
    """Write the Markdown file and score the conversion."""
    if doc.status != "converted":
        return
    meta = dict(doc.meta.values)
    meta["sop_id"] = doc.sop_id
    dept_code = _department_code(doc.sop_id)
    if dept_code:
        meta["department_code"] = dept_code
    # A translated variant ("SOP-CLN-001-ES") names its parent in its own id.
    # Only emitted when that parent is actually present in this batch.
    m = re.fullmatch(r"(SOP-[A-Z]{2,4}-\d{3})-[A-Z]{2}", doc.sop_id.upper())
    if m and known_ids and m.group(1) in known_ids:
        meta["parent"] = m.group(1)
        doc.meta.sources["parent"] = "derived from sop_id suffix"
    if "language" not in meta:
        sniffed = sniff_language(" ".join(b.text for b in doc.blocks))
        if sniffed:
            meta["language"] = sniffed
            doc.meta.sources["language"] = "text heuristic"
    meta["source_pdf"] = doc.pdf.name

    body = render_markdown(meta, doc.blocks)
    out_path = out_dir / f"{_safe_name(doc.sop_id)}.md"
    out_path.write_text(body, encoding="utf-8")
    doc.out_path = out_path

    sop = load_sop(out_path, dept_names)
    doc.sections = len(sop.sections)
    doc.cross_refs = sop.cross_references
    doc.self_refs = sum(1 for r in SOP_ID_RE.findall(sop.body) if r == doc.sop_id)
    doc.numbered_steps = len(re.findall(r"^\s{0,3}\d{1,2}[.)]\s", sop.body, re.MULTILINE))
    doc.sentences = len(sop.sentences)
    doc.words = len(sop.words)
    doc.fragments = sum(1 for s in sop.sentences if len(_words(s)) < 4)
    doc.body_chars = len(sop.body)
    doc.furniture_leftovers = len(_PAGE_OF_RE.findall(sop.body))
    doc.citations = len(kb.extract(doc.sop_id, sop.body)) if kb else 0
    _score(doc, meta)


def _department_code(sop_id: str) -> str:
    m = re.match(r"SOP-([A-Z]{2,4})-", sop_id.upper())
    return m.group(1) if m else ""


def _safe_name(sop_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", sop_id).strip("_") or "document"


def _score(doc: DocResult, meta: dict[str, str]) -> None:
    """Assign high/medium/low confidence with an explicit reason for each demotion."""
    missing = [f for f in REQUIRED_FIELDS + RECOMMENDED_FIELDS if not meta.get(f)]
    doc.missing_fields = missing
    low: list[str] = []
    med: list[str] = []

    if doc.body_chars < MIN_BODY_CHARS:
        low.append(f"only {doc.body_chars} characters of body text survived cleanup")
    if doc.sections == 0:
        low.append("no section headings detected")
    for f in REQUIRED_FIELDS:
        if not meta.get(f):
            low.append(f"required frontmatter field '{f}' not found in the document")
    if doc.empty_pages:
        low.append(f"{doc.empty_pages} of {doc.pages} pages yielded no text")
    if doc.meta.sources.get("sop_id") == "filename":
        med.append("sop_id came from the filename, not from the document text")

    recommended_missing = [f for f in RECOMMENDED_FIELDS if not meta.get(f)]
    if recommended_missing:
        med.append("frontmatter not found: " + ", ".join(recommended_missing))
    if doc.pages > 2 and doc.furniture_lines == 0:
        med.append("no repeated header/footer detected on a multi-page PDF — "
                   "page furniture may still be in the body")
    if doc.furniture_leftovers:
        med.append(f"{doc.furniture_leftovers} page-number line(s) still in the body — "
                   "header/footer stripping was incomplete")
    if doc.self_refs > 2:
        med.append(f"body still names its own id {doc.self_refs} times — possible header leakage")
    if doc.sections and doc.sections < 3:
        med.append(f"only {doc.sections} section(s) detected")
    if doc.hyphen_leftovers:
        med.append(f"{doc.hyphen_leftovers} block(s) end mid-word — a hyphenated break "
                   "was not re-joined")
    med.extend(doc.meta.notes)

    if low:
        doc.confidence, doc.reasons = "low", low + med
    elif med:
        doc.confidence, doc.reasons = "medium", med
    else:
        doc.confidence, doc.reasons = "high", []


# ---------------------------------------------------------------------------
# 9. Reporting
# ---------------------------------------------------------------------------


def build_report(docs: list[DocResult], pdf_dir: Path, out_dir: Path, used_ocr: bool) -> dict:
    converted = [d for d in docs if d.status == "converted"]
    return {
        "tool": "sop_pipeline.ingest",
        "extractor": f"pdftotext -layout (poppler {poppler_version()})",
        "pdf_dir": str(pdf_dir),
        "out_dir": str(out_dir),
        "ocr_fallback": used_ocr,
        "totals": {
            "pdfs_seen": len(docs),
            "converted": len(converted),
            "needs_ocr": sum(1 for d in docs if d.status == "needs_ocr"),
            "errors": sum(1 for d in docs if d.status == "error"),
            "needs_review": sum(1 for d in docs if d.needs_review),
            "confidence": {
                level: sum(1 for d in docs if d.confidence == level)
                for level in ("high", "medium", "low")
            },
            "pages": sum(d.pages for d in docs),
            "furniture_lines_stripped": sum(d.furniture_lines for d in docs),
            "sections": sum(d.sections for d in converted),
            "numbered_steps": sum(d.numbered_steps for d in converted),
            "cross_references": sum(len(d.cross_refs) for d in converted),
            "citations": sum(d.citations for d in converted),
        },
        "documents": [
            {
                "sop_id": d.sop_id,
                "source_pdf": d.pdf.name,
                "output": d.out_path.name if d.out_path else None,
                "status": d.status,
                "confidence": d.confidence,
                "needs_review": d.needs_review,
                "reasons": d.reasons,
                "pages": d.pages,
                "empty_pages": d.empty_pages,
                "chars_extracted": d.raw_chars,
                "chars_body": d.body_chars,
                "furniture_lines_stripped": d.furniture_lines,
                "furniture_examples": d.furniture_samples,
                "toc_rows_stripped": d.toc_rows,
                "cover_page_dropped": d.cover_dropped,
                "shared_boilerplate_lines_dropped": d.boilerplate_lines,
                "frontmatter_found": {k: d.meta.values[k] for k in sorted(d.meta.values)},
                "frontmatter_sources": {k: d.meta.sources[k] for k in sorted(d.meta.sources)},
                "frontmatter_missing": d.missing_fields,
                "sections_detected": d.sections,
                "numbered_steps": d.numbered_steps,
                "cross_references": d.cross_refs,
                "self_references_in_body": d.self_refs,
                "citations": d.citations,
                "sentences": d.sentences,
                "words": d.words,
                "mean_words_per_sentence": round(d.words / d.sentences, 1) if d.sentences else 0,
                "short_sentences": d.fragments,
                "hyphen_breaks_rejoined": d.hyphens_joined,
                "hyphen_breaks_kept_as_compound": d.hyphens_kept,
                "hyphen_breaks_unresolved": d.hyphen_leftovers,
                "page_number_lines_left_in_body": d.furniture_leftovers,
            }
            for d in docs
        ],
    }


def print_table(docs: list[DocResult]) -> None:
    header = (
        f"{'SOP ID':<16}{'st':>3}{'pg':>4}{'chars':>7}{'furn':>6}{'sec':>5}"
        f"{'step':>6}{'xref':>6}{'cite':>6}{'miss':>6}  {'confidence':<11}reason"
    )
    print(header)
    print("-" * min(len(header) + 30, 140))
    for d in sorted(docs, key=lambda x: ({"low": 0, "medium": 1, "high": 2}[x.confidence], x.sop_id)):
        reason = d.reasons[0] if d.reasons else ""
        if len(reason) > 46:
            reason = reason[:43] + "..."
        flag = {"converted": "ok", "needs_ocr": "!!", "error": "XX"}[d.status]
        print(
            f"{d.sop_id:<16}{flag:>3}{d.pages:>4}{d.raw_chars:>7}{d.furniture_lines:>6}"
            f"{d.sections:>5}{d.numbered_steps:>6}{len(d.cross_refs):>6}{d.citations:>6}"
            f"{len(d.missing_fields):>6}  {d.confidence:<11}{reason}"
        )


# ---------------------------------------------------------------------------
# 10. CLI
# ---------------------------------------------------------------------------


def convert(pdf_dir: Path, out_dir: Path, limit: int | None = None,
            use_ocr: bool = False) -> list[DocResult]:
    """Convert every PDF under ``pdf_dir`` into ``out_dir``."""
    pdfs = sorted(p for p in pdf_dir.glob("*.pdf") if p.is_file())
    pdfs += sorted(p for p in pdf_dir.glob("*.PDF") if p.is_file() and p not in pdfs)
    pdfs = sorted(set(pdfs))
    if limit is not None:
        pdfs = pdfs[:limit]
    if not pdfs:
        raise IngestError(f"no PDF files found in {pdf_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    dept_names = manifest.get("departments", {})
    kb = RegKB.from_manifest(manifest) if RegKB else None

    docs: list[DocResult] = []
    for pdf in pdfs:
        try:
            docs.append(stage_one(pdf, use_ocr))
        except IngestError:
            raise
        except Exception as exc:  # pragma: no cover - malformed PDF
            bad = DocResult(pdf=pdf, sop_id=_fallback_id(pdf), status="error")
            bad.confidence = "low"
            bad.reasons = [f"extraction failed: {exc}"]
            docs.append(bad)

    ok = [d for d in docs if d.status == "converted"]
    drop_shared_boilerplate(ok)
    vocab, hyphenated = build_vocabulary(
        [ln.raw for d in ok for page in d._pages for ln in page if not ln.drop]
    )
    dehy = Dehyphenator(vocab, hyphenated)
    for doc in ok:
        stage_two(doc, dehy)

    seen: dict[str, int] = {}
    for doc in ok:
        n = seen.get(doc.sop_id, 0)
        seen[doc.sop_id] = n + 1
        if n:
            doc.reasons.append(f"duplicate sop_id: written as {doc.sop_id}-{n}")
            doc.sop_id = f"{doc.sop_id}-{n}"
    known_ids = {d.sop_id.upper() for d in ok}
    for doc in ok:
        finalize(doc, out_dir, dept_names, kb, known_ids)
    return docs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m sop_pipeline.ingest",
        description="Convert digital-native SOP PDFs into pipeline-ready Markdown.",
    )
    ap.add_argument("--pdf-dir", type=Path, required=True, help="directory of source PDFs")
    ap.add_argument("--out", type=Path, required=True, help="directory for the Markdown output")
    ap.add_argument("--report", type=Path, default=None,
                    help="quality report path (default: <out>/ingest_report.json)")
    ap.add_argument("--limit", type=int, default=None, help="convert only the first N PDFs")
    ap.add_argument("--ocr", action="store_true",
                    help="OCR pages with no text layer (needs pdftoppm + tesseract)")
    ap.add_argument("--quiet", action="store_true", help="suppress the per-document table")
    args = ap.parse_args(argv)

    pdf_dir: Path = args.pdf_dir.expanduser().resolve()
    out_dir: Path = args.out.expanduser().resolve()
    if not pdf_dir.is_dir():
        print(f"ingest: --pdf-dir {pdf_dir} is not a directory", file=sys.stderr)
        return 2
    try:
        docs = convert(pdf_dir, out_dir, args.limit, args.ocr)
    except IngestError as exc:
        print(f"ingest: {exc}", file=sys.stderr)
        return 2

    report = build_report(docs, pdf_dir, out_dir, args.ocr)
    report_path = args.report.expanduser().resolve() if args.report else out_dir / "ingest_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not args.quiet:
        print_table(docs)
        print()
    t = report["totals"]
    print(f"Converted {t['converted']}/{t['pdfs_seen']} PDFs -> {out_dir}")
    print(f"  pages {t['pages']}, furniture lines stripped {t['furniture_lines_stripped']}, "
          f"sections {t['sections']}, steps {t['numbered_steps']}, "
          f"cross-refs {t['cross_references']}, citations {t['citations']}")
    print(f"  confidence: high {t['confidence']['high']}, medium {t['confidence']['medium']}, "
          f"low {t['confidence']['low']}"
          + (f", needs OCR {t['needs_ocr']}" if t["needs_ocr"] else "")
          + (f", errors {t['errors']}" if t["errors"] else ""))
    print(f"  NEEDS REVIEW: {t['needs_review']} document(s) — see {report_path}")
    if t["needs_review"]:
        for d in docs:
            if d.needs_review:
                why = d.reasons[0] if d.reasons else "see report"
                print(f"    - {d.sop_id} [{d.confidence}] {why}")

    if t["converted"] == 0:
        print("ingest: nothing was converted", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
