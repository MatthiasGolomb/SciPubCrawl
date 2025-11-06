Refactor Skeleton for AIchemy HED Extract

Purpose
- Provide a callable, script-first structure that mirrors the notebook pipeline but runs headless for reproducibility and sharing.

Layout
- src/alchemy_refactor/
  - scrape.py: read JSONL dumps and save PDFs/XML. Keys from env vars or a KEY=VALUE file (e.g., `refactor_skeleton/examples/lithium_metal_anode/scrape/api_keys.txt`).
  - convert_to_md.py: run Marker CLI over PDFs → Markdown in marker_extraction/<doi>/.
  - extract_marker.py: run LLM extraction over Marker Markdown into validated JSON using Pydantic schemas.
  - search_crossref.py: cursor-based Crossref searches (keywords or yearly dump) → JSONL dumps; regex utilities to filter dumps into results.
  - search_chemrxiv.py: ChemRxiv monthly scraping (JSONL dumps) and grouped-keyword querying of those dumps.
  - search_europe_pmc.py: Europe PMC cursor-based searches (keywords or yearly dump) → JSONL dumps; regex utilities to filter dumps into results.
- scripts/
  - scrape.py: thin CLI wrapper over src/alchemy_refactor/scrape.py
  - convert_to_md.py: thin CLI wrapper over src/alchemy_refactor/convert_to_md.py
  - extract_marker.py: thin CLI wrapper over src/alchemy_refactor/extract_marker.py
  - search_crossref.py: Crossref keywords/yearly dump, regex filtering into results; params JSON for query/filters/regex.
  - search_chemrxiv.py: ChemRxiv scrape/query CLI with subcommands and params JSON.
  - search_europe_pmc.py: Europe PMC keywords/yearly dump, regex filtering into results; params JSON for query/regex.
- requirements.txt: minimal conservative set of deps.

Quick try (1–2 minutes)
1) Ensure you have a few PDFs in a folder (e.g., downloads/) named by DOI: 10.1002_adfm.201505074.pdf
2) Convert PDFs → Markdown using Marker:
   python refactor_skeleton/scripts/convert_to_md.py --pdf-dir downloads/ --out marker_extraction/
3) Visualize schema or run extraction (example params provided):
  # visualize-only (no API key needed)
  python refactor_skeleton/scripts/extract_marker.py --params-file refactor_skeleton/examples/lithium_metal_anode/extract/extract_params.json --visualize-schema refactor_skeleton/examples/lithium_metal_anode/extract/diagram.svg --visualize-only
  # full extraction (requires OPENAI_API_KEY)
  python refactor_skeleton/scripts/extract_marker.py --params-file refactor_skeleton/examples/lithium_metal_anode/extract/extract_params.json

Search examples
- Prepare a params JSON file with a `query` string or list, and optional `filters` (see examples/lithium_metal_anode/search/crossref_params.json).
- Crossref search (always cursor-based) using a params JSON (contains query and optional filters):
  python refactor_skeleton/scripts/search_crossref.py keywords --params-file refactor_skeleton/examples/lithium_metal_anode/search/crossref_params.json --out refactor_skeleton/examples/lithium_metal_anode/search/results.jsonl

Europe PMC search
- Prepare a params JSON file with a `query` string or list; optional keys: `page_size`, `result_type` (core|lite), `sleep`, `timeout`, `extra_and`, `start_year`, `end_year`, and `require_full_text`. Example:
  {
    "query": ["lithium metal battery", "solid polymer electrolyte"],
    "page_size": 1000,
    "result_type": "core",
    "start_year": 2010,
    "end_year": 2015,
    "require_full_text": true,
    "regex": { "scope": "combined", "groups": { "topic": ["electrolyte", "polymer"], "metal": ["lithium|Li"] } }
  }
- Keywords search using a params JSON:
  python refactor_skeleton/scripts/search_europe_pmc.py keywords --params-file refactor_skeleton/examples/lithium_metal_anode/search/europmc_params.json --out refactor_skeleton/examples/lithium_metal_anode/search/europmc_keywords.jsonl
- Yearly cursor-based dumps replicating notebook defaults:
  python refactor_skeleton/scripts/search_europe_pmc.py cursor-yearly --out-dir Datasets/europmc_dump
