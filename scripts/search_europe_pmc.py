#!/usr/bin/env python3
"""CLI to search Europe PMC (cursor-based) and write JSONL dumps, plus regex filtering to results.

Examples:
    # Keywords search from params JSON (contains 'query' string or list) -> single dump JSONL
    python scripts/search_europe_pmc.py keywords \
        --params-file search/europmc_params.json \
        --out search/europmc_dumps/keywords_dump.jsonl

    # Yearly cursor-based dump
    python scripts/search_europe_pmc.py cursor-yearly \
        --out-dir search/europmc_dumps

    # Filter dumps into results using params-defined regex (directory mode)
    python scripts/search_europe_pmc.py filter \
        --params-file search/europmc_params.json \
        --in-dir search/europmc_dumps \
        --out-dir search/europmc_results

    # Filter a single dump file using params-defined regex (single-file mode)
    python scripts/search_europe_pmc.py filter \
        --params-file search/europmc_params.json \
        --in search/europmc_dumps/dumps_2019.jsonl \
        --out search/europmc_results/filtered_2019.jsonl

"""
import argparse
import importlib.util
import sys
from pathlib import Path


def _load_module() -> object:
    """Load Europe PMC search utilities from src/"""
    this_dir = Path(__file__).resolve().parent
    src_root = this_dir.parent / "src"
    module_file = src_root / "search_europe_pmc.py"
    spec = importlib.util.spec_from_file_location("search_europe_pmc", str(module_file))
    assert spec and spec.loader, f"Cannot load module from {module_file}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def main() -> None:
    mod = _load_module()

    p = argparse.ArgumentParser(description="Europe PMC: create dumps (keywords/yearly) and filter them into results with regex")
    sub = p.add_subparsers(dest="cmd", required=True)

    kw = sub.add_parser("keywords", help="Cursor-based search (dump); reads 'query' (string or list) from params JSON if provided")
    kw.add_argument("--params-file", type=Path, required=False, help="JSON file with 'query' (str or list[str]) and optional controls (page_size,result_type,sleep,timeout,extra_and)")
    kw.add_argument("--out", type=Path, required=True, help="Path to dump.jsonl")
    kw.add_argument("--page-size", type=int, default=1000)
    kw.add_argument("--result-type", type=str, default="core")
    kw.add_argument("--sleep", type=float, default=1.0)
    kw.add_argument("--timeout", type=int, default=60)
    kw.add_argument("--extra-and", type=str, default=None, help="Additional AND clause appended to each query")

    cur = sub.add_parser("cursor-yearly", help="Run per-year cursor-based fetch (dump); allow params file override")
    cur.add_argument("--out-dir", type=Path, default=Path("search/europmc_dumps"))
    cur.add_argument("--query", type=str, default="Lithium metal battery")
    cur.add_argument("--start-year", type=int, default=2010)
    cur.add_argument("--end-year", type=int, default=None)
    cur.add_argument("--page-size", type=int, default=1000)
    cur.add_argument("--result-type", type=str, default="core")
    cur.add_argument("--sleep", type=float, default=1.0)
    cur.add_argument("--timeout", type=int, default=60)
    cur.add_argument("--params-file", type=Path, help="Optional JSON file with defaults to override (query,start_year,end_year,page_size,result_type,sleep,timeout,base_url,out_dir)")
    cur.add_argument("--no-dedupe", action="store_true", help="Disable on-write de-duplication")
    cur.add_argument("--dedupe-existing", action="store_true", help="De-duplicate existing JSONL per-year before appending")

    # post-process de-duplication utility
    dd = sub.add_parser("dedupe", help="De-duplicate a .jsonl file or all .jsonl files in a directory in-place")
    dd.add_argument("path", type=Path, help="Path to .jsonl file or directory")

    # regex filter: convert dumps → results using params-defined regex
    rf = sub.add_parser("filter", help="Filter Europe PMC dumps into results using regex patterns from params JSON")
    rf.add_argument("--params-file", type=Path, required=True, help="Params JSON; may include a 'regex' section to override defaults")
    rf.add_argument("--in-dir", type=Path, help="Directory containing dump .jsonl files")
    rf.add_argument("--out-dir", type=Path, help="Directory to write filtered result .jsonl files")
    rf.add_argument("--in", dest="in_file", type=Path, help="Single dump .jsonl file to filter")
    rf.add_argument("--out", dest="out_file", type=Path, help="Single filtered .jsonl output path")
    rf.add_argument("--require-full-text", action="store_true", help="Keep only entries with apparent full text (pmcid/fullTextId/inEPMC/inPMC)")

    args = p.parse_args()

    if args.cmd == "keywords":
        search_eupmc_from_params = getattr(mod, "search_eupmc_from_params")
        search_eupmc_keywords = getattr(mod, "search_eupmc_keywords")
        if args.params_file and args.params_file.is_file():
            search_eupmc_from_params(
                args.params_file,
                args.out,
                page_size=args.page_size,
                result_type=args.result_type,
                sleep=args.sleep,
                timeout=args.timeout,
                extra_and=args.extra_and,
            )
        else:
            # Default to single query like notebook if no params provided
            queries = [args.query] if hasattr(args, "query") else ["Lithium metal battery"]
            search_eupmc_keywords(
                queries,
                args.out,
                page_size=args.page_size,
                result_type=args.result_type,
                sleep=args.sleep,
                timeout=args.timeout,
                dedupe_on_write=True,
                extra_and=args.extra_and,
            )
    elif args.cmd == "cursor-yearly":
        cursor_yearly_dump = getattr(mod, "cursor_yearly_dump")
        defaults = {
            "out_dir": args.out_dir,
            "base_url": getattr(mod, "EUPMC_BASE_URL", "https://www.ebi.ac.uk/europepmc/webservices/rest/search"),
            "query_bibliographic": args.query,
            "start_year": args.start_year,
            "end_year": args.end_year or __import__("datetime").datetime.now().year,
            "page_size": args.page_size,
            "result_type": args.result_type,
            "sleep": args.sleep,
            "timeout": args.timeout,
        }
        if args.params_file and args.params_file.is_file():
            try:
                import json
                data = json.loads(args.params_file.read_text(encoding="utf-8"))
                key_map = {
                    "out_dir": "out_dir",
                    "output_dir": "out_dir",
                    "base_url": "base_url",
                    "query": "query_bibliographic",
                    "query_bibliographic": "query_bibliographic",
                    "start_year": "start_year",
                    "end_year": "end_year",
                    "page_size": "page_size",
                    "result_type": "result_type",
                    "sleep": "sleep",
                    "timeout": "timeout",
                }
                default_out_dir = Path("search/europmc_dumps")
                user_provided_out_dir = Path(args.out_dir) != default_out_dir
                for k, v in data.items():
                    if k in key_map and v is not None:
                        mapped = key_map[k]
                        if mapped == "out_dir":
                            if user_provided_out_dir:
                                continue
                            vv = Path(v)
                            if not vv.is_absolute():
                                vv = (args.params_file.parent / vv).resolve()
                            defaults[mapped] = vv
                        else:
                            defaults[mapped] = v
            except Exception:
                pass
        # Coerce types
        if isinstance(defaults.get("out_dir"), str):
            defaults["out_dir"] = Path(defaults["out_dir"])  # type: ignore[assignment]
        for k in ("start_year", "end_year", "page_size", "timeout"):
            if k in defaults and defaults[k] is not None:
                try:
                    defaults[k] = int(defaults[k])
                except Exception:
                    if k == "end_year":
                        defaults[k] = __import__("datetime").datetime.now().year
        cursor_yearly_dump(**defaults, dedupe_on_write=(not args.no_dedupe), dedupe_existing=args.dedupe_existing)
    elif args.cmd == "filter":
        regex_filter_eupmc_from_params = getattr(mod, "regex_filter_eupmc_from_params")
        regex_filter_eupmc_jsonl = getattr(mod, "regex_filter_eupmc_jsonl")
        if args.in_file and args.out_file:
            import json
            data = json.loads(args.params_file.read_text(encoding="utf-8"))
            regex_cfg = data.get("regex") if isinstance(data, dict) else None
            stats = regex_filter_eupmc_jsonl(args.in_file, args.out_file, regex_cfg=regex_cfg, require_full_text=args.require_full_text)
            print(stats)
        elif args.in_dir and args.out_dir:
            stats_list = regex_filter_eupmc_from_params(args.params_file, args.in_dir, args.out_dir, require_full_text=args.require_full_text)
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
