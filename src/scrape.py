"""
Scraping helpers for downloading PDFs/XMLs from multiple sources.

Flows supported:
- ChemRxiv dump → download PDFs via paperscraper.save_pdf_from_dump
- Crossref dump → use direct requests for Wiley and Elsevier with fallbacks (Elsevier XML, Unpaywall),
  and Unpaywall for other publishers. This avoids paperscraper's Crossref path.

API keys: prefer env variables; optionally load from a KEY=VALUE file
for convenience (e.g., `refactor_skeleton/examples/lithium_metal_anode/scrape/api_keys.txt`).
Supported keys (env or file KEY=VALUE lines):
- WILEY_TDM_API_TOKEN
- ELSEVIER_TDM_API_KEY
- UNPAYWALL_EMAIL
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Dict
import time

try:  # requests is a common dependency; imported lazily in functions too
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore


@dataclass
class ApiKeys:
    wiley_tdm_api_token: Optional[str] = None
    elsevier_tdm_api_key: Optional[str] = None
    unpaywall_email: Optional[str] = None

    @classmethod
    def from_env_or_file(cls, api_keys_file: Optional[Path] = None) -> "ApiKeys":
        # Prefer environment variables
        wiley = os.getenv("WILEY_TDM_API_TOKEN")
        elsevier = os.getenv("ELSEVIER_TDM_API_KEY")
        unpaywall = os.getenv("UNPAYWALL_EMAIL")
        if (wiley or elsevier or unpaywall) and (api_keys_file is None or not Path(api_keys_file).exists()):
            return cls(wiley_tdm_api_token=wiley, elsevier_tdm_api_key=elsevier, unpaywall_email=unpaywall)
        # Fallback to local file with KEY=VALUE lines
        d = {}
        if api_keys_file and Path(api_keys_file).exists():
            for line in Path(api_keys_file).read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip()
        return cls(
            wiley_tdm_api_token=d.get("WILEY_TDM_API_TOKEN", wiley),
            elsevier_tdm_api_key=d.get("ELSEVIER_TDM_API_KEY", elsevier),
            unpaywall_email=d.get("UNPAYWALL_EMAIL", unpaywall),
        )


def iter_jsonl(path: Path) -> Iterable[dict]:
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

def _api_keys_arg(api_keys_file: Optional[Path]) -> Optional[Dict[str, str]] | str | None:
    """Return the appropriate api_keys argument for paperscraper.
    - If a file path is provided and exists, return the string path.
    - Else, return a dict from environment.
    """
    if api_keys_file and Path(api_keys_file).exists():
        return str(api_keys_file)
    keys = ApiKeys.from_env_or_file(api_keys_file)
    d: Dict[str, str] = {}
    if keys.wiley_tdm_api_token:
        d["WILEY_TDM_API_TOKEN"] = keys.wiley_tdm_api_token
    if keys.elsevier_tdm_api_key:
        d["ELSEVIER_TDM_API_KEY"] = keys.elsevier_tdm_api_key
    return d if d else None


# -----------------------------
# Crossref direct download impl
# -----------------------------

def _safe_request(*args, tries: int = 3, timeout: int = 30, **kwargs):
    if requests is None:  # pragma: no cover
        raise RuntimeError("requests is required for crossref scraping but is not installed")
    for attempt in range(tries):
        try:
            return requests.get(*args, timeout=timeout, **kwargs)
        except Exception as e:  # ConnectionError, ReadTimeout, etc.
            print(f"[crossref] Connection error: {e}. Retrying ({attempt+1}/{tries})...")
            time.sleep(2)
    return None


def _sanitize_name(s: str) -> str:
    return s.replace("/", "_")


def download_pdf_wiley(doi: str, outdir: Path, api_keys: ApiKeys) -> tuple[Optional[Path], Optional[str]]:
    """Attempt Wiley TDM PDF download for a DOI. Returns (path, source) on success, else (None, None)."""
    token = api_keys.wiley_tdm_api_token
    if not token:
        return None, None
    outdir.mkdir(parents=True, exist_ok=True)
    filename = outdir / f"{_sanitize_name(doi)}.pdf"
    if filename.exists():
        return filename, "Wiley (already exists)"
    url = f"https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}"
    headers = {"Wiley-TDM-Client-Token": token}
    r = _safe_request(url, headers=headers, stream=True)
    if r and r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/pdf"):
        with open(filename, "wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
        return filename, "Wiley"
    return None, None


def download_pdf_elsevier_scidir(doi: str, outdir: Path, api_keys: ApiKeys) -> tuple[Optional[Path], Optional[str]]:
    key = api_keys.elsevier_tdm_api_key
    if not key:
        return None, None
    outdir.mkdir(parents=True, exist_ok=True)
    filename = outdir / f"{_sanitize_name(doi)}.pdf"
    if filename.exists():
        return filename, "Elsevier-ScienceDirect (already exists)"
    url = f"https://api.elsevier.com/content/article/doi/{doi}"
    headers = {"X-ELS-APIKey": key, "Accept": "application/json"}
    r = _safe_request(url, headers=headers)
    if r and r.status_code == 200:
        try:
            data = r.json()
        except Exception:
            data = {}
        links = (
            data.get("full-text-retrieval-response", {})
            .get("coredata", {})
            .get("link", [])
        )
        for link in links:
            try:
                if link.get("@rel") == "scidir-pdf":
                    pdf_url = link.get("@href")
                    if not pdf_url:
                        continue
                    pdf_response = _safe_request(pdf_url, headers={"X-ELS-APIKey": key}, stream=True)
                    if (
                        pdf_response
                        and pdf_response.status_code == 200
                        and pdf_response.headers.get("Content-Type", "").startswith("application/pdf")
                    ):
                        with open(filename, "wb") as f:
                            for chunk in pdf_response.iter_content(1024):
                                f.write(chunk)
                        return filename, "Elsevier-ScienceDirect"
            except Exception:
                continue
    return None, None


def download_elsevier_xml(doi: str, outdir: Path, api_keys: ApiKeys) -> tuple[Optional[Path], Optional[str]]:
    key = api_keys.elsevier_tdm_api_key
    if not key:
        return None, None
    outdir.mkdir(parents=True, exist_ok=True)
    filename = outdir / f"{_sanitize_name(doi)}.xml"
    if filename.exists():
        return filename, "Elsevier-XML (already exists)"
    url = f"https://api.elsevier.com/content/article/doi/{doi}?APIKey={key}&httpAccept=text/xml&view=FULL"
    headers = {"Accept": "text/xml"}
    r = _safe_request(url, headers=headers)
    if r and r.status_code == 200 and r.headers.get("Content-Type", "").startswith("text/xml"):
        with open(filename, "wb") as f:
            f.write(r.content)
        return filename, "Elsevier-XML"
    return None, None


def download_pdf_unpaywall(doi: str, outdir: Path, email: Optional[str]) -> tuple[Optional[Path | str], Optional[str]]:
    if not email:
        return None, None
    outdir.mkdir(parents=True, exist_ok=True)
    filename = outdir / f"{_sanitize_name(doi)}.pdf"
    if filename.exists():
        return filename, "Unpaywall (already exists)"
    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    r = _safe_request(url)
    if r and r.status_code == 200:
        try:
            data = r.json()
        except Exception:
            data = {}
        best = data.get("best_oa_location")
        pdf_url = best.get("url_for_pdf") if best else None
        if pdf_url:
            pdf_response = _safe_request(pdf_url, stream=True)
            if (
                pdf_response
                and pdf_response.status_code == 200
                and pdf_response.headers.get("Content-Type", "").startswith("application/pdf")
            ):
                with open(filename, "wb") as f:
                    for chunk in pdf_response.iter_content(1024):
                        f.write(chunk)
                return filename, "Unpaywall"
            else:
                return pdf_url, "Unpaywall-URL"
    return None, None


def save_pdfs_from_chemrxiv(
    input_path: Path,
    pdf_root_dir: Path,
    key_to_save: str = "doi",
    api_keys_file: Optional[Path] = None,
    per_file_subdirs: bool = False,
    sleep_seconds: float = 0.0,
) -> None:
    """
    Download PDFs from ChemRxiv results using paperscraper.save_pdf_from_dump.

    Behavior:
    - If input_path is a single JSONL file: write PDFs to pdf_root_dir (or to a subfolder named after the file if per_file_subdirs=True).
    - If input_path is a directory: iterate all .jsonl files; write PDFs either all into pdf_root_dir, or into per-file subfolders under pdf_root_dir when per_file_subdirs=True.

    A single public entry-point to make it easy to invoke from scripts/CLI.
    """
    # Import lazily to keep module importable without paperscraper installed
    try:
        from paperscraper.pdf import save_pdf_from_dump as ps_save_pdf_from_dump  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("paperscraper is not installed; cannot run ChemRxiv download") from e

    api_keys = _api_keys_arg(api_keys_file)
    pdf_root = Path(pdf_root_dir)
    pdf_root.mkdir(parents=True, exist_ok=True)

    def _run_one(file_path: Path) -> None:
        # Determine destination: common folder or subfolder named after the file
        if per_file_subdirs:
            sub = pdf_root / file_path.stem
            sub.mkdir(parents=True, exist_ok=True)
            out_dir = sub
        else:
            out_dir = pdf_root
        print(f"[chemrxiv] Saving PDFs from: {file_path} → {out_dir}")
        ps_save_pdf_from_dump(
            str(file_path),
            pdf_path=str(out_dir),
            key_to_save=key_to_save,
            save_metadata=False,
            api_keys=api_keys,
        )

    p = Path(input_path)
    if p.is_file():
        _run_one(p)
        return

    if p.is_dir():
        files = sorted(fp for fp in p.iterdir() if fp.suffix == ".jsonl")
        if not files:
            print(f"[chemrxiv] No JSONL files found in {p}")
            return
        for fp in files:
            try:
                _run_one(fp)
            except Exception as e:
                print(f"[chemrxiv] Error saving PDFs for {fp}: {e}")
            if sleep_seconds and sleep_seconds > 0:
                import time as _time
                _time.sleep(sleep_seconds)
        return

    raise ValueError(f"Path must be a .jsonl file or directory: {input_path}")


def save_pdfs_from_crossref_dump(
    dump_path: Path,
    pdf_out_dir: Path,
    *,
    key_to_save: str = "doi",
    publishers: Optional[Iterable[str]] = None,
    api_keys_file: Optional[Path] = None,
    unpaywall_email: Optional[str] = None,
    xml_out_dir: Optional[Path] = None,
    not_downloaded_out: Optional[Path] = None,
    sleep_seconds: float = 1.0,
) -> None:
    """Download PDFs (and optionally Elsevier XML) from a Crossref results JSONL using direct requests.

    Strategy per entry (based on publisher field):
    - Wiley: try Wiley TDM PDF → fallback to Unpaywall
    - Elsevier: try ScienceDirect PDF → fallback to Elsevier XML (if xml_out_dir) → fallback to Unpaywall
    - Others: try Unpaywall

    Arguments:
    - dump_path: JSONL of Crossref results
    - pdf_out_dir: where to save PDFs
    - key_to_save: key holding the DOI (default 'doi')
    - publishers: optional allow-list (case-insensitive substring match) to process only specific publishers
    - api_keys_file: optional KEY=VALUE file supporting WILEY_TDM_API_TOKEN, ELSEVIER_TDM_API_KEY, UNPAYWALL_EMAIL
    - unpaywall_email: overrides UNPAYWALL_EMAIL from env/file
    - xml_out_dir: when provided, save Elsevier XML here on fallback
    - not_downloaded_out: path to write entries with no API-accessible PDF (defaults to parent of pdf_out_dir)
    - sleep_seconds: polite delay between entries
    """
    keys = ApiKeys.from_env_or_file(api_keys_file)
    if unpaywall_email:
        keys.unpaywall_email = unpaywall_email

    pdf_out_dir = Path(pdf_out_dir)
    pdf_out_dir.mkdir(parents=True, exist_ok=True)
    xml_out_dir = Path(xml_out_dir) if xml_out_dir else None
    if xml_out_dir:
        xml_out_dir.mkdir(parents=True, exist_ok=True)
    if not_downloaded_out is None:
        not_downloaded_out = pdf_out_dir.parent / "not_api_available.jsonl"
    not_downloaded: list[dict] = []

    pubs_lower = {p.lower() for p in publishers} if publishers else None

    for entry in iter_jsonl(dump_path):
        doi = entry.get(key_to_save) or entry.get("DOI")
        if not doi:
            continue
        publisher = str(entry.get("publisher", ""))
        if pubs_lower:
            if not any(p in publisher.lower() for p in pubs_lower):
                continue

        attempts: list[str] = []
        saved = False

        # Branch by publisher
        if "wiley" in publisher.lower():
            attempts.append("Wiley PDF")
            path, source = download_pdf_wiley(doi, pdf_out_dir, keys)
            if path:
                print(f"Downloaded PDF for {doi} (Publisher: {publisher}) via {source}: {path} [Attempted: {', '.join(attempts)}]")
                saved = True
            if not saved:
                attempts.append("Unpaywall PDF")
                path, source = download_pdf_unpaywall(doi, pdf_out_dir, keys.unpaywall_email)
                if path and isinstance(path, Path) and path.suffix == ".pdf":
                    print(f"Downloaded PDF for {doi} (Publisher: {publisher}) via {source}: {path} [Attempted: {', '.join(attempts)}]")
                    saved = True

        elif "elsevier" in publisher.lower():
            attempts.append("Elsevier ScienceDirect PDF")
            path, source = download_pdf_elsevier_scidir(doi, pdf_out_dir, keys)
            if path:
                print(f"Downloaded PDF for {doi} (Publisher: {publisher}) via {source}: {path} [Attempted: {', '.join(attempts)}]")
                saved = True
            if not saved and xml_out_dir is not None:
                attempts.append("Elsevier XML")
                x_path, x_source = download_elsevier_xml(doi, xml_out_dir, keys)
                if x_path:
                    print(f"Downloaded XML for {doi} (Publisher: {publisher}) via {x_source}: {x_path} [Attempted: {', '.join(attempts)}]")
            if not saved:
                attempts.append("Unpaywall PDF")
                path, source = download_pdf_unpaywall(doi, pdf_out_dir, keys.unpaywall_email)
                if path and isinstance(path, Path) and path.suffix == ".pdf":
                    print(f"Downloaded PDF for {doi} (Publisher: {publisher}) via {source}: {path} [Attempted: {', '.join(attempts)}]")
                    saved = True

        else:
            attempts.append("Unpaywall PDF")
            path, source = download_pdf_unpaywall(doi, pdf_out_dir, keys.unpaywall_email)
            if path and isinstance(path, Path) and path.suffix == ".pdf":
                print(f"Downloaded PDF for {doi} (Publisher: {publisher}) via {source}: {path} [Attempted: {', '.join(attempts)}]")
                saved = True

        if not saved:
            print(f"No API PDF found for {doi} (Publisher: {publisher}) [Attempted: {', '.join(attempts)}]")
            not_downloaded.append(entry)

        if sleep_seconds and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    # Write not-downloaded entries
    if not_downloaded:
        not_path = Path(not_downloaded_out)
        not_path.parent.mkdir(parents=True, exist_ok=True)
        with open(not_path, "w", encoding="utf-8") as out_f:
            for e in not_downloaded:
                out_f.write(json.dumps(e) + "\n")
        print(f"Wrote {len(not_downloaded)} entries to {not_path}")
    else:
        print("All PDFs were downloaded or already present.")


# --------------------------------------
# Europe PMC: download full-text XML only
# --------------------------------------

def _safe_request_eupmc(*args, tries: int = 3, timeout: int = 60, **kwargs):
    if requests is None:  # pragma: no cover
        raise RuntimeError("requests is required for Europe PMC scraping but is not installed")
    for attempt in range(tries):
        try:
            return requests.get(*args, timeout=timeout, **kwargs)
        except Exception as e:
            print(f"[europmc] Connection error: {e}. Retrying ({attempt+1}/{tries})...")
            time.sleep(2)
    return None


def _pmcid_from_entry(entry: dict) -> Optional[str]:
    pmcid = entry.get("pmcid")
    if isinstance(pmcid, str) and pmcid:
        return pmcid
    ft = entry.get("fullTextIdList") or {}
    if isinstance(ft, dict):
        lst = ft.get("fullTextId")
        if isinstance(lst, list):
            for v in lst:
                if isinstance(v, str) and v.startswith("PMC"):
                    return v
    return None


def save_eupmc_xml_from_results(
    input_path: Path,
    xml_out_dir: Path,
    *,
    sleep_seconds: float = 0.0,
) -> None:
    """Download full-text XMLs for Europe PMC results.

    Assumes inputs were pre-filtered to "require_full_text"; we simply fetch JATS XML by PMCID.

    - If input_path is a JSONL file: write XMLs to xml_out_dir
    - If input_path is a directory: iterate all .jsonl files and write XMLs to xml_out_dir
    """
    xml_out_dir = Path(xml_out_dir)
    xml_out_dir.mkdir(parents=True, exist_ok=True)

    def _process_file(fp: Path) -> None:
        count = 0
        for entry in iter_jsonl(fp):
            pmcid = _pmcid_from_entry(entry)
            if not pmcid:
                # Should be rare if require_full_text was enforced; skip quietly
                continue
            out_path = xml_out_dir / f"{_sanitize_name(pmcid)}.xml"
            if out_path.exists():
                # Already downloaded
                continue
            url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
            r = _safe_request_eupmc(url, headers={"Accept": "application/xml, text/xml"})
            if r and r.status_code == 200 and (
                r.headers.get("Content-Type", "").startswith("application/xml")
                or r.headers.get("Content-Type", "").startswith("text/xml")
            ):
                with open(out_path, "wb") as f:
                    f.write(r.content)
                count += 1
            if sleep_seconds and sleep_seconds > 0:
                time.sleep(sleep_seconds)
        print(f"[europmc] Saved {count} XML files from {fp} → {xml_out_dir}")

    p = Path(input_path)
    if p.is_file():
        _process_file(p)
        return
    if p.is_dir():
        files = sorted(fp for fp in p.iterdir() if fp.suffix == ".jsonl")
        if not files:
            print(f"[europmc] No JSONL files found in {p}")
            return
        for fp in files:
            try:
                _process_file(fp)
            except Exception as e:
                print(f"[europmc] Error saving XML for {fp}: {e}")
        return
    raise ValueError(f"Path must be a .jsonl file or directory: {input_path}")
