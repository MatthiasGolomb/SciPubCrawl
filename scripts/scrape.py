#!/usr/bin/env python3
"""CLI for scraping PDFs using paperscraper (ChemRxiv), direct Crossref logic, and Europe PMC XML.

Usage examples:
  # ChemRxiv dump
  python scripts/scrape.py chemrxiv \
  --dump search/results.jsonl \
  --out scrape \
  --key doi \
  --api-keys refactor_skeleton/examples/lithium_metal_anode/scrape/api_keys.txt

  # Crossref dump (Wiley/Elsevier only)
  python scripts/scrape.py crossref \
  --dump search/results.jsonl \
  --out scrape \
  --key doi \
  --publishers wiley elsevier \
  --api-keys refactor_skeleton/examples/lithium_metal_anode/scrape/api_keys.txt

  # Europe PMC results → full-text XML (by PMCID)
  python scripts/scrape.py europmc \
  --dump search/europmc_results \
  --xml-out scrape/europmc_xml
"""
import argparse
import importlib.util
import sys
from pathlib import Path


def _load_module() -> object:
  this_dir = Path(__file__).resolve().parent
  src_root = this_dir.parent / "src"
  module_file = src_root / "alchemy_refactor" / "scrape.py"
  spec = importlib.util.spec_from_file_location("alchemy_refactor.scrape", str(module_file))
  assert spec and spec.loader, f"Cannot load module from {module_file}"
  mod = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = mod  # register before exec
  spec.loader.exec_module(mod)  # type: ignore[attr-defined]
  return mod


def main() -> None:
  mod = _load_module()
  save_pdfs_from_crossref_dump = getattr(mod, "save_pdfs_from_crossref_dump")
  save_eupmc_xml_from_results = getattr(mod, "save_eupmc_xml_from_results")

  p = argparse.ArgumentParser(description="Scrape PDFs via paperscraper from ChemRxiv or Crossref dumps")
  sub = p.add_subparsers(dest="cmd", required=True)

  chem = sub.add_parser("chemrxiv", help="Download PDFs from a ChemRxiv JSONL dump or a directory of result files")
  chem.add_argument("--dump", type=Path, required=True, help="Path to a .jsonl file or a directory containing .jsonl results")
  chem.add_argument("--out", type=Path, required=True)
  chem.add_argument("--key", type=str, default="doi")
  chem.add_argument("--api-keys", type=Path, default=None)
  chem.add_argument("--sleep", type=float, default=0.0, help="Optional sleep between files when passing a directory")
  chem.add_argument("--per-file-subdirs", action="store_true", help="When --dump is a directory, write into a subfolder per input file")

  cr = sub.add_parser("crossref", help="Download PDFs from a Crossref JSONL dump using direct Wiley/Elsevier/Unpaywall logic")
  cr.add_argument("--dump", type=Path, required=True)
  cr.add_argument("--out", type=Path, required=True)
  cr.add_argument("--key", type=str, default="doi")
  cr.add_argument("--publishers", type=str, nargs="*", default=None, help="Optional allow-list (case-insensitive substring) of publishers to process")
  cr.add_argument("--api-keys", type=Path, default=None, help="Path to KEY=VALUE file with WILEY_TDM_API_TOKEN, ELSEVIER_TDM_API_KEY, UNPAYWALL_EMAIL")
  cr.add_argument("--unpaywall-email", type=str, default=None, help="Override UNPAYWALL_EMAIL for Unpaywall requests")
  cr.add_argument("--xml-out", type=Path, default=None, help="Optional directory to store Elsevier XML fallbacks")
  cr.add_argument("--not-downloaded", type=Path, default=None, help="Path to write entries with no API-accessible PDF (defaults to ../not_api_available.jsonl)")
  cr.add_argument("--sleep", type=float, default=1.0, help="Polite delay between entries")

  ep = sub.add_parser("europmc", help="Download full-text XML from Europe PMC results (.jsonl file or directory)")
  ep.add_argument("--dump", type=Path, required=True, help="Path to a .jsonl file or directory with Europe PMC results")
  ep.add_argument("--xml-out", type=Path, required=True, help="Directory to store full-text XML files (named by PMCID)")
  ep.add_argument("--sleep", type=float, default=0.0, help="Optional sleep between files/entries")

  args = p.parse_args()

  if args.cmd == "chemrxiv":
    save_pdfs_from_chemrxiv = getattr(mod, "save_pdfs_from_chemrxiv")
    save_pdfs_from_chemrxiv(
      input_path=args.dump,
      pdf_root_dir=args.out,
      key_to_save=args.key,
      api_keys_file=args.api_keys,
      per_file_subdirs=args.per_file_subdirs,
      sleep_seconds=args.sleep,
    )
  elif args.cmd == "crossref":
    save_pdfs_from_crossref_dump(
      args.dump,
      args.out,
      key_to_save=args.key,
      publishers=args.publishers,
      api_keys_file=args.api_keys,
      unpaywall_email=args.unpaywall_email,
      xml_out_dir=args.xml_out,
      not_downloaded_out=args.not_downloaded,
      sleep_seconds=args.sleep,
    )
  elif args.cmd == "europmc":
    save_eupmc_xml_from_results(
      input_path=args.dump,
      xml_out_dir=args.xml_out,
      sleep_seconds=args.sleep,
    )


if __name__ == "__main__":
  main()
