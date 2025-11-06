"""
Europe PMC search utilities to produce JSONL dumps and filter them into results.

Stages:
- dump: cursor-based fetch (keywords or yearly) writing raw Europe PMC items to JSONL files
- results: apply regex filters to title/abstract to produce result JSONLs

API: https://www.ebi.ac.uk/europepmc/webservices/rest/
Endpoint: /search?query=...&format=json&resultType=core|lite&pageSize=N&cursorMark=*

Notes
- We de-duplicate on DOI when available; otherwise we fallback to the Europe PMC "id" field.
- The yearly dump constructs queries of the form: (base_query) AND PUB_YEAR:YYYY
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional

import requests


EUPMC_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def eupmc_iter_results(
    query: str,
    base_url: str = EUPMC_BASE_URL,
    page_size: int = 1000,
    result_type: str = "core",
    sleep: float = 1.0,
    timeout: int = 60,
) -> Generator[dict, None, None]:
    """Iterate over all results for a Europe PMC query using cursorMark pagination.

    Yields raw result dictionaries as returned in resultList.result.
    """
    params: Dict[str, Any] = {
        "query": query,
        "format": "json",
        "resultType": result_type,
        "pageSize": int(page_size),
        "cursorMark": "*",
    }

    while True:
        try:
            resp = requests.get(base_url, params=params, timeout=timeout)
            if resp.status_code == 429:
                time.sleep(60)
                continue
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException:
            # brief backoff and retry
            time.sleep(30)
            continue

        results = (data.get("resultList") or {}).get("result") or []
        for item in results:
            yield item

        # Stop when batch smaller than requested or no nextCursorMark
        next_cursor = data.get("nextCursorMark")
        if not results or len(results) < params["pageSize"] or not next_cursor:
            break
        params["cursorMark"] = next_cursor
        time.sleep(max(0.0, float(sleep)))


def _dedup_key_eupmc(entry: dict) -> str:
    doi = (entry.get("doi") or entry.get("DOI") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    # Fallback to id (e.g., 'MED:1234567') when DOI missing
    eid = (entry.get("id") or "").strip()
    if eid:
        return f"id:{eid}"
    # last resort, title hash to avoid obvious repeats
    title = _text_to_str(entry.get("title"))
    return f"title:{hash(title)}"


def search_eupmc_keywords(
    queries: List[str],
    out_path: Path,
    base_url: str = EUPMC_BASE_URL,
    page_size: int = 1000,
    result_type: str = "core",
    sleep: float = 1.0,
    timeout: int = 60,
    dedupe_on_write: bool = True,
    extra_and: Optional[str] = None,
) -> None:
    """Run cursor-based search for each query; write all results to a single JSONL file.

    If extra_and is provided, it's AND'ed to each query (wrapped in parentheses).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    total_written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for q in queries:
            q_eff = f"({q}) AND ({extra_and})" if extra_and else q
            print(f"\n=== Europe PMC cursor search for query: {q_eff} ===")
            for item in eupmc_iter_results(
                q_eff,
                base_url=base_url,
                page_size=page_size,
                result_type=result_type,
                sleep=sleep,
                timeout=timeout,
            ):
                # annotate source query for traceability
                item["source_query"] = q
                key = _dedup_key_eupmc(item)
                if dedupe_on_write and key in seen:
                    continue
                seen.add(key)
                f.write(json.dumps(item) + "\n")
                total_written += 1
    print(f"Wrote {total_written} total entries to {out_path}")


