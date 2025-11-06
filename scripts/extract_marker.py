#!/usr/bin/env python3
"""CLI for running config-driven marker extraction over Markdown files.

Usage:
  python scripts/extract_marker.py --params-file path/to/extract_params.json

Optional overrides:
    --markdown-dir, --results-dir, --provider, --model, --prompt-mode

Visualization:
    --visualize-schema <out.{png|svg|pdf|dot}>  # generate schema graph before extraction
    --visualize-only                            # generate schema graph and exit (no extraction)
"""
import argparse
import importlib.util
import sys
from pathlib import Path


def _load_module() -> object:
    this_dir = Path(__file__).resolve().parent
    src_root = this_dir.parent / "src"
    module_file = src_root / "alchemy_refactor" / "extract_marker.py"
    spec = importlib.util.spec_from_file_location("alchemy_refactor.extract_marker", str(module_file))
    assert spec and spec.loader, f"Cannot load module from {module_file}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # register before exec
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def main() -> None:
    mod = _load_module()
    extract_markers = getattr(mod, "extract_markers")

    p = argparse.ArgumentParser(description="Run LLM extraction over Marker Markdown with a config file")
    p.add_argument("--params-file", type=Path, required=True)
    p.add_argument("--markdown-dir", type=Path, default=None)
    p.add_argument("--results-dir", type=Path, default=None)
    p.add_argument("--provider", type=str, default=None)
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--prompt-mode", type=str, default=None)
    p.add_argument("--api-keys-file", type=Path, default=None)
    p.add_argument(
        "--visualize-schema",
        type=Path,
        default=None,
        help="Output path for schema visualization (e.g., schema.png | schema.svg | schema.dot). If set, the schema graph is generated before extraction.",
    )
    p.add_argument(
        "--visualize-only",
        action="store_true",
        help="Only generate the schema visualization and exit without running extraction.",
    )
    args = p.parse_args()

    overrides = {}
    if args.markdown_dir is not None:
        overrides["markdown_dir"] = str(args.markdown_dir)
    if args.results_dir is not None:
        overrides["results_dir"] = str(args.results_dir)
    if args.provider is not None:
        overrides["provider"] = args.provider
    if args.model is not None:
        overrides["model"] = args.model
    if args.prompt_mode is not None:
        overrides["prompt_mode"] = args.prompt_mode
    if args.api_keys_file is not None:
        overrides["api_keys_file"] = str(args.api_keys_file)

    # Optional: Render schema graph first if requested
    if args.visualize_schema is not None:
        visualize_schema_from_params = getattr(mod, "visualize_schema_from_params", None)
        if callable(visualize_schema_from_params):
            try:
                out_path = visualize_schema_from_params(args.params_file, args.visualize_schema)
                print(f"[extract] Schema visualization written to: {out_path}")
            except Exception as e:
                print(f"[extract] Schema visualization failed: {e}")
    if args.visualize_only:
        return

    stats = extract_markers(args.params_file, overrides=overrides)
    print(f"[extract] Done. Stats: {stats}")


if __name__ == "__main__":
    main()
