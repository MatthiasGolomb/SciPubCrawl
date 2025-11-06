SciPubCrawl — Search → Scrape → Convert → Extract

Purpose
- A reproducible, script-first pipeline to search literature, download full texts, convert PDFs to Markdown, and extract structured data with either heuristics or an LLM-backed schema.

Pipeline overview

  [Search] → JSONL dumps
          → (regex filter) → JSONL results
          → [Scrape PDFs/XML] → files/
          → [Convert PDFs → MD (Marker)] → convert/<doi>/
          → [Extract] → structured outputs (JSON/TXT)

Repository layout (key parts)
- `src/`
  - `search_crossref.py`, `search_europe_pmc.py`, `search_chemrxiv.py`: search utilities and regex filtering helpers
  - `scrape.py`: PDF/XML downloaders (Wiley/Elsevier/Unpaywall; Europe PMC full-text XML)
  - `convert_to_md.py`: Marker-based PDF → Markdown conversion
  - `extract_marker.py`: Config-driven LLM extraction with schema validation and prompt config
  - `extract_markers.py`: Fast heuristic marker extraction from Markdown
- `scripts/` (thin CLIs over the above modules)
  - `search_crossref.py`, `search_europe_pmc.py`, `search_chemrxiv.py`
  - `scrape.py`, `convert_to_md.py`, `extract_marker.py`, `extract_markers.py`
- `examples/lithium_metal_anode/`
  - `search/`: example params and search outputs
  - `scrape/`: downloaded files (PDF/XML)
  - `convert/`: Marker Markdown outputs
  - `extract/`: extraction configs and outputs


Requirements
- Core: see `requirements.txt` (requests, bs4, lxml, pandas, numpy, click, crossrefapi, pytest)
- Optional by stage:
  - Convert: `marker-pdf` (Marker) if using the Python API; you may also use the Marker CLI
  - Extract (LLM): `pydantic>=2`, `litellm`, `instructor`, plus your model provider key (e.g., `OPENAI_API_KEY`)
  - Schema viz (optional): `erdantic`, `graphviz`
  - ChemRxiv scraping/query: `paperscraper`

API keys and politeness
- Set via environment variables or a simple KEY=VALUE file and pass with `--api-keys`:
  - `WILEY_TDM_API_TOKEN`, `ELSEVIER_TDM_API_KEY`, `UNPAYWALL_EMAIL` (scraping)
  - `OPENAI_API_KEY` (LLM extraction via litellm)
- Crossref requests include a polite User-Agent (Etiquette). Provide `--mailto` and app info where relevant.

Quickstart (full pipeline with examples)
1) Search (Crossref, yearly dump → filter)
   - Dump per-year:
     python scripts/search_crossref.py cursor-yearly \
       --out-dir examples/lithium_metal_anode/search/crossref_dumps \
       --query "Lithium metal battery" --start-year 2018 --end-year 2019
   - Filter into results using regex from params:
     python scripts/search_crossref.py filter \
       --params-file examples/lithium_metal_anode/search/crossref_params.json \
       --in-dir examples/lithium_metal_anode/search/crossref_dumps \
       --out-dir examples/lithium_metal_anode/search/crossref_results

2) Scrape PDFs from Crossref results (Wiley/Elsevier with fallbacks)
   - Put API keys in `examples/lithium_metal_anode/scrape/api_keys.txt` (KEY=VALUE lines)
   - Download:
     python scripts/scrape.py crossref \
       --dump examples/lithium_metal_anode/search/crossref_results \
       --out examples/lithium_metal_anode/scrape/crossref_pdf \
       --publishers wiley elsevier \
       --api-keys examples/lithium_metal_anode/scrape/api_keys.txt

3) Convert PDFs → Markdown (Marker)
   python scripts/convert_to_md.py \
     --pdf-dir examples/lithium_metal_anode/scrape/crossref_pdf \
     --out examples/lithium_metal_anode/convert/crossref_md

4) Visualize schema (optional) and run LLM extraction
   - Visualize (no API call):
     python scripts/extract_marker.py \
       --params-file examples/lithium_metal_anode/extract/extract_params.json \
       --visualize-schema examples/lithium_metal_anode/extract/diagram.svg \
       --visualize-only
   - Extract (requires provider API key, e.g., `OPENAI_API_KEY`):
     python scripts/extract_marker.py \
       --params-file examples/lithium_metal_anode/extract/extract_params.json

