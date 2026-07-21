"""Regulatory knowledge base and citation extraction.

`m05_regaudit` uses this to pull every regulatory citation out of an SOP's prose
and decide whether the cited version is current, outdated, or needs review.

The 'current version' ground truth is loaded from the corpus manifest
(``regulatory_current_versions``) so the KB and the mock data can never drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Citation extraction patterns. Each returns a canonical citation key that maps
# into the manifest's regulatory_current_versions table.
# ---------------------------------------------------------------------------

# Ordered list of (regex, canonicalizer). First match wins per span.
_CITATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"21\s*CFR\s*Part\s*11\b", re.IGNORECASE), "21 CFR Part 11"),
    (re.compile(r"21\s*CFR\s*(?:Part\s*)?(\d{3}\.\d{1,3})\b", re.IGNORECASE), "21 CFR {0}"),
    (re.compile(r"ICH\s*Q2\s*\(?R\s*2\)?", re.IGNORECASE), "ICH Q2(R2)"),
    (re.compile(r"ICH\s*Q2\s*\(?R\s*1\)?", re.IGNORECASE), "ICH Q2(R1)"),
    (re.compile(r"ICH\s*Q9\s*\(?R\s*1\)?", re.IGNORECASE), "ICH Q9(R1)"),
    (re.compile(r"ICH\s*Q9(?!\s*\(?R)", re.IGNORECASE), "ICH Q9"),
    (re.compile(r"ICH\s*Q10\b", re.IGNORECASE), "ICH Q10"),
    (re.compile(r"ICH\s*Q7\b", re.IGNORECASE), "ICH Q7"),
    (re.compile(r"EU\s*GMP\s*Annex\s*1\b(?!\d)", re.IGNORECASE), "EU GMP Annex 1"),
    (re.compile(r"EU\s*GMP\s*Annex\s*15\b", re.IGNORECASE), "EU GMP Annex 15"),
    (re.compile(r"Annex\s*1\b(?!\d)", re.IGNORECASE), "EU GMP Annex 1"),
    (re.compile(r"Annex\s*15\b", re.IGNORECASE), "EU GMP Annex 15"),
    (re.compile(r"USP\s*<\s*1058\s*>", re.IGNORECASE), "USP <1058>"),
    (re.compile(r"USP\s*<\s*797\s*>", re.IGNORECASE), "USP <797>"),
    (re.compile(r"USP\s*<\s*71\s*>", re.IGNORECASE), "USP <71>"),
    (re.compile(r"USP\s*<\s*85\s*>", re.IGNORECASE), "USP <85>"),
    (re.compile(r"ISO\s*14644-1(?:\s*:\s*(\d{4}))?", re.IGNORECASE), "ISO 14644-1"),
    (re.compile(r"ISO\s*13408-1\b", re.IGNORECASE), "ISO 13408-1"),
    (re.compile(r"PDA\s*TR-?\s*60\b", re.IGNORECASE), "PDA TR-60"),
    (re.compile(r"PDA\s*TR-?\s*70\b", re.IGNORECASE), "PDA TR-70"),
    (re.compile(r"GAMP\s*5\b", re.IGNORECASE), "GAMP 5"),
    (re.compile(r"ISPE\s*Baseline\s*Guide[:\s].{0,20}?CIP", re.IGNORECASE), "ISPE Baseline Guide: CIP"),
    (re.compile(r"ISPE\b.{0,20}?\bCIP\b", re.IGNORECASE), "ISPE Baseline Guide: CIP"),
]

# Version designations appearing near a citation, e.g. "(2015 revision)", "Rev 2001",
# ":1999", "2nd Ed", "1st Ed", "R1".
_VERSION_NEAR_RE = re.compile(
    r"(\b\d{4}\s*(?:revision|rev\.?|edition|ed\.?)?"
    r"|(?:rev\.?|revision|edition)\s*\d{4}"
    r"|:\s*\d{4}"
    r"|\d(?:st|nd|rd|th)\s*ed(?:ition)?"
    r"|\(?R\s*\d\)?)",
    re.IGNORECASE,
)


@dataclass
class Citation:
    """One extracted regulatory citation from an SOP."""

    sop_id: str
    canonical: str          # e.g. "EU GMP Annex 1"
    as_written: str         # the exact substring found, incl. any version text
    version_text: str       # extracted version designation, if any
    status: str             # "current" | "outdated" | "review" | "unknown"
    current_version: str    # what the KB says is current
    topic: str
    action: str             # human-readable remediation

    def as_row(self) -> dict:
        return {
            "sop_id": self.sop_id,
            "reference": self.canonical,
            "as_written": self.as_written,
            "status": self.status,
            "current_version": self.current_version,
            "action": self.action,
        }


class RegKB:
    """Regulatory version table + citation classifier."""

    def __init__(self, current_versions: dict):
        # strip the informational "note" key if present
        self.table = {k: v for k, v in current_versions.items() if isinstance(v, dict)}

    @classmethod
    def from_manifest(cls, manifest: dict) -> "RegKB":
        return cls(manifest.get("regulatory_current_versions", {}))

    # -- extraction --------------------------------------------------------
    def extract(self, sop_id: str, text: str) -> list[Citation]:
        """Find and classify every regulatory citation in ``text``."""
        found: dict[str, Citation] = {}
        for rx, template in _CITATION_PATTERNS:
            for m in rx.finditer(text):
                canonical = template.format(*m.groups()) if "{0}" in template else template
                # window of context after the match for version detection
                end = min(len(text), m.end() + 30)
                vmatch = _VERSION_NEAR_RE.search(text[m.end():end])
                version_text = vmatch.group(1).strip() if vmatch else ""
                written_end = m.end() + vmatch.end() if vmatch else m.end()
                # Some citation patterns capture the version inline (e.g. ISO 14644-1:1999,
                # where ":1999" is inside the match). Fall back to a captured year.
                if not version_text:
                    for g in m.groups():
                        if g and re.fullmatch(r"\d{4}", str(g)):
                            version_text = str(g)
                            break
                # include a trailing ")" if the version was written in parentheses
                if written_end < len(text) and text[written_end:written_end + 1] == ")":
                    written_end += 1
                as_written = _clean_ws(text[m.start():written_end])
                cite = self._classify(sop_id, canonical, as_written, version_text)
                # Keep the most severe status if the same canonical appears twice.
                prev = found.get(canonical)
                if prev is None or _severity(cite.status) > _severity(prev.status):
                    found[canonical] = cite
        return list(found.values())

    # -- classification ----------------------------------------------------
    def _classify(self, sop_id: str, canonical: str, as_written: str, version_text: str) -> Citation:
        entry = self.table.get(canonical)
        # ICH Q2(R1)/Q9 map onto their superseding entries.
        if entry is None and canonical == "ICH Q2(R1)":
            return self._outdated(sop_id, "ICH Q2(R2)", as_written, "Q2(R1)")
        if entry is None and canonical == "ICH Q9":
            return self._outdated(sop_id, "ICH Q9(R1)", as_written, "Q9")
        if entry is None:
            return Citation(sop_id, canonical, as_written, version_text, "unknown", "", "", "Verify citation manually")

        current = str(entry.get("current", "current"))
        topic = str(entry.get("topic", ""))
        outdated_designations = [d.lower() for d in entry.get("outdated_designations", [])]

        vt = version_text.lower().strip()
        status = "current"
        action = "None"

        if vt:
            # normalise ":1999" -> "1999"
            norm = re.sub(r"[^\w]", "", vt)
            if any(re.sub(r"[^\w]", "", d) in norm or norm in re.sub(r"[^\w]", "", d) for d in outdated_designations):
                status = "outdated"
                action = f"Update reference to {current}"
            elif "review" in vt:
                status = "review"
                action = "Review scope against current version"
        # Special-case: manifest may flag a citation as needing review even when current.
        return Citation(
            sop_id=sop_id,
            canonical=canonical,
            as_written=as_written,
            version_text=version_text,
            status=status,
            current_version=current,
            topic=topic,
            action=action,
        )

    def _outdated(self, sop_id: str, superseding_key: str, as_written: str, old: str) -> Citation:
        entry = self.table.get(superseding_key, {})
        return Citation(
            sop_id=sop_id,
            canonical=superseding_key,
            as_written=as_written,
            version_text=old,
            status="outdated",
            current_version=str(entry.get("current", superseding_key)),
            topic=str(entry.get("topic", "")),
            action=f"Update reference to {entry.get('current', superseding_key)}",
        )


def _severity(status: str) -> int:
    return {"current": 0, "unknown": 1, "review": 2, "outdated": 3}.get(status, 0)


def _clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