def search_eupmc_from_params(
    params_file: Path,
    out_path: Path,
    base_url: str = EUPMC_BASE_URL,
    page_size: int = 1000,
    result_type: str = "core",
    sleep: float = 1.0,
    timeout: int = 60,
    extra_and: Optional[str] = None,
) -> None:
    """Run cursor-based search using a query (string or list) from a params JSON file.

        Expected keys in the JSON:
            - query: str | list[str]
            - page_size, result_type, sleep, timeout (optional)
            - extra_and: str (optional; appended with AND to each query)
            - start_year, end_year (optional; if provided, constrain with PUB_YEAR:[start TO end])
    """
    data = json.loads(Path(params_file).read_text(encoding="utf-8"))
    q = data.get("query")
    if isinstance(q, str):
        queries = [q]
    elif isinstance(q, list) and all(isinstance(x, str) for x in q) and q:
        queries = q
    else:
        raise ValueError("params JSON must include 'query' as a string or non-empty list of strings")
    # Override defaults from params if present
    page_size = int(data.get("page_size", page_size))
    result_type = str(data.get("result_type", result_type))
    sleep = float(data.get("sleep", sleep))
    timeout = int(data.get("timeout", timeout))
    if extra_and is None and isinstance(data.get("extra_and"), str):
        extra_and = data["extra_and"]
    # Year range support via params file
    sy = data.get("start_year")
    ey = data.get("end_year")
    year_clause: Optional[str] = None
    try:
        if sy is not None and ey is not None:
            sy_i = int(sy)
            ey_i = int(ey)
            if sy_i <= ey_i:
                year_clause = f"PUB_YEAR:[{sy_i} TO {ey_i}]"
    except Exception:
        year_clause = None

    # Merge extra_and with year_clause if both specified
    eff_extra_and = extra_and
    if year_clause and extra_and:
        eff_extra_and = f"({extra_and}) AND ({year_clause})"
    elif year_clause and not extra_and:
        eff_extra_and = year_clause

    search_eupmc_keywords(
        queries,
        out_path,
        base_url=base_url,
        page_size=page_size,
        result_type=result_type,
        sleep=sleep,
        timeout=timeout,
        dedupe_on_write=True,
        extra_and=eff_extra_and,
    )


def cursor_yearly_dump(
    out_dir: Path = Path("Datasets/europmc_dump"),
    base_url: str = EUPMC_BASE_URL,
    query_bibliographic: str = "Lithium metal battery",
    start_year: int = 2010,
    end_year: int = datetime.now().year,
    page_size: int = 1000,
    result_type: str = "core",
    sleep: float = 1.0,
    timeout: int = 60,
    params_file: Optional[Path] = None,
    dedupe_on_write: bool = True,
    dedupe_existing: bool = False,
) -> None:
    """Fetch Europe PMC dumps per-year using cursor pagination and write JSONL files.

    We use the query pattern: (query_bibliographic) AND PUB_YEAR:YYYY
    """
    # Optional overrides from params file
    if params_file:
        try:
            data = json.loads(Path(params_file).read_text(encoding="utf-8"))
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
            overrides: Dict[str, Any] = {}
            for k, v in data.items():
                if k in key_map and v is not None:
                    overrides[key_map[k]] = v
            if isinstance(overrides.get("out_dir"), str):
                out_dir = Path(overrides["out_dir"])  # type: ignore[assignment]
            base_url = overrides.get("base_url", base_url)
            query_bibliographic = overrides.get("query_bibliographic", query_bibliographic)
            if "start_year" in overrides:
                start_year = int(overrides["start_year"])  # type: ignore[assignment]
            if "end_year" in overrides:
                end_year = int(overrides["end_year"])  # type: ignore[assignment]
            if "page_size" in overrides:
                page_size = int(overrides["page_size"])  # type: ignore[assignment]
            if "sleep" in overrides:
                sleep = float(overrides["sleep"])  # type: ignore[assignment]
            if "timeout" in overrides:
                timeout = int(overrides["timeout"])  # type: ignore[assignment]
            result_type = overrides.get("result_type", result_type)
        except Exception:
            pass

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing yearly Europe PMC dumps under: {out_dir}")

    for year in range(start_year, end_year + 1):
        year_query = f"({query_bibliographic}) AND PUB_YEAR:{year}"
        print(f"\n=== Europe PMC dump for {year}: {year_query} ===")
        output_file = out_dir / f"dumps_{year}.jsonl"
        seen: set[str] = set()
        existing_count = 0
        if output_file.exists():
            print(f"Loading existing keys from {output_file}...")
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
                    key = _dedup_key_eupmc(entry)
                    seen.add(key)
                    existing_count += 1
            print(f"Loaded {existing_count} existing entries, {len(seen)} unique keys.")
        else:
            print("No existing dump file found. Starting fresh.")

        wrote = 0
        for item in eupmc_iter_results(
            year_query,
            base_url=base_url,
            page_size=page_size,
            result_type=result_type,
            sleep=sleep,
            timeout=timeout,
        ):
            key = _dedup_key_eupmc(item)
            if dedupe_on_write and key in seen:
                continue
            seen.add(key)
            with output_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item) + "\n")
                wrote += 1
        print(f"Year {year}: appended {wrote} entries; unique keys so far: {len(seen)}")

    print("Finished Europe PMC yearly dumps.")


# --- Regex filtering (results from dumps) ---


def _compile_patterns(patterns: List[str]) -> List[re.Pattern[str]]:
    return [re.compile(p, re.I) for p in patterns]


def _default_regex_config() -> dict:
    """Default regex configuration for generalized groups-based matching.

    Neutral by default (no groups); users should provide groups via params.
    """
    return {"groups": {}, "scope": "field"}


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


