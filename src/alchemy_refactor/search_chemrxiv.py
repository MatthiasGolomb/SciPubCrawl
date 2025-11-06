"""
ChemRxiv monthly scraping and metadata querying utilities.

- scrape_chemrxiv_monthly: iterate month-by-month and save dumps to chemrxiv_dumps/
    (skips months where output file already exists and is non-empty)
- query_chemrxiv_dumps: run keyword-group queries over each dump file and store results in chemrxiv_results/
- run_from_params: end-to-end flow configurable by a chemrxiv_params.json

Functions are importable and usable via a thin CLI in scripts/search_chemrxiv.py.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# Note: external dependencies are imported lazily inside functions to keep this module importable
# even if optional packages are not installed in the analysis environment.


# ---- Data models ----

@dataclass
class ChemRxivParams:
    start_date: str = "2018-01-01"  # YYYY-MM-DD
    end_date: Optional[str] = None   # YYYY-MM-DD; defaults to today
    dump_dir: str = "chemrxiv_dumps"
    result_dir: str = "chemrxiv_results"
    sleep_seconds: float = 5.0
    query: Optional[Sequence[Sequence[str]]] = None  # 2+ groups for Cartesian AND over groups

    @staticmethod
    def default_query() -> List[List[str]]:
        li_metal = ["lithium anode", "lithium metal anode", "lithium metal"]
        elec = ["electrolyte", "solvent", "liquid electrolyte"]
        return [li_metal, elec]

    @classmethod
    def load(cls, params_file: Path) -> "ChemRxivParams":
        raw = json.loads(Path(params_file).read_text())
        # Resolve relative dirs based on params file location
        base = params_file.parent
        dump_dir = str((base / raw.get("dump_dir", cls.dump_dir)).resolve())
        result_dir = str((base / raw.get("result_dir", cls.result_dir)).resolve())
        query = raw.get("query")
        return cls(
            start_date=raw.get("start_date", cls.start_date),
            end_date=raw.get("end_date"),
            dump_dir=dump_dir,
            result_dir=result_dir,
            sleep_seconds=float(raw.get("sleep_seconds", cls.sleep_seconds)),
            query=query,
        )


# ---- Core functionality ----

def _month_iter(start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    """Yield (start, end) ranges for each month between start (inclusive) and end (exclusive)."""
    ranges: List[Tuple[datetime, datetime]] = []
    current = start
    while current < end:
        next_month = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        month_end = min(next_month, end)
        ranges.append((current, month_end))
        current = next_month
    return ranges


def scrape_chemrxiv_monthly(
    start_date: str = "2018-01-01",
    end_date: Optional[str] = None,
    save_dir: Path | str = "chemrxiv_dumps",
    sleep_seconds: float = 5.0,
    retry_on_decode_error: bool = True,
    fallback_chunk_days: int = 7,
) -> None:
    """
    Iterate through the ChemRxiv API in monthly steps and save JSONL dumps.

    Skips a month if the output file already exists and is non-empty.
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    if end_date is None:
        end_date = datetime.today().strftime("%Y-%m-%d")

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # Lazy import here to avoid hard failure when the package isn't installed yet
    try:
        from paperscraper.get_dumps import chemrxiv as chemrxiv_dump  # type: ignore
    except Exception as e:  # pragma: no cover - environment-specific
        raise RuntimeError("paperscraper is required for scrape_chemrxiv_monthly; install it via requirements.txt") from e

    for m_start, m_end in _month_iter(start_dt, end_dt):
        start_s = m_start.strftime("%Y-%m-%d")
        end_s = m_end.strftime("%Y-%m-%d")
        out_path = save_dir / f"chemrxiv_{start_s}_{end_s}.jsonl"

        # Skip if exists and non-empty
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"[chemrxiv] Skipping existing file (non-empty): {out_path}")
            continue

        print(f"[chemrxiv] Scraping {start_s} → {end_s} → {out_path}")
        try:
            chemrxiv_dump(save_path=str(out_path), start_date=start_s, end_date=end_s)
        except Exception as e:
            msg = str(e)
            print(f"[chemrxiv] Error scraping {start_s}–{end_s}: {msg}")
            # brief backoff on error to avoid tight retry loops
            try:
                time.sleep(2)
            except Exception:
                pass
            if retry_on_decode_error:
                print(f"[chemrxiv] Retrying {start_s}–{end_s} in smaller chunks (starting with {fallback_chunk_days} days)...")
                _scrape_range_chunked(
                    start_s,
                    end_s,
                    save_dir=save_dir,
                    out_path=out_path,
                    chunk_days=fallback_chunk_days,
                    sleep_seconds=sleep_seconds,
                    chemrxiv_dump=chemrxiv_dump,
                )
            else:
                print(f"[chemrxiv] Skipping period {start_s}–{end_s} after error.")
        time.sleep(sleep_seconds)


