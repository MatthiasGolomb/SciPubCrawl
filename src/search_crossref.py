"""
Crossref search utilities to produce JSONL dumps and filter them into results.

Stages:
- dump: cursor-based fetch (keywords or yearly) writing raw Crossref items to JSONL files
- results: apply regex filters to title/abstract to produce result JSONLs

Dependencies: crossrefapi (lightweight wrapper) or direct REST requests if preferred.
"""
from __future__ import annotations
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import requests

import re
try:
    from crossref.restful import Works, Etiquette  # type: ignore
except Exception:  # pragma: no cover
    Works = None  # type: ignore
    Etiquette = None  # type: ignore


def _build_headers(
    app_name: str = "High-throughput design of lithium metal electrolytes",
    app_version: str = "0.1",
    app_url: str = "None",
    mailto: str = "m.golomb@surrey.ac.uk",
) -> Dict[str, str]:
    """Build polite Crossref headers using Etiquette when available.

    Falls back to a plain User-Agent string if Etiquette is unavailable.
    """
    # Prefer Etiquette user-agent construction if available
    if Etiquette is not None:
        try:
            et = Etiquette(app_name, app_version, app_url, mailto)  # type: ignore[call-arg]
            # Some versions expose as_header(); otherwise str(et)
            if hasattr(et, "as_header"):
                hdr = et.as_header()  # type: ignore[attr-defined]
                if isinstance(hdr, dict) and "User-Agent" in hdr:
                    return {"User-Agent": hdr["User-Agent"]}
            return {"User-Agent": str(et)}
        except Exception:
            pass
    # Fallback simple UA
    return {"User-Agent": f"{app_name}/{app_version} (mailto:{mailto})"}


def _works(etiquette: Optional[object] = None) -> Any:
    if Works is None:
        raise RuntimeError("crossrefapi is not installed: pip install crossrefapi")
    if etiquette is not None:
        return Works(etiquette=etiquette)
    return Works()