def _text_to_str(val: Any) -> str:
    if isinstance(val, list):
        return " ".join(x for x in val if isinstance(x, str))
    return val if isinstance(val, str) else ""


def _eupmc_matches_entry_groups(entry: dict, groups: dict[str, List[re.Pattern[str]]], scope: str = "field") -> bool:
    title = _text_to_str(entry.get("title"))
    abstract = _text_to_str(entry.get("abstractText"))
    if scope == "title":
        return _text_matches_groups(title, groups)
    if scope == "abstract":
        return _text_matches_groups(abstract, groups)
    if scope == "field":  # any single field must satisfy all groups (default)
        return _text_matches_groups(title, groups) or _text_matches_groups(abstract, groups)
    # combined: concatenate title+abstract, allow matches across fields
    combined = " ".join(x for x in (title, abstract) if x)
    return _text_matches_groups(combined, groups)


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
    for pats in groups.values():
        if not any(rx.search(text) for rx in pats):
            return False
    return True


def regex_filter_eupmc_jsonl(
    in_path: Path,
    out_path: Path,
    regex_cfg: Optional[dict] = None,
    require_full_text: bool = False,
) -> dict:
    """Filter a single Europe PMC dump JSONL into a results JSONL using regex config.

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
            if require_full_text and not _has_full_text(obj):
                continue
            if _eupmc_matches_entry_groups(obj, groups, scope=scope):
                key = _dedup_key_eupmc(obj)
                if key in seen:
                    continue
                seen.add(key)
                fout.write(json.dumps(obj) + "\n")
                kept += 1
    return {"path": str(in_path), "out": str(out_path), "total": total, "kept": kept}


def regex_filter_eupmc_from_params(
    params_file: Path,
    in_dir: Path,
    out_dir: Path,
    require_full_text: bool = False,
) -> list[dict]:
    """Filter all JSONL dumps in a directory using regex config from params JSON.

    Returns a list of stats dicts.
    """
    params_file = Path(params_file)
    in_dir = Path(in_dir)
    out_dir = Path(out_dir)
    data = json.loads(params_file.read_text(encoding="utf-8"))
    regex_cfg = data.get("regex") if isinstance(data, dict) else None
    # Allow params to control full-text requirement too
    if isinstance(data, dict) and bool(data.get("require_full_text")):
        require_full_text = True
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for child in sorted(in_dir.iterdir()):
        if child.is_file() and child.suffix == ".jsonl":
            # Derive year-based output name: results_{year}.jsonl
            m = re.search(r"(\d{4})", child.name)
            year = m.group(1) if m else "unknown"
            out_path = out_dir / f"results_{year}.jsonl"
            stats = regex_filter_eupmc_jsonl(child, out_path, regex_cfg=regex_cfg, require_full_text=require_full_text)
            results.append(stats)
    return results


# --- Utilities: post-process JSONL de-duplication ---


def _deduplicate_jsonl_file(in_path: Path, out_path: Optional[Path] = None, in_place: bool = False) -> dict:
    """De-duplicate a JSONL file by DOI (case-insensitive) or id. Returns stats.

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
    missing_key = 0
    with in_path.open("r", encoding="utf-8") as fin, Path(temp_out).open("w", encoding="utf-8") as fout:
        for line in fin:
            total += 1
            try:
                obj = json.loads(line)
            except Exception:
                continue
            key = _dedup_key_eupmc(obj)
            if not key:
                missing_key += 1
                fout.write(json.dumps(obj) + "\n")
                kept += 1
                continue
            if key in seen:
                continue
            seen.add(key)
            fout.write(json.dumps(obj) + "\n")
            kept += 1
    if in_place:
        Path(temp_out).replace(in_path)
    return {"total": total, "kept": kept, "duplicates": total - kept, "missing_key": missing_key}


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


def _has_full_text(entry: dict) -> bool:
    """Heuristic: True if entry appears to have a Europe PMC full text.

    Signals considered:
    - fullTextIdList.fullTextId non-empty
    - pmcid present
    - inEPMC or inPMC == "Y"
    """
    try:
        ft = entry.get("fullTextIdList") or {}
        if isinstance(ft, dict):
            lst = ft.get("fullTextId")
            if isinstance(lst, list) and len(lst) > 0:
                return True
        if entry.get("pmcid"):
            return True
        if str(entry.get("inEPMC", "")).upper() == "Y" or str(entry.get("inPMC", "")).upper() == "Y":
            return True
    except Exception:
        return False
    return False
