"""
Convert a folder of PDFs to Markdown using Marker.

Behavior
- For each PDF <name>.pdf under --pdf-dir, write outputs to <out>/<name>/
- Skip if output folder exists and is non-empty unless --overwrite
- Optionally reuse/copy existing extractions from one or more folders
- Optional ignore list (basenames without .pdf)

Note: Requires the Marker library. Install with: pip install marker-pdf
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable, Optional, Set, Dict, Any


def _load_ignore(ignore_file: Optional[Path]) -> Set[str]:
    if not ignore_file:
        return set()
    p = Path(ignore_file)
    if not p.exists():
        return set()
    vals: Set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t:
            vals.add(t)
    return vals


def _copy_existing_outputs(dst: Path, existing_roots: Iterable[Path], name: str) -> bool:
    """
    Try to copy an already-extracted paper folder from any of existing_roots/name to dst/name.
    Returns True if copied.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for root in existing_roots or []:
        src = Path(root) / name
        if src.is_dir():
            for item in src.iterdir():
                s = item
                d = dst / item.name
                if s.is_dir():
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
            return True
    return False


def convert_pdfs_to_md(
    pdf_dir: Path,
    out_root: Path,
    *,
    existing_outputs: Optional[Iterable[Path]] = None,
    ignore_file: Optional[Path] = None,
    overwrite: bool = False,
    pattern: str = "*.pdf",
    max_papers: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Convert all PDFs in pdf_dir to Markdown using Marker, writing per-paper folders under out_root.

    - Each PDF <name>.pdf → out_root/<name>/
    - Skip if out_root/<name> exists and is non-empty unless overwrite=True
    - If not present in out_root, optionally copy from any existing_outputs/<name>/

    Returns a stats dict.
    """
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import save_output
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Marker is required. Install with: pip install marker-pdf") from e

    pdf_dir = Path(pdf_dir)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    ignore = _load_ignore(ignore_file)
    conv = PdfConverter(artifact_dict=create_model_dict())

    processed = 0
    skipped_existing = 0
    copied_existing = 0
    failed = 0

    # rglob allows nested layouts (e.g., scrape/crossref_pdf/2020/...) if ever present
    for pdf_path in sorted(pdf_dir.rglob(pattern)):
        if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
            continue
        name = pdf_path.stem

        if name in ignore:
            continue

        out_dir = out_root / name
        if out_dir.is_dir() and any(out_dir.iterdir()) and not overwrite:
            skipped_existing += 1
            continue

        # Try to reuse/copy if available
        if (not overwrite) and existing_outputs and _copy_existing_outputs(out_dir, existing_outputs, name):
            copied_existing += 1
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            rendered = conv(str(pdf_path))
            # save_output will produce Markdown + assets; use base name for file naming
            save_output(rendered, str(out_dir), name)
            processed += 1
        except Exception:
            failed += 1

        if max_papers is not None and (processed + copied_existing + skipped_existing + failed) >= max_papers:
            break

    return {
        "processed": processed,
        "skipped_existing": skipped_existing,
        "copied_existing": copied_existing,
        "failed": failed,
        "out_root": str(out_root),
    }
 
