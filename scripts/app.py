#!/usr/bin/env python3
"""
Streamlit GUI for search_crossref.py

To run:
1. Make sure this file is in the same directory as the original search_crossref.py
   (e.g., in the 'scripts/' folder).
2. Make sure src/search_crossref.py exists and is importable.
3. Run: streamlit run app.py
"""
import streamlit as st
import importlib.util
import sys
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime

# --- Module Loading Logic (from your script) ---

@st.cache_resource
def _load_module() -> object:
    """Load Crossref search utilities from src/"""
    try:
        this_dir = Path(__file__).resolve().parent
        src_root = this_dir.parent / "src"
        module_file = src_root / "search_crossref.py"
        spec = importlib.util.spec_from_file_location("search_crossref", str(module_file))
        assert spec and spec.loader, f"Cannot load module from {module_file}"
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        return mod
    except Exception as e:
        st.error(f"Fatal Error: Could not load module from 'src/search_crossref.py'.")
        st.error("Please ensure 'app.py' is in the 'scripts/' directory and 'src/search_crossref.py' exists.")
        st.exception(e)
        st.stop()
        
def parse_filter_kv_from_textarea(text: str) -> dict:
    """Parses a multi-line k:v text area into a dict."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out

def _safe_load_json(uploaded_file):
    """Safely loads JSON from an uploaded file."""
    if uploaded_file is None:
        return None
    try:
        string_data = uploaded_file.getvalue().decode("utf-8")
        return json.loads(string_data)
    except Exception as e:
        st.error(f"Error reading params file: {e}")
        return None

# --- UI Functions for Each Tab ---

def ui_keywords(mod):
    """UI for the 'keywords' command."""
    search_crossref_from_params = getattr(mod, "search_crossref_from_params")
    search_crossref_cursor = getattr(mod, "search_crossref_cursor")
    
    st.header("Keyword-Based Search")
    st.write("Run a cursor-based search using keywords, optionally configured from a params JSON file.")

    params_file = st.file_uploader("Params JSON (Optional)", type=["json"], 
                                   help="JSON file with 'query' (str or list[str]) and optional filters/settings.")
    
    st.subheader("Configuration")
    
    # Load defaults from params file if provided
    params_data = _safe_load_json(params_file)
    if params_data is None:
        params_data = {}

    # CLI args defaults
    default_rows = params_data.get("rows", 1000)
    default_select = params_data.get("select", "DOI,publisher,title,license,abstract")
    default_mailto = params_data.get("mailto", "")
    default_app_name = params_data.get("app_name", "High-throughput design of lithium metal electrolytes")
    
    out_file = st.text_input("Output File Path", "search/crossref_dumps/keywords_dump.jsonl", 
                             help="Path to write the results (e.g., `search/crossref_dumps/keywords_dump.jsonl`)")

    if not params_file:
        queries = st.text_area("Queries (one per line)", "Lithium metal battery",
                               help="Used if no params file is provided.")
        query_list = [q.strip() for q in queries.splitlines() if q.strip()]
    
    filter_text = st.text_area("Extra Filters (one 'key:value' per line)", 
                               help="Optional Crossref filters (e.g., `type:journal-article`)")
    
    no_dedupe = st.toggle("Disable De-duplication", value=False, 
                          help="Disable on-write de-duplication by DOI.", 
                          key="kw_no_dedupe")

    with st.expander("Advanced Options"):
        rows = st.number_input("Rows per Request", min_value=1, max_value=1000, value=default_rows, key="kw_rows")
        select = st.text_input("Fields to Select", default_select, key="kw_select")
        mailto = st.text_input("MailTo (Crossref 'polite' pool)", default_mailto, key="kw_mailto")
        app_name = st.text_input("App Name", default_app_name, key="kw_app_name")
        app_version = st.text_input("App Version", params_data.get("app_version", "0.1"), key="kw_app_version")
        app_url = st.text_input("App URL", params_data.get("app_url", "None"), key="kw_app_url")
        base_url = st.text_input("Crossref API URL", params_data.get("base_url", "https://api.crossref.org/works"), key="kw_base_url")

    if st.button("Run Keyword Search", type="primary"):
        if not out_file:
            st.error("Please provide an output file path.")
            return

        out_path = Path(out_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        extra_filters = parse_filter_kv_from_textarea(filter_text)
        
        with st.spinner(f"Running search... Writing to {out_file}"):
            try:
                if params_file:
                    # Need to save the uploaded file to disk temporarily for the function
                    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.json') as f:
                        f.write(params_file.getvalue().decode('utf-8'))
                        temp_params_path = Path(f.name)
                    
                    st.write(f"Using params file: {params_file.name}")
                    search_crossref_from_params(
                        temp_params_path,
                        out_path,
                        base_url=base_url,
                        select=select,
                        rows=rows,
                        mailto=mailto,
                        app_name=app_name,
                        app_version=app_version,
                        app_url=app_url,
                        extra_filter_args=extra_filters,
                    )
                    os.unlink(temp_params_path) # Clean up temp file

                else:
                    if not query_list:
                        st.error("Please provide at least one query.")
                        return
                    st.write(f"Using manual queries: {query_list}")
                    search_crossref_cursor(
                        query_list,
                        out_path,
                        filter_args=extra_filters,
                        base_url=base_url,
                        select=select,
                        rows=rows,
                        mailto=mailto,
                        app_name=app_name,
                        app_version=app_version,
                        app_url=app_url,
                        dedupe_on_write=(not no_dedupe),
                    )
                st.success(f"Search complete! Results saved to {out_file}")
            except Exception as e:
                st.exception(e)

def ui_yearly(mod):
    """UI for the 'cursor-yearly' command."""
    cursor_yearly_dump = getattr(mod, "cursor_yearly_dump")

    st.header("Yearly Cursor Dump")
    st.write("Fetch Crossref data year-by-year for a specific query.")
    
    params_file = st.file_uploader("Params JSON (Optional)", type=["json"],
                                   help="JSON file with defaults to override (query, start_year, end_year, etc.)")
    
    # Load defaults from params file if provided
    params_data = _safe_load_json(params_file)
    if params_data is None:
        params_data = {}
    
    # Map params keys
    key_map = {
        "out_dir": "out_dir", "output_dir": "out_dir", "base_url": "base_url",
        "query": "query_bibliographic", "query_bibliographic": "query_bibliographic",
        "start_year": "start_year", "end_year": "end_year", "rows": "rows",
        "mailto": "mailto", "select": "select", "restart_threshold": "restart_threshold",
        "app_name": "app_name", "app_version": "app_version", "app_url": "app_url",
    }
    
    def get_param(key, default):
        for k, mapped_key in key_map.items():
            if mapped_key == key and k in params_data:
                return params_data[k]
        return default

    # Set defaults, overridden by params
    default_out_dir = str(get_param("out_dir", "search/crossref_dumps"))
    default_query = str(get_param("query_bibliographic", "Lithium metal battery"))
    default_start_year = int(get_param("start_year", 2010))
    default_end_year = int(get_param("end_year", datetime.now().year))
    default_rows = int(get_param("rows", 1000))
    default_mailto = str(get_param("mailto", "m.golomb@surrey.ac.uk"))
    default_select = str(get_param("select", "DOI,publisher,title,license,abstract"))
    default_restart = int(get_param("restart_threshold", 100000))
    default_app_name = str(get_param("app_name", "High-throughput design of lithium metal electrolytes"))
    default_app_version = str(get_param("app_version", "0.1"))
    default_app_url = str(get_param("app_url", "None"))
    default_base_url = str(get_param("base_url", "https://api.crossref.org/works"))

    st.subheader("Configuration")
    
    out_dir = st.text_input("Output Directory", default_out_dir, 
                            help="Directory to save the per-year JSONL dump files.")
    query = st.text_input("Query", default_query)
    
    col1, col2 = st.columns(2)
    with col1:
        start_year = st.number_input("Start Year", min_value=1900, max_value=datetime.now().year, value=default_start_year)
    with col2:
        end_year = st.number_input("End Year", min_value=1900, max_value=datetime.now().year + 1, value=default_end_year)

    no_dedupe = st.toggle("Disable De-duplication", value=False, help="Disable on-write de-duplication by DOI.", 
                      key="yr_no_dedupe")
    dedupe_existing = st.toggle("De-duplicate Existing Files", value=False, help="De-duplicate existing JSONL per-year before appending.")

    with st.expander("Advanced Options"):
        rows = st.number_input("Rows per Request", min_value=1, max_value=1000, value=default_rows, key="yr_rows")
        select = st.text_input("Fields to Select", default_select, key="yr_select")
        mailto = st.text_input("MailTo (Crossref 'polite' pool)", default_mailto, key="yr_mailto")
        restart_threshold = st.number_input("Restart Threshold", min_value=1000, value=default_restart) # This one was probably fine, but doesn't hurt
        app_name = st.text_input("App Name", default_app_name, key="yr_app_name")
        app_version = st.text_input("App Version", default_app_version, key="yr_app_version")
        app_url = st.text_input("App URL", default_app_url, key="yr_app_url")
        base_url = st.text_input("Crossref API URL", default_base_url, key="yr_base_url")

    if st.button("Run Yearly Dump", type="primary"):
        out_path = Path(out_dir)
        if not query:
            st.error("Please provide a query.")
            return
        if end_year < start_year:
            st.error("End year must be greater than or equal to start year.")
            return

        # Resolve out_dir relative to params file if it was provided and path is relative
        if params_file and not out_path.is_absolute():
            # This logic is complex in the CLI. For Streamlit, we'll assume
            # paths are relative to where the app is run, or absolute.
            st.info(f"Output directory '{out_dir}' will be created relative to the script's location if it doesn't exist.")
        
        out_path.mkdir(parents=True, exist_ok=True)

        kwargs = {
            "out_dir": out_path,
            "base_url": base_url,
            "query_bibliographic": query,
            "start_year": start_year,
            "end_year": end_year,
            "rows": rows,
            "mailto": mailto,
            "select": select,
            "restart_threshold": restart_threshold,
            "app_name": app_name,
            "app_version": app_version,
            "app_url": app_url,
            "dedupe_on_write": (not no_dedupe),
            "dedupe_existing": dedupe_existing,
        }
        
        with st.spinner(f"Running yearly dump from {start_year} to {end_year}..."):
            try:
                # The cursor_yearly_dump function likely prints its own progress.
                # In Streamlit, we can capture stdout, but for simplicity, 
                # we'll just show a spinner and success.
                st.write(f"Writing files to {out_path.resolve()}")
                cursor_yearly_dump(**kwargs)
                st.success(f"Yearly dump complete! Files saved in {out_dir}")
            except Exception as e:
                st.exception(e)

def ui_filter(mod):
    """UI for the 'filter' command."""
    regex_filter_crossref_from_params = getattr(mod, "regex_filter_crossref_from_params")
    regex_filter_crossref_jsonl = getattr(mod, "regex_filter_crossref_jsonl")

    st.header("Filter Dumps with Regex")
    st.write("Filter Crossref JSONL dumps using regex patterns from a params file.")
    
    params_file = st.file_uploader("Params JSON (with 'regex' key)", type=["json"], 
                                   help="This file is *required* and must contain a 'regex' section.")
    
    if not params_file:
        st.warning("Please upload a params file to define regex filters.")
        st.stop()
        
    params_data = _safe_load_json(params_file)
    regex_cfg = params_data.get("regex") if isinstance(params_data, dict) else None
    
    if not regex_cfg:
        st.error("Params file does not contain a 'regex' key or is invalid.")
        st.json(params_data, expanded=False)
        st.stop()
        
    st.success("Params file loaded. Regex config found:")
    st.json(regex_cfg, expanded=False)
    
    st.subheader("Filter Mode")
    mode = st.radio("Select mode:", ("Single File", "Directory"), horizontal=True)
    
    if mode == "Single File":
        in_file = st.text_input("Input Dump File (.jsonl)", "search/crossref_dumps/dump.jsonl")
        out_file = st.text_input("Output Filtered File (.jsonl)", "search/crossref_results/filtered.jsonl")
        
        if st.button("Run Filter on Single File", type="primary"):
            if not in_file or not out_file:
                st.error("Please provide both input and output file paths.")
                return
            
            in_path = Path(in_file)
            out_path = Path(out_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            
            if not in_path.is_file():
                st.error(f"Input file not found: {in_file}")
                return
                
            with st.spinner(f"Filtering {in_file}..."):
                try:
                    stats = regex_filter_crossref_jsonl(in_path, out_path, regex_cfg=regex_cfg)
                    st.success(f"Filtering complete! Saved to {out_file}")
                    st.text("Stats:")
                    st.code(str(stats), language="text")
                except Exception as e:
                    st.exception(e)
    
    else: # Directory Mode
        in_dir = st.text_input("Input Directory", "search/crossref_dumps")
        out_dir = st.text_input("Output Directory", "search/crossref_results")
        
        if st.button("Run Filter on Directory", type="primary"):
            if not in_dir or not out_dir:
                st.error("Please provide both input and output directories.")
                return
            
            in_path = Path(in_dir)
            out_path = Path(out_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            
            if not in_path.is_dir():
                st.error(f"Input directory not found: {in_dir}")
                return
                
            # The function `regex_filter_crossref_from_params` needs a *path*
            # to the params file. We must save our uploaded file temporarily.
            with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.json') as f:
                f.write(params_file.getvalue().decode('utf-8'))
                temp_params_path = Path(f.name)
            
            with st.spinner(f"Filtering all .jsonl files in {in_dir}..."):
                try:
                    stats_list = regex_filter_crossref_from_params(temp_params_path, in_path, out_path)
                    st.success(f"Directory filtering complete! Saved to {out_dir}")
                    st.text("Stats:")
                    for s in stats_list:
                        st.code(str(s), language="text")
                except Exception as e:
                    st.exception(e)
                finally:
                    os.unlink(temp_params_path) # Clean up temp file

def ui_dedupe(mod):
    """UI for the 'dedupe' command."""
    deduplicate_jsonl_path = getattr(mod, "deduplicate_jsonl_path")

    st.header("De-duplicate JSONL")
    st.write("De-duplicate a .jsonl file or all .jsonl files in a directory in-place.")
    
    path_to_dedupe = st.text_input("File or Directory Path", "search/crossref_dumps")
    
    if st.button("Run De-duplication", type="primary"):
        if not path_to_dedupe:
            st.error("Please provide a path.")
            return
            
        dedupe_path = Path(path_to_dedupe)
        if not dedupe_path.exists():
            st.error(f"Path not found: {path_to_dedupe}")
            return
        
        with st.spinner(f"De-duplicating {dedupe_path}..."):
            try:
                stats = deduplicate_jsonl_path(dedupe_path)
                st.success("De-duplication complete!")
                st.text("Stats:")
                for s in stats:
                    st.code(str(s), language="text")
            except Exception as e:
                st.exception(e)

# --- Main App ---

def main():
    st.set_page_config(page_title="Crossref Search UI", layout="wide")
    st.title("Crossref Search & Filter Tool 🧪")
    
    st.info("This app is a graphical interface for the `search_crossref.py` CLI script. "
            "It calls the underlying functions from `src/search_crossref.py`.")
    
    # Load the module
    mod = _load_module()
    
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Keyword Search", 
        "Yearly Dump", 
        "Filter Dumps", 
        "De-duplicate"
    ])
    
    with tab1:
        ui_keywords(mod)
        
    with tab2:
        ui_yearly(mod)
        
    with tab3:
        ui_filter(mod)
        
    with tab4:
        ui_dedupe(mod)

if __name__ == "__main__":
    main()