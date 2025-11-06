#!/usr/bin/env python3
"""CLI to search Crossref (cursor-based) and write JSONL dumps, plus regex filtering to results.

Examples:
    # Keywords search from params JSON (contains 'query' string or list, and optional filters) -> single dump JSONL
    python scripts/search_crossref.py keywords \
        --params-file search/crossref_params.json \
        --out search/crossref_dumps/keywords_dump.jsonl

    # Yearly cursor-based dump 
    python scripts/search_crossref.py cursor-yearly \
        --out-dir search/crossref_dumps

    # Filter dumps into results using params-defined regex (directory mode)
    python scripts/search_crossref.py filter \
        --params-file search/crossref_params.json \
        --in-dir search/crossref_dumps \
        --out-dir search/crossref_results

    # Filter a single dump file using params-defined regex (single-file mode)
    python scripts/search_crossref.py filter \
        --params-file search/crossref_params.json \
        --in search/crossref_dumps/dumps_2019.jsonl \
        --out search/crossref_results/filtered_2019.jsonl

"""
import argparse
import importlib.util
import sys
from pathlib import Path


def _load_module() -> object:
    this_dir = Path(__file__).resolve().parent
    src_root = this_dir.parent / "src"
    module_file = src_root / "alchemy_refactor" / "search_crossref.py"
    spec = importlib.util.spec_from_file_location("alchemy_refactor.search_crossref", str(module_file))
    assert spec and spec.loader, f"Cannot load module from {module_file}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def parse_filter_kv(items: list[str]) -> dict:
    out = {}
    for it in items:
        if ":" in it:
            k, v = it.split(":", 1)
            out[k] = v
    return out


