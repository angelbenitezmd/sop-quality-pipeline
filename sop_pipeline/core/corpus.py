"""Corpus data model and loader.

An SOP on disk is a Markdown file with YAML frontmatter (see data/sops/*.md).
This module parses those files into `SOP` objects and groups them into a `Corpus`.

Every pipeline module receives a `Corpus` and writes artifacts into its own output
directory. Modules should treat SOP fields as read-only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# .../sop_pipeline/core/corpus.py -> project root is three parents up
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
SOP_DIR = DATA_DIR / "sops"
MANIFEST_PATH = DATA_DIR / "corpus_manifest.json"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Matches an SOP identifier anywhere in prose, e.g. "SOP-CLN-001" or "SOP-CLN-001-ES".
SOP_ID_RE = re.compile(r"SOP-[A-Z]{2,4}-\d{3}(?:-[A-Z]{2})?")

# A section heading: markdown "## 3. Title", "## Title", or all-caps "3. TITLE".
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")

# Bare roman-numeral headings ("I. Purpose", "VII. Calculation and Acceptance Criteria").
# QC-style SOPs number their sections this way with no '#' and no all-caps, so without
# this they collapse into a single section. Kept deliberately strict — a valid roman
# numeral, a short title-cased remainder, and no sentence-ending period — so ordinary
# prose beginning "I." is not mistaken for a heading.
_ROMAN_HEADING_RE = re.compile(
    r"^\s{0,3}"
    r"(?=[IVXLC])(?:M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"
    r"[.)]\s+"
    r"([A-Z][A-Za-z0-9][^.!?]{1,70})\s*$"
)


@dataclass
class Section:
    """A single heading + its body text within an SOP."""

    heading: str
    body: str
    index: int

    @property
    def text(self) -> str:
        return f"{self.heading}\n{self.body}".strip()


@dataclass
class SOP:
    """One parsed SOP document."""

    sop_id: str
    title: str
    department: str  # department code, e.g. "CLN"
    department_name: str
    path: Path
    frontmatter: dict = field(default_factory=dict)
    body: str = ""

    # -- convenience frontmatter accessors ---------------------------------
    @property
    def version(self) -> str:
        return str(self.frontmatter.get("version", ""))

    @property
    def language(self) -> str:
        return str(self.frontmatter.get("language", "en")).lower()

    @property
    def owner(self) -> str:
        return str(self.frontmatter.get("owner", ""))

    @property
    def effective_date(self) -> str:
        return str(self.frontmatter.get("effective_date", ""))

    @property
    def next_review(self) -> str:
        return str(self.frontmatter.get("next_review", ""))

    @property
    def status(self) -> str:
        return str(self.frontmatter.get("status", "Effective"))

    @property
    def parent_id(self) -> str | None:
        """For translated variants, the EN parent SOP id (from frontmatter)."""
        p = self.frontmatter.get("parent")
        return str(p) if p else None

    # -- derived text views ------------------------------------------------
    @property
    def full_text(self) -> str:
        """Title + body — the canonical text used for NLP/similarity."""
        return f"{self.title}\n{self.body}".strip()

    @cached_property
    def sections(self) -> list[Section]:
        return _split_sections(self.body)

    @cached_property
    def sentences(self) -> list[str]:
        return split_sentences(self.body)

    @cached_property
    def words(self) -> list[str]:
        return re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+", self.body)

    @cached_property
    def cross_references(self) -> list[str]:
        """All SOP ids referenced in the body, excluding self, de-duplicated,
        order-preserving."""
        seen: dict[str, None] = {}
        for m in SOP_ID_RE.findall(self.body):
            if m != self.sop_id:
                seen.setdefault(m, None)
        return list(seen.keys())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"SOP({self.sop_id}, {self.title!r}, {len(self.words)} words)"


class Corpus:
    """A collection of SOPs plus the manifest that describes ground truth."""

    def __init__(self, sops: list[SOP], manifest: dict | None = None):
        self.sops = sops
        self.manifest = manifest or {}
        self._by_id = {s.sop_id: s for s in sops}

    # -- container protocol ------------------------------------------------
    def __iter__(self) -> Iterable[SOP]:
        return iter(self.sops)

    def __len__(self) -> int:
        return len(self.sops)

    def __getitem__(self, sop_id: str) -> SOP:
        return self._by_id[sop_id]

    def get(self, sop_id: str) -> SOP | None:
        return self._by_id.get(sop_id)

    @property
    def ids(self) -> list[str]:
        return [s.sop_id for s in self.sops]

    def english(self) -> list[SOP]:
        return [s for s in self.sops if s.language == "en"]

    def by_department(self) -> dict[str, list[SOP]]:
        groups: dict[str, list[SOP]] = {}
        for s in self.sops:
            groups.setdefault(s.department, []).append(s)
        return groups

    # -- manifest helpers --------------------------------------------------
    def manifest_entry(self, sop_id: str) -> dict:
        for entry in self.manifest.get("sops", []):
            if entry.get("sop_id") == sop_id:
                return entry
        return {}

    def department_name(self, code: str) -> str:
        return self.manifest.get("departments", {}).get(code, code)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a leading YAML frontmatter block from the body.

    Uses PyYAML when available, otherwise a small line-based fallback so the
    loader never hard-depends on yaml for such simple documents.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw, body = m.group(1), m.group(2)
    try:
        import yaml  # type: ignore

        meta = yaml.safe_load(raw) or {}
        if not isinstance(meta, dict):
            meta = {}
        return meta, body
    except Exception:
        return _fallback_frontmatter(raw), body


def _fallback_frontmatter(raw: str) -> dict:
    meta: dict = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip().strip('"').strip("'")
        meta[key.strip()] = val
    return meta


def _split_sections(body: str) -> list[Section]:
    """Split body into sections on markdown or all-caps headings."""
    lines = body.splitlines()
    sections: list[Section] = []
    cur_heading = "Preamble"
    cur_lines: list[str] = []
    idx = 0

    def flush():
        nonlocal idx
        text_body = "\n".join(cur_lines).strip()
        if cur_heading != "Preamble" or text_body:
            sections.append(Section(heading=cur_heading, body=text_body, index=idx))
            idx += 1

    for line in lines:
        md = _MD_HEADING_RE.match(line)
        is_caps_heading = bool(
            re.match(r"^\s{0,3}(\d+(\.\d+)*\.?\s+)?[A-ZÁÉÍÓÚÜÑ0-9][A-ZÁÉÍÓÚÜÑ0-9 &/\-,()]{4,}\s*$", line)
            and sum(c.isalpha() for c in line) >= 4
            and line.strip() == line.strip().upper()
        )
        roman = _ROMAN_HEADING_RE.match(line)
        if md:
            flush()
            cur_heading = md.group(1).strip()
            cur_lines = []
        elif roman:
            flush()
            cur_heading = line.strip()
            cur_lines = []
        elif is_caps_heading:
            flush()
            cur_heading = line.strip()
            cur_lines = []
        else:
            cur_lines.append(line)
    flush()
    return sections


_ABBREV = {
    "no.", "fig.", "e.g.", "i.e.", "etc.", "vs.", "approx.", "min.", "max.",
    "sec.", "std.", "rev.", "ref.", "dr.", "mr.", "ms.", "cfr.", "vol.",
}


def split_sentences(text: str) -> list[str]:
    """Lightweight sentence splitter tolerant of abbreviations and decimals.

    Good enough for readability metrics; not a full NLP tokenizer.
    """
    # Protect decimals like "0.5" and known abbreviations from being split.
    protected = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", text)
    # Split on sentence-final punctuation followed by whitespace + capital/number.
    pieces = re.split(r"(?<=[.!?])\s+(?=[\"'(A-Z0-9])", protected)
    out: list[str] = []
    for p in pieces:
        p = p.replace("<DOT>", ".").strip()
        if not p:
            continue
        # Merge fragments that end in a known abbreviation with the next piece.
        if out and out[-1].split()[-1].lower() in _ABBREV:
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_manifest(path: Path | None = None) -> dict:
    path = path or MANIFEST_PATH
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_sop(path: Path, dept_names: dict[str, str] | None = None) -> SOP:
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    sop_id = str(meta.get("sop_id") or path.stem).strip()
    dept_code = str(meta.get("department_code") or _infer_dept(sop_id)).strip()
    dept_name = (dept_names or {}).get(dept_code) or str(meta.get("department", dept_code))
    return SOP(
        sop_id=sop_id,
        title=str(meta.get("title", sop_id)),
        department=dept_code,
        department_name=dept_name,
        path=path,
        frontmatter=meta,
        body=body.strip(),
    )


def _infer_dept(sop_id: str) -> str:
    m = re.match(r"SOP-([A-Z]{2,4})-", sop_id)
    return m.group(1) if m else "UNK"


def load_corpus(sop_dir: Path | None = None, manifest_path: Path | None = None) -> Corpus:
    """Load every *.md SOP under ``sop_dir`` and attach the manifest."""
    sop_dir = sop_dir or SOP_DIR
    manifest = load_manifest(manifest_path)
    dept_names = manifest.get("departments", {})
    paths = sorted(sop_dir.glob("*.md"))
    sops = [load_sop(p, dept_names) for p in paths]
    return Corpus(sops, manifest)


if __name__ == "__main__":  # pragma: no cover - smoke test
    c = load_corpus()
    print(f"Loaded {len(c)} SOPs from {SOP_DIR}")
    for dept, group in c.by_department().items():
        print(f"  {dept:5s} {c.department_name(dept):40s} {len(group)}")
    total_refs = sum(len(s.cross_references) for s in c)
    print(f"Total cross-references parsed: {total_refs}")
