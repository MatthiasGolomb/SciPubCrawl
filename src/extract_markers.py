"""
Extract domain markers from Marker-generated Markdown.
- Keep parsing minimal here; plug in project-specific rules where needed.
- Writes structured results into marker_extraction_results/.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Dict
import json
import re


@dataclass
class MarkerRecord:
    doi: str
    path: str
    # Add fields for extracted entities, e.g. salts, solvents, concentrations
    entities: Dict[str, List[str]]


def find_markdown_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.md"):
        yield p


def extract_entities_from_md(md_text: str) -> Dict[str, List[str]]:
    # Heuristic extraction for salts, solvents, and concentrations.
    text = md_text
    lowered = text.lower()

    # Common salts and solvent keywords (extend as needed)
    salts_keywords = [
        "litisf", "litfsi", "lpf6", "lifsi", "liotf", "liotf", "liontf2",
        "lipf6", "liclo4", "liasf6", "lif", "li2so4", "li2co3",
        "naotf", "natfsi", "napf6",
    ]
    solvents_keywords = [
        "dme", "diglyme", "dioxolane", "dol", "ec", "emc", "dec", "pc",
        "acetonitrile", "acn", "thf", "dmso", "dmf", "propylene carbonate",
        "ethylene carbonate", "fluoroethylene carbonate", "fec",
    ]

    # Find keyword matches preserving original case by scanning tokens
    def find_keywords(keywords: List[str]) -> List[str]:
        found: Dict[str, str] = {}
        # Tokenize by non-word boundaries but keep words with +, - if present
        for kw in keywords:
            pattern = re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
            for m in pattern.finditer(text):
                found[m.group(0).lower()] = m.group(0)
        return sorted(found.values(), key=str.lower)

    # Concentrations: capture forms like 1 M, 0.5M, 3 mol/L, 1.0 m, 10 wt%, 5 vol%, 100 mg/mL, 1 g/L
    conc_patterns = [
        r"\b\d+(?:\.\d+)?\s*(?:m|mol\/l|mol\s*L\s*[-−–]?\s*1)\b",
        r"\b\d+(?:\.\d+)?\s*(?:wt%|vol%|mol%)\b",
        r"\b\d+(?:\.\d+)?\s*(?:mg\/mL|g\/L)\b",
        r"\b\d+(?:\.\d+)?\s*M\b",
    ]
    concentrations: Dict[str, str] = {}
    for pat in conc_patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            concentrations[m.group(0).lower()] = m.group(0)

    return {
        "salts": find_keywords(salts_keywords),
        "solvents": find_keywords(solvents_keywords),
        "concentrations": sorted(concentrations.values(), key=str.lower),
    }


def extract_markers(md_root: Path, results_out: Path) -> None:
    results_out.mkdir(parents=True, exist_ok=True)
    for md in find_markdown_files(md_root):
        doi = md.parent.name  # assuming per-doi subfolders
        entities = extract_entities_from_md(md.read_text(encoding="utf-8", errors="ignore"))
        rec = MarkerRecord(doi=doi, path=str(md), entities=entities)
        # write one JSON per DOI (append or merge as needed); here we write per-file for simplicity
        out_file = results_out / f"{doi}.jsonl"
        with out_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