5) (Alternative) Heuristic marker extraction (fast)
   python scripts/extract_markers.py \
     --md-root examples/lithium_metal_anode/convert/crossref_md \
     --out examples/lithium_metal_anode/extract/crossref_md_output


Search

Crossref
- Keyword(s) via params file (contains `query` and optional `filters`):
  python scripts/search_crossref.py keywords \
    --params-file examples/lithium_metal_anode/search/crossref_params.json \
    --out examples/lithium_metal_anode/search/crossref_dumps/keywords.jsonl
- Yearly dumps:
  python scripts/search_crossref.py cursor-yearly \
    --out-dir examples/lithium_metal_anode/search/crossref_dumps
- Filter dumps to results using regex groups (AND across groups, OR within each group):
  python scripts/search_crossref.py filter \
    --params-file examples/lithium_metal_anode/search/crossref_params.json \
    --in-dir examples/lithium_metal_anode/search/crossref_dumps \
    --out-dir examples/lithium_metal_anode/search/crossref_results
- Single-file filter:
  python scripts/search_crossref.py filter \
    --params-file examples/lithium_metal_anode/search/crossref_params.json \
    --in examples/lithium_metal_anode/search/crossref_dumps/dumps_2019.jsonl \
    --out examples/lithium_metal_anode/search/crossref_results/filtered_2019.jsonl

Europe PMC
- Keywords (append `extra_and` or constrain by years via params):
  python scripts/search_europe_pmc.py keywords \
    --params-file examples/lithium_metal_anode/search/europmc_params.json \
    --out examples/lithium_metal_anode/search/europmc_dumps/keywords.jsonl
- Yearly dumps:
  python scripts/search_europe_pmc.py cursor-yearly \
    --out-dir examples/lithium_metal_anode/search/europmc_dumps
- Filter with regex; optionally keep only entries with apparent full text:
  python scripts/search_europe_pmc.py filter \
    --params-file examples/lithium_metal_anode/search/europmc_params.json \
    --in-dir examples/lithium_metal_anode/search/europmc_dumps \
    --out-dir examples/lithium_metal_anode/search/europmc_results \
    --require-full-text

ChemRxiv
- End-to-end (monthly scrape + grouped query):
  python scripts/search_chemrxiv.py run \
    --params-file examples/lithium_metal_anode/search/chemrxiv_params.json
- Scrape only (writes `chemrxiv_YYYY-MM-DD_YYYY-MM-DD.jsonl` files):
  python scripts/search_chemrxiv.py scrape-monthly \
    --start-date 2018-01-01 \
    --dump-dir examples/lithium_metal_anode/search/chemrxiv_dumps
- Query only (reads dumps, writes `results_<dump>.jsonl`):
  python scripts/search_chemrxiv.py query \
    --dump-dir examples/lithium_metal_anode/search/chemrxiv_dumps \
    --result-dir examples/lithium_metal_anode/search/chemrxiv_results \
    --params-file examples/lithium_metal_anode/search/chemrxiv_params.json


Scrape

ChemRxiv PDFs (via paperscraper)
  python scripts/scrape.py chemrxiv \
    --dump examples/lithium_metal_anode/search/chemrxiv_results \
    --out examples/lithium_metal_anode/scrape/chemrxiv_pdf \
    --key doi \
    --api-keys examples/lithium_metal_anode/scrape/api_keys.txt \
    --per-file-subdirs

Crossref PDFs (Wiley/Elsevier with fallbacks; others via Unpaywall)
  python scripts/scrape.py crossref \
    --dump examples/lithium_metal_anode/search/crossref_results \
    --out examples/lithium_metal_anode/scrape/crossref_pdf \
    --publishers wiley elsevier \
    --api-keys examples/lithium_metal_anode/scrape/api_keys.txt

Europe PMC full-text XML by PMCID
  python scripts/scrape.py europmc \
    --dump examples/lithium_metal_anode/search/europmc_results \
    --xml-out examples/lithium_metal_anode/scrape/europmc_xml

Notes
- Saved files are named by sanitized DOI/PMCID. A `not_api_available.jsonl` file is written if API-based PDFs can’t be retrieved; you may fetch those manually.
- Use `--sleep` to be polite for large batches.