- Filter dumps into results using the params-defined regex (directory mode):
  python refactor_skeleton/scripts/search_europe_pmc.py filter --params-file refactor_skeleton/examples/lithium_metal_anode/search/europmc_params.json --in-dir refactor_skeleton/examples/lithium_metal_anode/search/europmc_dumps --out-dir refactor_skeleton/examples/lithium_metal_anode/search/europmc_results

ChemRxiv monthly scraping and query
- End-to-end (params JSON controls dates, directories, and the grouped query):
  python refactor_skeleton/scripts/search_chemrxiv.py run --params-file refactor_skeleton/examples/lithium_metal_anode/search/chemrxiv_params.json
- Scrape-only (writes monthly JSONL files under chemrxiv_dumps by default):
  python refactor_skeleton/scripts/search_chemrxiv.py scrape-monthly --start-date 2018-01-01 --dump-dir refactor_skeleton/examples/lithium_metal_anode/search/chemrxiv_dumps
- Query-only (reads dumps, writes results per dump; defaults mirror the notebook query groups):
  python refactor_skeleton/scripts/search_chemrxiv.py query --dump-dir refactor_skeleton/examples/lithium_metal_anode/search/chemrxiv_dumps --result-dir refactor_skeleton/examples/lithium_metal_anode/search/chemrxiv_results --params-file refactor_skeleton/examples/lithium_metal_anode/search/chemrxiv_params.json

Cursor-yearly dumps and params files
- Yearly cursor-based dumps replicating the notebook defaults:
  python refactor_skeleton/scripts/search_crossref.py cursor-yearly --out-dir Datasets/crossref_dumps_2

- You can provide a JSON params file to override defaults without long command lines. The same file used for keyword searches works here and may include query/start_year/end_year/... keys.
  python refactor_skeleton/scripts/search_crossref.py cursor-yearly --params-file refactor_skeleton/examples/lithium_metal_anode/search/crossref_params.json

Filter dumps into results (regex)
- Use params-defined regex (crossref_params.json) to filter dump JSONLs into results. The regex now supports arbitrary groups with AND semantics across groups. Example config:
  {
    "regex": {
      "scope": "combined",  # combined|field|title|abstract
      "groups": {
        "apples": ["a", "b"],
        "bananas": ["c"],
        "oranges": ["e", "f"]
      }
    }
  }
  Matching requires at least one pattern from every group to match. In "combined" scope, title and abstract are concatenated; in "field" scope, a single field must satisfy all groups; "title" or "abstract" restrict matching to that field only.
  Backward compatibility: legacy keys (anode_patterns, solvent_pattern) are still supported and mapped into two groups.
  python refactor_skeleton/scripts/search_crossref.py filter --params-file refactor_skeleton/examples/lithium_metal_anode/search/crossref_params.json --in-dir refactor_skeleton/examples/lithium_metal_anode/search/crossref_dumps --out-dir refactor_skeleton/examples/lithium_metal_anode/search/crossref_results
- For a single file:
  python refactor_skeleton/scripts/search_crossref.py filter --params-file refactor_skeleton/examples/lithium_metal_anode/search/crossref_params.json --in refactor_skeleton/examples/lithium_metal_anode/search/crossref_dumps/dumps_2019.jsonl --out refactor_skeleton/examples/lithium_metal_anode/search/crossref_results/filtered_2019.jsonl

Example folders
- refactor_skeleton/examples/lithium_metal_anode/
  - search/: params JSON and search outputs
  - scrape/: downloaded PDFs
  - convert/: Marker Markdown outputs
  - extract/: extracted marker JSONL outputs

- You can provide a JSON params file to override defaults without long command lines. Example file at examples/crossref_params.json. Precedence: CLI flags > params file > built-in defaults.
  python refactor_skeleton/scripts/search_crossref.py cursor-yearly --params-file refactor_skeleton/examples/crossref_params.json

Polite access to Crossref
- The scripts set User-Agent using crossref Etiquette with: app_name="High-throughput design of lithium metal electrolytes", app_version="0.1", app_url="None", and your mailto. Adjust via flags or params file.

Notes
- Marker must be installed and available in PATH.
- For scraping, set env vars (WILEY_TDM_API_TOKEN, ELSEVIER_TDM_API_KEY, UNPAYWALL_EMAIL) or provide a KEY=VALUE file. Example file: `refactor_skeleton/examples/lithium_metal_anode/scrape/api_keys.txt` (pass via `--api-keys`).
- Keep changes minimal; this skeleton is intended as a starting point, not a drop-in replacement.