def query_chemrxiv_dumps(
    dump_dir: Path | str = "chemrxiv_dumps",
    result_dir: Path | str = "chemrxiv_results",
    query_groups: Optional[Sequence[Sequence[str]]] = None,
    force: bool = False,
) -> None:
    """
    Query all JSONL dumps in dump_dir using XRXivQuery.search_keywords with grouped keywords.

    query_groups should be a sequence of groups; terms within a group are ORed, and
    groups are ANDed. If not provided, uses the default lithium-metal/electrolyte groups.
    """
    dump_dir = Path(dump_dir)
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    if query_groups is None:
        query_groups = ChemRxivParams.default_query()

    files = sorted(p for p in dump_dir.iterdir() if p.suffix == ".jsonl")
    if not files:
        print(f"[chemrxiv] No dump files found in {dump_dir}")
        return

    # Lazy import here
    try:
        from paperscraper.xrxiv.xrxiv_query import XRXivQuery  # type: ignore
    except Exception as e:  # pragma: no cover - environment-specific
        raise RuntimeError("paperscraper is required for query_chemrxiv_dumps; install it via requirements.txt") from e

    for in_file in files:
        out_file = result_dir / f"results_{in_file.name}"
        if out_file.exists() and out_file.stat().st_size > 0 and not force:
            print(f"[chemrxiv] Skipping existing results (non-empty): {out_file}")
            continue
        print(f"[chemrxiv] Querying {in_file} → {out_file}")
        try:
            querier = XRXivQuery(str(in_file))
            querier.search_keywords(list(query_groups), output_filepath=str(out_file))
        except Exception as e:
            print(f"[chemrxiv] Error querying {in_file}: {e}")


def run_from_params(
    params_file: Path,
    override_start_date: Optional[str] = None,
    override_end_date: Optional[str] = None,
    override_dump_dir: Optional[Path | str] = None,
    override_result_dir: Optional[Path | str] = None,
    override_sleep: Optional[float] = None,
    force_query: bool = False,
) -> None:
    """End-to-end: scrape monthly then query, using a chemrxiv_params.json file."""
    params = ChemRxivParams.load(params_file)

    # Apply overrides (CLI should take precedence over params)
    start_date = override_start_date or params.start_date
    end_date = override_end_date or params.end_date
    dump_dir = Path(override_dump_dir) if override_dump_dir else Path(params.dump_dir)
    result_dir = Path(override_result_dir) if override_result_dir else Path(params.result_dir)
    sleep_seconds = float(override_sleep) if override_sleep is not None else params.sleep_seconds
    query_groups = params.query if params.query is not None else ChemRxivParams.default_query()

    print(f"[chemrxiv] Writing dumps under: {dump_dir}")
    scrape_chemrxiv_monthly(start_date=start_date, end_date=end_date, save_dir=dump_dir, sleep_seconds=sleep_seconds)

    print(f"[chemrxiv] Writing queried results under: {result_dir}")
    query_chemrxiv_dumps(dump_dir=dump_dir, result_dir=result_dir, query_groups=query_groups, force=force_query)


# ---- Helpers for chunked retries and merging ----

