#!/usr/bin/env python3
"""CLI for converting PDFs to Markdown using Marker.

Mirrors the Production_Extraction notebook behavior:
- Per-PDF subfolder under the output root (default: marker_extraction)
- Skip if output exists (unless --overwrite)
- Optionally reuse existing extractions from prior folders
"""
import argparse
import importlib.util
import sys
from pathlib import Path


def _load_module() -> object:
    this_dir = Path(__file__).resolve().parent
    src_root = this_dir.parent / "src"
    module_file = src_root / "alchemy_refactor" / "convert_to_md.py"
    spec = importlib.util.spec_from_file_location("alchemy_refactor.convert_to_md", str(module_file))
    assert spec and spec.loader, f"Cannot load module from {module_file}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # register before exec
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def main() -> None:
    mod = _load_module()
    convert_pdfs_to_md = getattr(mod, "convert_pdfs_to_md")

    p = argparse.ArgumentParser(description="Convert a folder of PDFs to Markdown using Marker (per-paper folders).")
    p.add_argument("--pdf-dir", type=Path, required=True, help="Folder containing PDFs (e.g., scrape/crossref_pdf)")
    p.add_argument("--out", type=Path, default=Path("marker_extraction"), help="Output root for per-paper Markdown (default: marker_extraction)")
    p.add_argument(
        "--existing-outputs",
        type=Path,
        nargs="*",
        default=[],
        help="Optional folders to reuse existing extractions from (copy into --out if found)",
    )
    p.add_argument("--ignore-file", type=Path, default=None, help="Optional file with basenames (without .pdf) to skip, one per line")
    p.add_argument("--overwrite", action="store_true", help="Re-run conversion even if output folder exists and is non-empty")
    p.add_argument("--pattern", type=str, default="*.pdf", help="Glob to select PDFs (default: *.pdf)")
    p.add_argument("--max", type=int, default=None, help="Process at most N PDFs (for quick tests)")

    args = p.parse_args()

    stats = convert_pdfs_to_md(
        pdf_dir=args.pdf_dir,
        out_root=args.out,
        existing_outputs=args.existing_outputs,
        ignore_file=args.ignore_file,
        overwrite=args.overwrite,
        pattern=args.pattern,
        max_papers=args.max,
    )
    print(f"[marker] Done. Stats: {stats}")


if __name__ == "__main__":
    main()
