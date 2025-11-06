#!/usr/bin/env python3
"""CLI wrapper to extract markers from Marker-generated Markdown.
Example:
  python scripts/extract_markers.py \
    --md-root examples/lithium_metal_anode/convert/crossref_md \
    --out examples/lithium_metal_anode/extract/crossref_md_output
"""
import argparse
import importlib.util
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SRC_ROOT = THIS_DIR.parent / "src"
MODULE_FILE = SRC_ROOT / "extract_markers.py"

spec = importlib.util.spec_from_file_location("extract_markers", str(MODULE_FILE))
assert spec and spec.loader, f"Cannot load module from {MODULE_FILE}"
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod  # register before exec for dataclasses
spec.loader.exec_module(mod)  # type: ignore[attr-defined]
extract_markers_fn = getattr(mod, "extract_markers")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--md-root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    extract_markers_fn(args.md_root, args.out)


if __name__ == "__main__":
    main()