def _scrape_range_chunked(
    start_s: str,
    end_s: str,
    save_dir: Path,
    out_path: Path,
    chunk_days: int,
    sleep_seconds: float,
    chemrxiv_dump,
) -> None:
    """Retry a large period by splitting into smaller chunks and merging results."""
    from datetime import datetime, timedelta

    save_dir = Path(save_dir)
    out_path = Path(out_path)
    tmp_dir = save_dir / f".tmp_chunks_{start_s}_{end_s}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    s_dt = datetime.strptime(start_s, "%Y-%m-%d")
    e_dt = datetime.strptime(end_s, "%Y-%m-%d")

    cur = s_dt
    chunk_paths: list[Path] = []
    while cur < e_dt:
        nxt = min(cur + timedelta(days=chunk_days), e_dt)
        s2 = cur.strftime("%Y-%m-%d")
        e2 = nxt.strftime("%Y-%m-%d")
        chunk_out = tmp_dir / f"chemrxiv_{s2}_{e2}.jsonl"
        if chunk_out.exists() and chunk_out.stat().st_size > 0:
            print(f"[chemrxiv] (chunk) Skipping existing file: {chunk_out}")
        else:
            print(f"[chemrxiv] (chunk) Scraping {s2} → {e2} → {chunk_out}")
            try:
                chemrxiv_dump(save_path=str(chunk_out), start_date=s2, end_date=e2)
            except Exception as ce:
                print(f"[chemrxiv] (chunk) Error scraping {s2}–{e2}: {ce}")
                # brief backoff
                try:
                    _time = __import__("time")
                    _time.sleep(2)
                except Exception:
                    pass
                # Progressive fallback: try smaller chunk sizes (e.g., 3 days, then 1 day)
                smaller_sizes = []
                if chunk_days > 3:
                    smaller_sizes.append(3)
                if chunk_days > 1:
                    smaller_sizes.append(1)
                for sz in smaller_sizes:
                    if sz >= chunk_days:
                        continue
                    print(f"[chemrxiv] (chunk) Retrying {s2}–{e2} with {sz}-day sub-chunks...")
                    # Recursively split the failed subrange and merge into chunk_out
                    try:
                        _scrape_range_chunked(
                            s2,
                            e2,
                            save_dir=tmp_dir,
                            out_path=chunk_out,
                            chunk_days=sz,
                            sleep_seconds=sleep_seconds,
                            chemrxiv_dump=chemrxiv_dump,
                        )
                        break  # stop trying smaller sizes once succeeded
                    except Exception as ce2:
                        print(f"[chemrxiv] (chunk) Secondary error with {sz}-day chunks for {s2}–{e2}: {ce2}")
                        try:
                            _time = __import__("time")
                            _time.sleep(2)
                        except Exception:
                            pass
        chunk_paths.append(chunk_out)
        if sleep_seconds and sleep_seconds > 0:
            import time as _time
            _time.sleep(sleep_seconds)
        cur = nxt

    # Merge chunk files with DOI-based de-duplication
    _merge_jsonl_unique(chunk_paths, out_path)
    # Optional: cleanup temp directory
    try:
        for p in chunk_paths:
            if p.exists():
                p.unlink()
        tmp_dir.rmdir()
    except Exception:
        pass


def _merge_jsonl_unique(paths: list[Path], out_path: Path) -> None:
    """Merge multiple JSONL files into one, de-duplicating by DOI (case-insensitive)."""
    out_path = Path(out_path)
    seen: set[str] = set()
    total = 0
    kept = 0
    with out_path.open("w", encoding="utf-8") as fout:
        for p in paths:
            if not p.exists() or p.stat().st_size == 0:
                continue
            with p.open("r", encoding="utf-8") as fin:
                for line in fin:
                    total += 1
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    doi = (obj.get("doi") or obj.get("DOI") or "").strip().lower()
                    if doi and doi in seen:
                        continue
                    if doi:
                        seen.add(doi)
                    fout.write(json.dumps(obj) + "\n")
                    kept += 1
    print(f"[chemrxiv] Merged chunks → {out_path} (total lines: {total}, unique kept: {kept})")