def search_crossref_cursor(
    queries: List[str],
    out_path: Path,
    filter_args: Optional[Dict[str, str]] = None,
    base_url: str = "https://api.crossref.org/works",
    select: str = "DOI,publisher,title,license,abstract",
    rows: int = 1000,
    mailto: str = "m.golomb@surrey.ac.uk",
    app_name: str = "High-throughput design of lithium metal electrolytes",
    app_version: str = "0.1",
    app_url: str = "None",
    dedupe_on_write: bool = True,
) -> None:
    """Cursor-based query search; writes all results for each query to a single JSONL.

    Always uses cursor pagination and polite headers via Etiquette.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    headers = _build_headers(app_name, app_version, app_url, mailto)
    seen_dois: set[str] = set()
    with Path(out_path).open("w", encoding="utf-8") as f:
        for q in queries:
            print(f"\n=== Cursor search for query: {q} ===")
            params: Dict[str, Any] = {
                "query.bibliographic": q,
                "select": select,
                "rows": rows,
                "cursor": "*",
                "mailto": mailto,
            }
            if filter_args:
                # The Crossref API expects comma-separated filter pairs; convert dict
                filt = ",".join(f"{k}:{v}" for k, v in filter_args.items())
                params["filter"] = filt
            total_written = 0
            while True:
                try:
                    resp = requests.get(base_url, params=params, headers=headers, timeout=60)
                    if resp.status_code == 429:
                        time.sleep(60)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    batch = data.get("message", {}).get("items", [])
                    for entry in batch:
                        # annotate source query for traceability
                        entry["source_query"] = q
                        doi = (entry.get("DOI") or entry.get("doi") or "").strip().lower()
                        if dedupe_on_write and doi:
                            if doi in seen_dois:
                                continue
                            seen_dois.add(doi)
                        f.write(json.dumps(entry) + "\n")
                        total_written += 1
                    if not batch or len(batch) < params["rows"]:
                        break
                    next_cursor = data.get("message", {}).get("next-cursor")
                    if not next_cursor:
                        break
                    params["cursor"] = next_cursor
                    time.sleep(1)
                except requests.exceptions.RequestException:
                    time.sleep(30)
                    continue

def _filter_str_from_params(data: Dict[str, Any]) -> Optional[str]:
    if isinstance(data.get("filter"), str):
        return data["filter"]
    if isinstance(data.get("filters"), dict):
        return ",".join(f"{k}:{v}" for k, v in data["filters"].items())
    return None


def search_crossref_from_params(
    params_file: Path,
    out_path: Path,
    base_url: str = "https://api.crossref.org/works",
    select: str = "DOI,publisher,title,license,abstract",
    rows: int = 1000,
    mailto: str = "m.golomb@surrey.ac.uk",
    app_name: str = "High-throughput design of lithium metal electrolytes",
    app_version: str = "0.1",
    app_url: str = "None",
    extra_filter_args: Optional[Dict[str, str]] = None,
) -> None:
    """Run cursor-based search using a query (string or list) and optional filters from a params JSON file.

    Expected keys in the JSON:
      - query: str | list[str]
      - filter (str) or filters (object mapping k->v)
    Other keys like rows/select/mailto/app_name/... can still be set via CLI; this function
    focuses on extracting query+filters and delegates the rest to search_crossref_cursor.
    """
    data = json.loads(Path(params_file).read_text(encoding="utf-8"))
    q = data.get("query")
    if isinstance(q, str):
        queries = [q]
    elif isinstance(q, list) and all(isinstance(x, str) for x in q) and q:
        queries = q
    else:
        raise ValueError("params JSON must include 'query' as a string or non-empty list of strings")
    filt = _filter_str_from_params(data)
    filter_args: Dict[str, str] = {}
    if isinstance(filt, str):
        parts = [p.strip() for p in filt.split(",") if p.strip()]
        for p in parts:
            if ":" in p:
                k, v = p.split(":", 1)
                filter_args[k] = v
    # Apply start_year/end_year from params as date filters if present
    try:
        sy = int(data.get("start_year")) if data.get("start_year") is not None else None
        ey = int(data.get("end_year")) if data.get("end_year") is not None else None
    except Exception:
        sy = None
        ey = None
    if sy:
        filter_args.setdefault("from-pub-date", f"{sy}-01-01")
    if ey:
        filter_args.setdefault("until-pub-date", f"{ey}-12-31")
    # Merge any extra filter args provided by CLI (CLI should win)
    if extra_filter_args:
        filter_args.update({k: str(v) for k, v in extra_filter_args.items()})
    search_crossref_cursor(
        queries,
        out_path,
    filter_args=filter_args or None,
        base_url=base_url,
        select=select,
        rows=rows,
        mailto=mailto,
        app_name=app_name,
        app_version=app_version,
        app_url=app_url,
    )


# --- Cursor-based yearly download with defaults ---

def cursor_yearly_dump(
    out_dir: Path = Path("Datasets/crossref_dumps_2"),
    base_url: str = "https://api.crossref.org/works",
    query_bibliographic: str = "Lithium metal battery",
    start_year: int = 2010,
    end_year: int = datetime.now().year,
    rows: int = 1000,
    mailto: str = "m.golomb@surrey.ac.uk",
    select: str = "DOI,publisher,title,license,abstract",
    restart_threshold: int = 100000,
    app_name: str = "High-throughput design of lithium metal electrolytes",
    app_version: str = "0.1",
    app_url: str = "None",
    params_file: Optional[Path] = None,
    dedupe_on_write: bool = True,
    dedupe_existing: bool = False,
) -> None:
    """Fetch Crossref dumps per-year using cursor pagination and write JSONL files.

    Resumable per-year: if a year's file exists, new dumps append to it.
    Implements 429 backoff, cursor iteration, and default polite delays.
    """
    # Optionally override defaults from a params JSON file
    if params_file:
        try:
            data = json.loads(Path(params_file).read_text(encoding="utf-8"))
            # Map JSON keys to function parameters
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
            # Apply overrides locally via a dict, then rebind locals
            overrides: Dict[str, Any] = {}
            for k, v in data.items():
                if k in key_map and v is not None:
                    overrides[key_map[k]] = v
            # Coerce types where needed
            if isinstance(overrides.get("out_dir"), str):
                out_dir = Path(overrides["out_dir"])  # type: ignore[assignment]
            base_url = overrides.get("base_url", base_url)
            query_bibliographic = overrides.get("query_bibliographic", query_bibliographic)
            if "start_year" in overrides:
                start_year = int(overrides["start_year"])  # type: ignore[assignment]
            if "end_year" in overrides:
                end_year = int(overrides["end_year"])  # type: ignore[assignment]
            if "rows" in overrides:
                rows = int(overrides["rows"])  # type: ignore[assignment]
            mailto = overrides.get("mailto", mailto)
            select = overrides.get("select", select)
            if "restart_threshold" in overrides:
                restart_threshold = int(overrides["restart_threshold"])  # type: ignore[assignment]
            app_name = overrides.get("app_name", app_name)
            app_version = overrides.get("app_version", app_version)
            app_url = overrides.get("app_url", app_url)
        except Exception:
            pass
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing yearly dumps under: {out_dir}")
    headers = _build_headers(app_name, app_version, app_url, mailto)

    for year in range(start_year, end_year + 1):
        print(f"\n=== Fetching dump for {year} ===")
        params = {
            "query.bibliographic": query_bibliographic,
            "filter": f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31",
            "select": select,
            "rows": rows,
            "cursor": "*",
            "mailto": mailto,
        }

        output_file = out_dir / f"dumps_{year}.jsonl"
        seen_dois: set[str] = set()
        existing_count = 0
        if output_file.exists():
            print(f"Loading existing DOIs from {output_file}...")
            if dedupe_existing:
                try:
                    _deduplicate_jsonl_file(output_file, in_place=True)
                    print("Existing file de-duplicated in place.")
                except Exception as e:
                    print(f"Failed to de-duplicate existing file: {e}")
            with output_file.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    doi = (entry.get("DOI") or entry.get("doi") or "").strip().lower()
                    if doi:
                        seen_dois.add(doi)
                        existing_count += 1
            print(f"Loaded {existing_count} existing entries, {len(seen_dois)} unique DOIs.")
        else:
            print("No existing dump file found. Starting fresh.")

        processed_entries = 0
        print("Starting CrossRef API download loop for dump...")
        while True:
            try:
#                print(f"\nRequesting batch with cursor: {params['cursor']}")
                resp = requests.get(base_url, params=params, headers=headers, timeout=60)
                if resp.status_code == 429:
                    print("Rate limit exceeded. Waiting 60 seconds before retrying...")
                    time.sleep(60)
                    continue
                resp.raise_for_status()
                data = resp.json()

                if processed_entries == 0:
                    total_results = data.get("message", {}).get("total-results")
                    print(f"Total results available for {year}: {total_results}")

                batch = data.get("message", {}).get("items", [])
                print(f"Received {len(batch)} results in this batch.")

                wrote = 0
                with output_file.open("a", encoding="utf-8") as f:
                    for entry in batch:
                        if dedupe_on_write:
                            doi = (entry.get("DOI") or entry.get("doi") or "").strip().lower()
                            if doi and doi in seen_dois:
                                continue
                            if doi:
                                seen_dois.add(doi)
                        f.write(json.dumps(entry) + "\n")
                        wrote += 1
                processed_entries += len(batch)
                print(f"Appended {wrote} unique entries; unique DOIs so far this year: {len(seen_dois)}")

                if not batch or len(batch) < params["rows"]:
                    print("No more results or batch smaller than requested. Stopping.")
                    break

                next_cursor = data.get("message", {}).get("next-cursor")
                if not next_cursor:
                    print("No next cursor found. Stopping.")
                    break
                params["cursor"] = next_cursor
#                print(f"Next cursor: {next_cursor}")

                if processed_entries >= restart_threshold:
                    print(f"Restarting query after processing {processed_entries} entries.")
                    processed_entries = 0
                    time.sleep(20)



                time.sleep(1)

            except requests.exceptions.RequestException as e:
                print(f"Request failed: {e}")
                print(f"Last cursor: {params['cursor']}")
                print("Waiting 30 seconds before retrying...")
                time.sleep(30)

    print(f"Finished year {year}. Unique DOIs currently stored: {len(seen_dois)}")


# --- Utilities: post-process JSONL de-duplication ---

def _deduplicate_jsonl_file(in_path: Path, out_path: Optional[Path] = None, in_place: bool = False) -> dict:
    """De-duplicate a JSONL file by DOI (case-insensitive). Returns stats.

    If out_path is None and in_place is False, writes alongside as <name>.dedup.jsonl
    If in_place is True, writes to a temp path and replaces the original.
    """
    in_path = Path(in_path)
    if out_path is None and not in_place:
        out_path = in_path.with_suffix("")
        out_path = out_path.with_name(out_path.name + ".dedup.jsonl")

    temp_out = in_path.parent / (in_path.name + ".tmp") if in_place else out_path
    assert temp_out is not None
    seen: set[str] = set()
    total = 0
    kept = 0
    missing_doi = 0
    with in_path.open("r", encoding="utf-8") as fin, Path(temp_out).open("w", encoding="utf-8") as fout:
        for line in fin:
            total += 1
            try:
                obj = json.loads(line)
            except Exception:
                continue
            doi = (obj.get("DOI") or obj.get("doi") or "").strip().lower()
            if not doi:
                # keep but cannot dedup safely
                missing_doi += 1
                fout.write(json.dumps(obj) + "\n")
                kept += 1
                continue
            if doi in seen:
                continue
            seen.add(doi)
            fout.write(json.dumps(obj) + "\n")
            kept += 1
    if in_place:
        # replace original atomically where possible
        Path(temp_out).replace(in_path)
    return {"total": total, "kept": kept, "duplicates": total - kept, "missing_doi": missing_doi}


def deduplicate_jsonl_path(path: Path) -> List[dict]:
    """De-duplicate a JSONL file or all JSONL files in a directory in-place.

    Returns a list of stats dicts for each processed file.
    """
    p = Path(path)
    results: List[dict] = []
    if p.is_file() and p.suffix == ".jsonl":
        stats = _deduplicate_jsonl_file(p, in_place=True)
        results.append({"path": str(p), **stats})
        return results
    if p.is_dir():
        for child in sorted(p.iterdir()):
            if child.is_file() and child.suffix == ".jsonl":
                stats = _deduplicate_jsonl_file(child, in_place=True)
                results.append({"path": str(child), **stats})
        return results
    raise ValueError(f"Path must be a .jsonl file or directory: {path}")


# --- Regex filtering (results from dumps) ---

def _compile_patterns(patterns: List[str]) -> List[re.Pattern[str]]:
    return [re.compile(p, re.I) for p in patterns]


def _normalize_regex_cfg(cfg: Optional[dict]) -> tuple[dict[str, List[re.Pattern[str]]], str]:
    """Normalize regex config to a dict of groups -> [compiled patterns] and a scope.

        Supported config:
            {"groups": {"apples": ["a", "b"], "bananas": ["c"]}, "scope": "combined|field|title|abstract"}
        Scope default: "field" )
    """
    if not isinstance(cfg, dict):
        cfg = _default_regex_config()
    scope = cfg.get("scope") or "field"

    groups_cfg_raw = cfg.get("groups")
    if isinstance(groups_cfg_raw, dict):
        groups_cfg: dict = groups_cfg_raw
    else:
        groups_cfg = _default_regex_config()["groups"]

    groups_compiled: dict[str, List[re.Pattern[str]]] = {}
    for g, pats in groups_cfg.items():
        if isinstance(pats, str):
            pats = [pats]
        if not isinstance(pats, list):  # skip invalid
            continue
        groups_compiled[str(g)] = _compile_patterns([p for p in pats if isinstance(p, str)])
    return groups_compiled, str(scope)


def _text_matches_groups(text: Any, groups: dict[str, List[re.Pattern[str]]]) -> bool:
    """True if text contains at least one match for every group (AND across groups)."""
    if not groups:
        return False
    if not text:
        return False
    if isinstance(text, list):
        text = " ".join(t for t in text if isinstance(t, str))
    if not isinstance(text, str):
        return False
    # For each group (list of patterns), require ANY pattern in that group to match
    for pats in groups.values():
        if not any(rx.search(text) for rx in pats):
            return False
    return True


def _matches_entry_groups(entry: dict, groups: dict[str, List[re.Pattern[str]]], scope: str = "field") -> bool:
    title = _text_to_str(entry.get("title"))
    abstract = _text_to_str(entry.get("abstract"))
    if scope == "title":
        return _text_matches_groups(title, groups)
    if scope == "abstract":
        return _text_matches_groups(abstract, groups)
    if scope == "field":  # any single field must satisfy all groups (default)
        return _text_matches_groups(title, groups) or _text_matches_groups(abstract, groups)
    # combined: concatenate title+abstract, allow matches across fields
    combined = " ".join(x for x in (title, abstract) if x)
    return _text_matches_groups(combined, groups)

# --- Regex filtering using params-file config ---

def _default_regex_config() -> dict:
    """Default regex configuration for generalized groups-based matching.

    Neutral by default (no groups); users should provide groups via params.
    """
    return {"groups": {}, "scope": "field"}


# Regex filtering is implemented directly via _normalize_regex_cfg and _matches_entry_groups.


def _text_to_str(val: Any) -> str:
    if isinstance(val, list):
        return " ".join(x for x in val if isinstance(x, str))
    return val if isinstance(val, str) else ""


def regex_filter_crossref_jsonl(in_path: Path, out_path: Path, regex_cfg: Optional[dict] = None) -> dict:
    """Filter a single Crossref dump JSONL into a results JSONL using regex config.

    Overwrites out_path. Returns stats dict.
    """
    in_path = Path(in_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    groups, scope = _normalize_regex_cfg(regex_cfg)
    total = 0
    kept = 0
    seen: set[str] = set()
    with in_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            total += 1
            if _matches_entry_groups(obj, groups, scope=scope):
                doi = (obj.get("DOI") or obj.get("doi") or "").strip().lower()
                if doi and doi in seen:
                    continue
                if doi:
                    seen.add(doi)
                fout.write(json.dumps(obj) + "\n")
                kept += 1
    return {"path": str(in_path), "out": str(out_path), "total": total, "kept": kept}


def regex_filter_crossref_from_params(params_file: Path, in_dir: Path, out_dir: Path) -> list[dict]:
    """Filter all JSONL dumps in a directory using regex config from params JSON.

    Returns a list of stats dicts.
    """
    params_file = Path(params_file)
    in_dir = Path(in_dir)
    out_dir = Path(out_dir)
    data = json.loads(params_file.read_text(encoding="utf-8"))
    regex_cfg = data.get("regex") if isinstance(data, dict) else None
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for child in sorted(in_dir.iterdir()):
        if child.is_file() and child.suffix == ".jsonl":
            # Derive year-based output name: results_{year}.jsonl
            m = re.search(r"(\d{4})", child.name)
            year = m.group(1) if m else "unknown"
            out_path = out_dir / f"results_{year}.jsonl"
            stats = regex_filter_crossref_jsonl(child, out_path, regex_cfg=regex_cfg)
            results.append(stats)
    return results