def main() -> None:
    mod = _load_module()
    cursor_yearly_dump = getattr(mod, "cursor_yearly_dump")

    p = argparse.ArgumentParser(description="Crossref: create dumps (keywords/yearly) and filter them into results with regex")
    sub = p.add_subparsers(dest="cmd", required=True)

    kw = sub.add_parser("keywords", help="Cursor-based search (dump); reads 'query' (string or list) from params JSON if provided, else defaults to notebook behavior")
    kw.add_argument("--params-file", type=Path, required=False, help="JSON file with 'query' (str or list[str]) and optional filters")
    kw.add_argument("--out", type=Path, required=True, help="Path to dump.jsonl")
    kw.add_argument("--filter", nargs="*", default=[], help="Optional Crossref filters in k:v form")
    kw.add_argument("--rows", type=int, default=1000)
    kw.add_argument("--select", type=str, default="DOI,publisher,title,license,abstract")
    kw.add_argument("--mailto", type=str, default="m.golomb@surrey.ac.uk")
    kw.add_argument("--app-name", type=str, default="High-throughput design of lithium metal electrolytes")
    kw.add_argument("--app-version", type=str, default="0.1")
    kw.add_argument("--app-url", type=str, default="None")
    kw.add_argument("--no-dedupe", action="store_true", help="Disable on-write de-duplication by DOI")
    # params-file (if provided) holds 'query' and optional filters

    cur = sub.add_parser("cursor-yearly", help="Run per-year cursor-based fetch (dump) with defaults matching the notebook; allow params file override")
    cur.add_argument("--out-dir", type=Path, default=Path("search/crossref_dumps"))
    cur.add_argument("--query", type=str, default="Lithium metal battery")
    cur.add_argument("--start-year", type=int, default=2010)
    cur.add_argument("--end-year", type=int, default=None)
    cur.add_argument("--rows", type=int, default=1000)
    cur.add_argument("--mailto", type=str, default="m.golomb@surrey.ac.uk")
    cur.add_argument("--select", type=str, default="DOI,publisher,title,license,abstract")
    cur.add_argument("--restart-threshold", type=int, default=100000)
    cur.add_argument("--app-name", type=str, default="High-throughput design of lithium metal electrolytes")
    cur.add_argument("--app-version", type=str, default="0.1")
    cur.add_argument("--app-url", type=str, default="None")
    cur.add_argument("--params-file", type=Path, help="Optional JSON file with defaults to override (query,start_year,end_year,rows,select,mailto,app_name,app_version,app_url,restart_threshold,base_url,out_dir)")
    cur.add_argument("--no-dedupe", action="store_true", help="Disable on-write de-duplication by DOI")
    cur.add_argument("--dedupe-existing", action="store_true", help="De-duplicate existing JSONL per-year before appending")

    # post-process de-duplication utility
    dd = sub.add_parser("dedupe", help="De-duplicate a .jsonl file or all .jsonl files in a directory in-place")
    dd.add_argument("path", type=Path, help="Path to .jsonl file or directory")

    # regex filter: convert dumps → results using params-defined regex
    rf = sub.add_parser("filter", help="Filter Crossref dumps into results using regex patterns from params JSON")
    rf.add_argument("--params-file", type=Path, required=True, help="Params JSON; may include a 'regex' section to override defaults")
    rf.add_argument("--in-dir", type=Path, help="Directory containing dump .jsonl files")
    rf.add_argument("--out-dir", type=Path, help="Directory to write filtered result .jsonl files")
    rf.add_argument("--in", dest="in_file", type=Path, help="Single dump .jsonl file to filter")
    rf.add_argument("--out", dest="out_file", type=Path, help="Single filtered .jsonl output path")

    args = p.parse_args()

    if args.cmd == "keywords":
        # Defaults from CLI, overridden by params file for these keys
        k_defaults = {
            "base_url": "https://api.crossref.org/works",
            "rows": args.rows,
            "select": args.select,
            "mailto": args.mailto,
            "app_name": args.app_name,
            "app_version": args.app_version,
            "app_url": args.app_url,
        }
        if args.params_file and args.params_file.is_file():
            try:
                import json
                data = json.loads(args.params_file.read_text(encoding="utf-8"))
                for k in ("base_url", "rows", "select", "mailto", "app_name", "app_version", "app_url"):
                    if k in data and data[k] is not None:
                        k_defaults[k] = data[k]
            except Exception:
                pass
        # Coerce
        try:
            k_defaults["rows"] = int(k_defaults["rows"])  # type: ignore[index]
        except Exception:
            pass
        if args.params_file and args.params_file.is_file():
            # Delegate: params file holds query (str or list) and optional filters
            search_crossref_from_params = getattr(mod, "search_crossref_from_params")
            extra_filters = parse_filter_kv(args.filter)
            search_crossref_from_params(
                args.params_file,
                args.out,
                base_url=k_defaults["base_url"],
                select=k_defaults["select"],
                rows=k_defaults["rows"],
                mailto=k_defaults["mailto"],
                app_name=k_defaults["app_name"],
                app_version=k_defaults["app_version"],
                app_url=k_defaults["app_url"],
                extra_filter_args=extra_filters,
            )
        else:
            # No params file -> default to notebook behavior: single query "Lithium metal battery"
            search_crossref_cursor = getattr(mod, "search_crossref_cursor")
            queries = ["Lithium metal battery"]
            filter_args = parse_filter_kv(args.filter) if args.filter else None
            search_crossref_cursor(
                queries,
                args.out,
                filter_args=filter_args,
                base_url=k_defaults["base_url"],
                select=k_defaults["select"],
                rows=k_defaults["rows"],
                mailto=k_defaults["mailto"],
                app_name=k_defaults["app_name"],
                app_version=k_defaults["app_version"],
                app_url=k_defaults["app_url"],
                dedupe_on_write=(not args.no_dedupe),
            )
    elif args.cmd == "cursor-yearly":
        # Build defaults, possibly overridden by params file; CLI flags take precedence
        defaults = {
            "out_dir": args.out_dir,
            "base_url": "https://api.crossref.org/works",
            "query_bibliographic": args.query,
            "start_year": args.start_year,
            "end_year": args.end_year or __import__("datetime").datetime.now().year,
            "rows": args.rows,
            "mailto": args.mailto,
            "select": args.select,
            "restart_threshold": args.restart_threshold,
            "app_name": args.app_name,
            "app_version": args.app_version,
            "app_url": args.app_url,
        }
        if args.params_file and args.params_file.is_file():
            try:
                import json
                data = json.loads(args.params_file.read_text(encoding="utf-8"))
                # Map file keys to function parameter names; ignore unknown keys
                key_map = {
                    "out_dir": "out_dir",
                    "output_dir": "out_dir",
                    "base_url": "base_url",
                    "query": "query_bibliographic",
                    "query_bibliographic": "query_bibliographic",
                    "start_year": "start_year",
                    "end_year": "end_year",
                    "rows": "rows",
                    "mailto": "mailto",
                    "select": "select",
                    "restart_threshold": "restart_threshold",
                    "app_name": "app_name",
                    "app_version": "app_version",
                    "app_url": "app_url",
                }
                # Detect if user explicitly provided --out-dir (differs from default)
                default_out_dir = Path("search/results")
                user_provided_out_dir = Path(args.out_dir) != default_out_dir
                for k, v in data.items():
                    if k in key_map and v is not None:
                        mapped = key_map[k]
                        if mapped == "out_dir":
                            # Respect explicit CLI --out-dir; otherwise resolve relative to params file location
                            if user_provided_out_dir:
                                continue
                            # Resolve relative paths against the params file directory
                            vv = Path(v)
                            if not vv.is_absolute():
                                vv = (args.params_file.parent / vv).resolve()
                            defaults[mapped] = vv
                        else:
                            defaults[mapped] = v
            except Exception:
                pass
        # Coerce types for known fields
        if isinstance(defaults.get("out_dir"), str):
            defaults["out_dir"] = Path(defaults["out_dir"])  # type: ignore[assignment]
        for k in ("start_year", "end_year", "rows", "restart_threshold"):
            if k in defaults and defaults[k] is not None:
                try:
                    defaults[k] = int(defaults[k])
                except Exception:
                    # If end_year not parseable, fall back to current year
                    if k == "end_year":
                        defaults[k] = __import__("datetime").datetime.now().year
        if not defaults.get("end_year"):
            defaults["end_year"] = __import__("datetime").datetime.now().year
        # Finally, call with merged parameters
        cursor_yearly_dump(**defaults, dedupe_on_write=(not args.no_dedupe), dedupe_existing=args.dedupe_existing)
    elif args.cmd == "filter":
        regex_filter_crossref_from_params = getattr(mod, "regex_filter_crossref_from_params")
        regex_filter_crossref_jsonl = getattr(mod, "regex_filter_crossref_jsonl")
        if args.in_file and args.out_file:
            # Load regex config from params and filter a single file
            import json
            data = json.loads(args.params_file.read_text(encoding="utf-8"))
            regex_cfg = data.get("regex") if isinstance(data, dict) else None
            stats = regex_filter_crossref_jsonl(args.in_file, args.out_file, regex_cfg=regex_cfg)
            print(stats)
        elif args.in_dir and args.out_dir:
            stats_list = regex_filter_crossref_from_params(args.params_file, args.in_dir, args.out_dir)
            for s in stats_list:
                print(s)
        else:
            raise SystemExit("Provide either --in/--out for single-file mode or --in-dir/--out-dir for directory mode.")
    else:  # dedupe
        deduplicate_jsonl_path = getattr(mod, "deduplicate_jsonl_path")
        stats = deduplicate_jsonl_path(args.path)
        for s in stats:
            print(s)


if __name__ == "__main__":
    main()
