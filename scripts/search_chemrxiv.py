#!/usr/bin/env python3
"""ChemRxiv monthly scraping and querying CLI.

Subcommands:
  - scrape-monthly: Dump ChemRxiv metadata month by month (skips existing non-empty files)
  - query: Query dumps with grouped keywords (default lithium-metal/electrolyte groups)
  - run: End-to-end using a chemrxiv_params.json 

Examples (from repo root):
  python scripts/search_chemrxiv.py run \
    --params-file search/chemrxiv_params.json

  python scripts/search_chemrxiv.py scrape-monthly \
    --start-date 2018-01-01 \
    --dump-dir search/chemrxiv_dumps

  python scripts/search_chemrxiv.py query \
    --dump-dir search/chemrxiv_dumps \
    --result-dir search/chemrxiv_results
"""
import argparse
import importlib.util
import sys
from pathlib import Path


def _load_module() -> object:
    this_dir = Path(__file__).resolve().parent
    src_root = this_dir.parent / "src"
    module_file = src_root / "alchemy_refactor" / "search_chemrxiv.py"
    spec = importlib.util.spec_from_file_location("alchemy_refactor.search_chemrxiv", str(module_file))
    assert spec and spec.loader, f"Cannot load module from {module_file}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def main() -> None:
    mod = _load_module()
    scrape_chemrxiv_monthly = getattr(mod, "scrape_chemrxiv_monthly")
    query_chemrxiv_dumps = getattr(mod, "query_chemrxiv_dumps")
    run_from_params = getattr(mod, "run_from_params")
    ChemRxivParams = getattr(mod, "ChemRxivParams")

    default_dump = Path(__file__).resolve().parents[1] / "examples" / "lithium_metal_anode" / "search" / "chemrxiv_dumps"
    default_results = Path(__file__).resolve().parents[1] / "examples" / "lithium_metal_anode" / "search" / "chemrxiv_results"
    default_params = Path(__file__).resolve().parents[1] / "examples" / "lithium_metal_anode" / "search" / "chemrxiv_params.json"

    p = argparse.ArgumentParser(description="ChemRxiv monthly scraping and querying CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    # scrape-monthly
    ps = sub.add_parser("scrape-monthly", help="Scrape ChemRxiv metadata month by month")
    ps.add_argument("--start-date", type=str, default=ChemRxivParams.start_date)
    ps.add_argument("--end-date", type=str, default=None)
    ps.add_argument("--dump-dir", type=Path, default=default_dump)
    ps.add_argument("--sleep", type=float, default=ChemRxivParams.sleep_seconds)

    # query
    pq = sub.add_parser("query", help="Query ChemRxiv dumps with grouped keywords")
    pq.add_argument("--dump-dir", type=Path, default=default_dump)
    pq.add_argument("--result-dir", type=Path, default=default_results)
    pq.add_argument("--params-file", type=Path, default=None, help="Optional chemrxiv_params.json to supply 'query'")
    pq.add_argument("--force", action="store_true", help="Overwrite existing non-empty results files")

    # run (params.json)
    pr = sub.add_parser("run", help="End-to-end: scrape monthly then query using a params.json")
    pr.add_argument("--params-file", type=Path, default=default_params, help="chemrxiv_params.json")
    pr.add_argument("--start-date", type=str, default=None)
    pr.add_argument("--end-date", type=str, default=None)
    pr.add_argument("--dump-dir", type=Path, default=None)
    pr.add_argument("--result-dir", type=Path, default=None)
    pr.add_argument("--sleep", type=float, default=None)
    pr.add_argument("--force-query", action="store_true")

    args = p.parse_args()

    if args.cmd == "scrape-monthly":
        scrape_chemrxiv_monthly(
            start_date=args.start_date,
            end_date=args.end_date,
            save_dir=args.dump_dir,
            sleep_seconds=args.sleep,
        )
        return

    if args.cmd == "query":
        query_groups = None
        if args.params_file and args.params_file.exists():
            params = ChemRxivParams.load(args.params_file)
            query_groups = params.query if params.query is not None else ChemRxivParams.default_query()
        query_chemrxiv_dumps(
            dump_dir=args.dump_dir,
            result_dir=args.result_dir,
            query_groups=query_groups,
            force=args.force,
        )
        return

    if args.cmd == "run":
        run_from_params(
            params_file=args.params_file,
            override_start_date=args.start_date,
            override_end_date=args.end_date,
            override_dump_dir=args.dump_dir,
            override_result_dir=args.result_dir,
            override_sleep=args.sleep,
            force_query=args.force_query,
        )
        return


if __name__ == "__main__":
    main()