Convert (Marker)
- Install `marker-pdf` (or use the CLI if preferred). The CLI here uses Marker’s Python API.
  python scripts/convert_to_md.py \
    --pdf-dir examples/lithium_metal_anode/scrape/crossref_pdf \
    --out examples/lithium_metal_anode/convert/crossref_md \
    --overwrite

Behavior
- Each `<name>.pdf` becomes `out/<name>/...` (Markdown + assets). Existing non-empty outputs are skipped unless `--overwrite`.
- You can reuse prior extractions via `--existing-outputs <folder1> <folder2>`.


Extract (LLM-driven)
- Config file: `examples/lithium_metal_anode/extract/extract_params.json` controls schema, prompts, provider/model, and run settings.
- Run:
  python scripts/extract_marker.py --params-file examples/lithium_metal_anode/extract/extract_params.json

Key config fields
- `schema` (type=python): `module_path`, `root_model`, optional `root_container` (e.g., "List")
- `llm`: `provider`, `model`, `temperature`, `max_retries`, `timeout_s` (provided via `litellm`)
- `prompt`: `file` (YAML/JSON), `mode` (fewshot|oneshot|simpleprompt), `system_key`, `user_key`
- `run`: `glob`, `max_files`, `sleep_s`, `on_parse_error` (save_raw|skip|retry), `output_format` (txt|json)

Overrides
- CLI flags can override `markdown_dir`, `results_dir`, `provider`, `model`, `prompt-mode`, and `api-keys-file`.
- Schema visualization:
  python scripts/extract_marker.py \
    --params-file examples/lithium_metal_anode/extract/extract_params.json \
    --visualize-schema examples/lithium_metal_anode/extract/diagram.svg

Outputs
- Saved under `results_dir/instruct_<mode>_<provider>_<model>/` as `.txt` (default) or `.json`.
- On errors with `on_parse_error=save_raw`, a `.error.txt` is written with details.


Extract (Heuristic, fast)
- Quick signals (salts, solvents, concentrations) from Markdown with minimal parsing:
  python scripts/extract_markers.py \
    --md-root examples/lithium_metal_anode/convert/crossref_md \
    --out examples/lithium_metal_anode/extract/crossref_md_output
- Writes one JSONL per DOI, appending records per Markdown file.


Configuration files (examples)

Crossref params (`examples/lithium_metal_anode/search/crossref_params.json`)
- Keys: `query` (str|list), `filters` (object) or `filter` (string), `start_year`, `end_year`, `rows`, `select`, `mailto`, app info, `base_url`, and `regex` block.
- Regex semantics: AND across groups, OR within each group. `scope`: `field` (default; title or abstract individually), `combined` (title+abstract concatenated), `title`, `abstract`.

Europe PMC params (`examples/lithium_metal_anode/search/europmc_params.json`)
- Keys: `query` (str|list), `page_size`, `result_type` (core|lite), `sleep`, `timeout`, optional `extra_and`, `start_year`, `end_year`, `require_full_text`, and `regex`.

ChemRxiv params (`examples/lithium_metal_anode/search/chemrxiv_params.json`)
- Keys: `start_date`, `end_date`, `dump_dir`, `result_dir`, `sleep_seconds`, `query` as grouped keywords (OR within group, AND across groups).

LLM extract params (`examples/lithium_metal_anode/extract/extract_params.json`)
- Pydantic schema module path and root model, prompt file+mode, provider/model, and run controls.

Precedence
- CLI flags > params file > built-in defaults.


Testing
- Run unit tests:
  pytest -q
- Current tests cover ChemRxiv params loading and heuristic marker extraction basics.


Troubleshooting
- HTTP 429 / rate limiting: the tools back off and retry. Increase `--sleep` for large jobs.
- Empty results: verify `query` and `regex` group logic; try `scope=combined` for cross-field matches.
- Missing PDFs: check `not_api_available.jsonl` and consider manual retrieval.
- Marker failures: rerun with `--overwrite`; some PDFs have complex layouts.
- LLM extraction errors: set `on_parse_error=save_raw` (default) to capture failures; check your provider API key and model availability.


Notes
- This repository’s CLIs assume the `scripts/` shims are in sync with `src/`. If your local clone still has older import paths in scripts, either update those paths or invoke the `src/*` functions from a small one-off Python snippet.
