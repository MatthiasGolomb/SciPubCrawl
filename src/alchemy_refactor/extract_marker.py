"""
Config-driven extractor that runs an LLM over Marker-produced Markdown and returns
structured Pydantic objects with schema validation (instructor MD_JSON mode).

Key features
- User-definable Pydantic schema loaded from a Python module
- Prompts loaded from a YAML/JSON file; select fewshot/oneshot/etc via config
- LLM provider/model controlled via config (routed by litellm); instructor enforces schema
- Saves outputs under results_dir/<instruct_{mode}_{provider}_{model}>/<paper>.{txt|json}

Dependencies at runtime
- pydantic, litellm, instructor; YAML support if you use YAML config/prompt files

This module avoids hard-coded keys. Configure providers via environment variables
per litellm (e.g., OPENAI_API_KEY, GEMINI_API_KEY, etc.).
"""
from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Type, Union, Set, cast
from enum import Enum
from typing import get_args, get_origin

try:  # optional YAML support
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

# pydantic is imported lazily inside load_schema to avoid hard runtime deps at import time


@dataclass
class SchemaConfig:
    type: str  # "python" | "json" (python supported; json reserved)
    module_path: Optional[str] = None
    root_model: Optional[str] = None
    root_container: Optional[str] = None  # e.g., "List"


@dataclass
class LLMConfig:
    provider: str
    model: str
    temperature: float = 0.0
    max_retries: int = 2
    timeout_s: int = 60


@dataclass
class PromptConfig:
    file: str
    mode: str  # fewshot | oneshot | simplest | custom key
    system_key: str = "system"
    user_key: str = "fewshot"


@dataclass
class RunConfig:
    glob: str = "**/*.md"
    max_files: Optional[int] = None
    sleep_s: float = 0.0
    on_parse_error: str = "save_raw"  # save_raw | skip | retry
    output_format: str = "txt"  # txt | json
    validation: str = "instructor"  # instructor | none


@dataclass
class Params:
    markdown_dir: str
    results_dir: str
    api_keys_file: Optional[str]
    schema: SchemaConfig
    llm: LLMConfig
    prompt: PromptConfig
    run: RunConfig


def _load_json_or_yaml(path: Path) -> Dict[str, Any]:
    if path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("pyyaml is required to load YAML files. Install pyyaml or use JSON.")
        return cast(Dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))
    return cast(Dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def load_params(params_path: Path) -> Params:
    data = _load_json_or_yaml(params_path)
    schema = data.get("schema", {})
    llm = data.get("llm", {})
    prompt = data.get("prompt", {})
    run = data.get("run", {})
    return Params(
        markdown_dir=data["markdown_dir"],
        results_dir=data["results_dir"],
        api_keys_file=data.get("api_keys_file"),
        schema=SchemaConfig(
            type=schema.get("type", "python"),
            module_path=schema.get("module_path"),
            root_model=schema.get("root_model"),
            root_container=schema.get("root_container"),
        ),
        llm=LLMConfig(
            provider=llm.get("provider", "openai"),
            model=llm.get("model", "gpt-4.1"),
            temperature=float(llm.get("temperature", 0.0)),
            max_retries=int(llm.get("max_retries", 2)),
            timeout_s=int(llm.get("timeout_s", 60)),
        ),
        prompt=PromptConfig(
            file=prompt.get("file", "prompts.yaml"),
            mode=prompt.get("mode", "fewshot"),
            system_key=prompt.get("system_key", "system"),
            user_key=prompt.get("user_key", "fewshot"),
        ),
        run=RunConfig(
            glob=run.get("glob", "**/*.md"),
            max_files=run.get("max_files"),
            sleep_s=float(run.get("sleep_s", 0.0)),
            on_parse_error=run.get("on_parse_error", "save_raw"),
            output_format=run.get("output_format", "txt"),
            validation=run.get("validation", "instructor"),
        ),
    )


def _import_module_from_path(module_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(module_path.stem, str(module_path))
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot import schema module from {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _rebuild_pydantic_models_in_module(module: Any) -> None:
    """Call model_rebuild() on all Pydantic BaseModel subclasses found in a module.

    This helps avoid Pydantic 'class-not-fully-defined' forward-ref issues when models
    reference each other or use Literals and are loaded dynamically.
    """
    try:
        import importlib
        pyd = importlib.import_module("pydantic")
        BaseModel = getattr(pyd, "BaseModel")
    except Exception:
        return

    for name in dir(module):
        obj = getattr(module, name)
        try:
            if isinstance(obj, type) and issubclass(obj, BaseModel):
                rebuild = getattr(obj, "model_rebuild", None)
                if callable(rebuild):
                    rebuild()
        except Exception:
            # Continue rebuilding others even if one fails
            pass


def load_schema(cfg: SchemaConfig) -> Tuple[Any, str]:
    """
    Returns (response_model_type, container) where response_model_type is either a BaseModel subclass
    or typing.List[BaseModel] depending on root_container.
    """
    if cfg.type != "python":
        raise NotImplementedError("Only schema.type='python' is currently supported.")
    if not cfg.module_path or not cfg.root_model:
        raise ValueError("schema.module_path and schema.root_model are required for python schemas")
    import importlib
    import importlib.util as importlib_util
    if importlib_util.find_spec("pydantic") is None:
        raise RuntimeError("pydantic is required to load the schema; install it and retry")
    pyd = importlib.import_module("pydantic")
    BaseModel = getattr(pyd, "BaseModel")
    mod = _import_module_from_path(Path(cfg.module_path))
    # Rebuild all models in the module defensively
    _rebuild_pydantic_models_in_module(mod)
    model = getattr(mod, cfg.root_model, None)
    if model is None:
        raise RuntimeError(f"Root model '{cfg.root_model}' not found in {cfg.module_path}")
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise RuntimeError("root_model must be a Pydantic BaseModel subclass")

    # Construct List[Model] if requested
    if (cfg.root_container or "").lower() == "list":
        from typing import List as _List

        return _List[model], "List"
    return model, "Single"



def _type_name(t: Any) -> str:
    try:
        if hasattr(t, "__name__"):
            return t.__name__  # type: ignore[attr-defined]
        return str(t).replace("typing.", "")
    except Exception:
        return str(t)


def _extract_model_types(tp: Any, base_model_cls: Any) -> List[type]:
    """Return BaseModel subclasses referenced by a typing annotation."""
    out: List[type] = []
    try:
        if isinstance(tp, type) and issubclass(tp, base_model_cls):
            return [tp]
    except Exception:
        pass
    origin = get_origin(tp)
    args = get_args(tp) or []
    if origin in (list, List, tuple, Tuple, set, Set, dict, Dict, Union, Optional):  # type: ignore[name-defined]
        for a in args:
            out.extend(_extract_model_types(a, base_model_cls))
        return out
    # handle Literal/Annotated by drilling into args if present
    for a in args:
        out.extend(_extract_model_types(a, base_model_cls))
    return out


def visualize_schema_from_params(params_path: Path, output_path: Path) -> str:
    """Render a diagram of the Pydantic schema.

    Behavior:
    - Prefer erdantic (erd.create(Model); diagram.draw("...svg")) when available.
    - If erdantic/graphviz pipeline fails, fall back to a DOT graph we generate.
    - Returns the actual path written.
    """
    params = load_params(params_path)
    # Resolve relative module path against params file
    base_dir = params_path.parent
    if params.schema.module_path and not os.path.isabs(params.schema.module_path):
        params.schema.module_path = str((base_dir / params.schema.module_path).resolve())

    response_model, container = load_schema(params.schema)
    # If List[T], take inner model
    try:
        model_cls = response_model.__args__[0] if container == "List" and hasattr(response_model, "__args__") else response_model
    except Exception:
        model_cls = response_model

    # Import pydantic BaseModel for checks
    import importlib
    pyd = importlib.import_module("pydantic")
    BaseModel = getattr(pyd, "BaseModel")

    # First, try ERD via erdantic
    out_path = Path(output_path)
    try:
        import erdantic as erd  # type: ignore
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # erdantic expects a BaseModel subclass
        if not (isinstance(model_cls, type) and issubclass(model_cls, BaseModel)):
            # If we somehow didn't resolve a concrete model class, use fallback
            raise RuntimeError("Unable to determine root Pydantic model for ERD")
    # Default to SVG if no suffix is provided
        if out_path.suffix.lower() not in {".svg", ".png", ".pdf"}:
            out_path = out_path.with_suffix(".svg")
        diagram = erd.create(model_cls)
        diagram.draw(str(out_path))
        return str(out_path)
    except Exception as e:
        # Fall through to DOT-based fallback and inform the user
        print(f"[extract] erdantic visualization failed: {e}; falling back to DOT/Graphviz fallback")

    # Traverse models graph (fallback path)
    to_visit: List[type] = []
    seen: set[type] = set()
    if isinstance(model_cls, type):
        to_visit.append(model_cls)

    nodes: Dict[str, Dict[str, str]] = {}  # model_name -> {field: type_str}
    edges: List[Tuple[str, str, str]] = []  # (src, dst, field)

    while to_visit:
        m = to_visit.pop(0)
        if m in seen:
            continue
        seen.add(m)
        m_name = m.__name__
        fields_map: Dict[str, str] = {}

        # pydantic v2: model_fields contains FieldInfo with .annotation
        model_fields = getattr(m, "model_fields", {})
        annotations = getattr(m, "__annotations__", {})
        for fname, finfo in model_fields.items():  # type: ignore[attr-defined]
            ann = getattr(finfo, "annotation", None) or annotations.get(fname)
            tname = _type_name(ann)
            fields_map[fname] = tname
            # enqueue nested BaseModel types
            for nested in _extract_model_types(ann, BaseModel):
                to_visit.append(nested)
                edges.append((m_name, nested.__name__, fname))

        nodes[m_name] = fields_map

    # Build DOT
    dot_lines: List[str] = [
        "digraph PydanticSchema {",
        "  rankdir=LR;",
        "  node [shape=record, fontsize=10, fontname=Helvetica];",
    ]
    for m_name, fields_map in nodes.items():
        fields_str = "|".join([f"{k}: {v}" for k, v in fields_map.items()])
        label = f"{{{m_name}|{fields_str}}}" if fields_str else f"{{{m_name}}}"
        dot_lines.append(f"  \"{m_name}\" [label='{label}'];")
    for src, dst, fname in edges:
        dot_lines.append(f"  \"{src}\" -> \"{dst}\" [label=\"{fname}\"];")
    dot_lines.append("}")
    dot_src = "\n".join(dot_lines)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = out_path.suffix.lower().lstrip(".")
    if fmt in {"png", "svg", "pdf"}:
        try:
            from graphviz import Digraph  # type: ignore
            graph = Digraph(format=fmt)
            graph.body.extend(dot_lines[1:-1])  # skip digraph header/footer
            # Render to the specified path (without suffix)
            base = out_path.with_suffix("")
            result_path = graph.render(filename=str(base), cleanup=True)
            return result_path
        except Exception:
            # Fallback to DOT
            dot_path = out_path.with_suffix(".dot")
            dot_path.write_text(dot_src, encoding="utf-8")
            return str(dot_path)
    else:
        # Write DOT by default
        if out_path.suffix.lower() != ".dot":
            out_path = out_path.with_suffix(".dot")
        out_path.write_text(dot_src, encoding="utf-8")
        return str(out_path)


def load_prompts(prompt_cfg: PromptConfig) -> Tuple[str, str]:
    path = Path(prompt_cfg.file)
    data = _load_json_or_yaml(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"Prompt file did not parse as a mapping: {path}")

    available_keys = list(data.keys())
    system_text = data.get(prompt_cfg.system_key, "")
    user_text = data.get(prompt_cfg.user_key, "")

    # Fallback for missing system text: try common default
    if not system_text and "system" in data:
        system_text = data.get("system", "")

    # Graceful fallback for missing user prompt key
    if not user_text:
        candidates = [
            prompt_cfg.user_key,
            getattr(prompt_cfg, "mode", None),
            "simpleprompt",
            "oneshot",
            "fewshot",
        ]
        candidates = [c for c in candidates if isinstance(c, str)]
        for key in candidates:
            if key in data and data[key]:
                user_text = data[key]
                break

    if not system_text or not user_text:
        raise RuntimeError(
            f"Prompt keys not found in {path}: system='{prompt_cfg.system_key}' user='{prompt_cfg.user_key}'. "
            f"Available keys: {sorted(available_keys)}"
        )

    return str(system_text), str(user_text)
def _load_api_keys_file(path: Path) -> None:
    """Load API keys from a file into environment variables.

    Supported formats:
    - .json: {"OPENAI_API_KEY": "...", "WILEY_TDM_API_TOKEN": "..."}
    - .yaml/.yml: same mapping as JSON
    - other: simple KEY=VALUE lines, ignoring blanks and lines starting with '#'
    """
    if not path.exists():
        return
    try:
        if path.suffix.lower() in {".json", ".yaml", ".yml"}:
            data = _load_json_or_yaml(path)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(k, str) and isinstance(v, (str, int)):
                        os.environ[k] = str(v)
            return
        # Fallback: KEY=VALUE format
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    os.environ[k] = v
    except Exception:
        # Don't crash on key loading; continue without keys
        pass



def _sanitize(s: str) -> str:
    return s.replace("/", "_").replace(" ", "_")


def _iter_markdown_files(root: Path, pattern: str) -> Iterable[Path]:
    yield from sorted(root.rglob(pattern))


def extract_markers(params_file: Path, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # litellm is required; instructor is used unconditionally for validation
    try:
        from litellm import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("litellm is required to run extraction") from e

    params = load_params(params_file)
    # Apply minimal overrides
    if overrides:
        if "markdown_dir" in overrides:
            params.markdown_dir = overrides["markdown_dir"]
        if "results_dir" in overrides:
            params.results_dir = overrides["results_dir"]
        if "api_keys_file" in overrides:
            params.api_keys_file = overrides["api_keys_file"]
        if "model" in overrides:
            params.llm.model = overrides["model"]
        if "provider" in overrides:
            params.llm.provider = overrides["provider"]
        if "prompt_mode" in overrides:
            params.prompt.mode = overrides["prompt_mode"]
            # Also switch the user_key to that mode if not explicitly set
            params.prompt.user_key = overrides.get("prompt_user_key", params.prompt.mode)
    # Schema must be provided via params (type='python')
    else:
        pass

    # Resolve any relative paths in schema/prompt/dirs against the params file directory
    base_dir = params_file.parent
    if params.schema.module_path and not os.path.isabs(params.schema.module_path):
        params.schema.module_path = str((base_dir / params.schema.module_path).resolve())
    if params.prompt.file and not os.path.isabs(params.prompt.file):
        params.prompt.file = str((base_dir / params.prompt.file).resolve())
    # Also resolve markdown_dir and results_dir for reproducible runs independent of CWD
    if params.markdown_dir and not os.path.isabs(params.markdown_dir):
        params.markdown_dir = str((base_dir / params.markdown_dir).resolve())
    if params.results_dir and not os.path.isabs(params.results_dir):
        params.results_dir = str((base_dir / params.results_dir).resolve())
    if params.api_keys_file and not os.path.isabs(params.api_keys_file):
        params.api_keys_file = str((base_dir / params.api_keys_file).resolve())

    # Load API keys from file if provided
    if params.api_keys_file:
        _load_api_keys_file(Path(params.api_keys_file))

    response_model, container = load_schema(params.schema)

    # Defensive: rebuild pydantic models to avoid forward-ref issues in some environments
    try:
        inner_model = response_model.__args__[0] if container == "List" and hasattr(response_model, "__args__") else response_model
        rebuild = getattr(inner_model, "model_rebuild", None)
        if callable(rebuild):
            rebuild()
    except Exception:
        pass
    system_text, user_text = load_prompts(params.prompt)

    # Build output path
    out_root = Path(params.results_dir) / (
        f"instruct_{_sanitize(params.prompt.mode)}_{_sanitize(params.llm.provider)}_{_sanitize(params.llm.model)}"
    )
    out_root.mkdir(parents=True, exist_ok=True)

    # Always use instructor in MD_JSON mode for structured output
    try:
        import instructor  # type: ignore
    except Exception as e:
        raise RuntimeError("instructor is required to run extraction with validation") from e

    client, client_mode = instructor.patch(OpenAI(), mode=instructor.Mode.MD_JSON), "MD_JSON"
    from typing import cast as _cast
    client_instructor = _cast(Any, client)

    # --- Model self-identification ping (untraced quick check) ---
    try:
        raw_client = OpenAI()
        ping = raw_client.chat.completions.create(
            model=params.llm.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {
                    "role": "user",
                    "content": "Reply with the exact name of the model you are running on. Output only the model name and nothing else.",
                },
            ],
        )
        model_reported = None
        # litellm/OpenAI returns choices[0].message.content
        try:
            model_reported = ping.choices[0].message.get("content") if hasattr(ping.choices[0], "message") else None
        except Exception:
            pass
        if not model_reported:
            try:
                # Some clients expose .choices[0].message.content as attribute
                model_reported = getattr(getattr(ping.choices[0], "message", object()), "content", None)
            except Exception:
                model_reported = None
        if isinstance(model_reported, str):
            print(f"[extract] Model reports: {model_reported.strip()}")
        else:
            print(f"[extract] Model ping completed (could not parse content); configured model: {params.llm.model}")
    except Exception as _e:
        # Non-fatal; continue
        print(f"[extract] Model ping failed: {_e}")

    processed = 0
    failed = 0
    skipped = 0

    import time

    md_root = Path(params.markdown_dir)
    files = list(_iter_markdown_files(md_root, params.run.glob))
    if params.run.max_files is not None:
        files = files[: int(params.run.max_files)]

    for md_path in files:
        if not md_path.is_file() or not md_path.suffix.lower().endswith(".md"):
            continue
        doc_name = md_path.stem
        try:
            rel = md_path.relative_to(md_root)
        except Exception:
            rel = md_path
        print(f"[extract] Analyzing: {rel}")
        try:
            document = md_path.read_text(encoding="utf-8")
        except Exception:
            skipped += 1
            continue

        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
            {"role": "user", "content": document},
        ]

        out_file = out_root / f"{doc_name}.{params.run.output_format}"

        try:
            # Instructor path only
            completion = client_instructor.chat.completions.create(
                model=params.llm.model,
                messages=messages,
                temperature=params.llm.temperature,
                max_retries=params.llm.max_retries,
                response_model=response_model,  # Pydantic-enforced structure
            )
            # Normalize to list of dicts for saving
            if container == "List":
                items = completion  # already list of BaseModel
                data = [item.model_dump() for item in items]
            else:
                item = completion
                data = item.model_dump()

            text = json.dumps(data, indent=2)
            out_file.write_text(text, encoding="utf-8")
            processed += 1
        except Exception as e:
            failed += 1
            # No built-in fallbacks here; record the error

            if failed > 0:  # still failed after any fallback
                policy = (params.run.on_parse_error or "save_raw").lower()
                if policy == "save_raw":
                    # Save an error marker alongside
                    err_path = out_root / f"{doc_name}.error.txt"
                    extra = ""
                    err_path.write_text(
                        f"Error: {e}\nClientMode: {client_mode}{extra}\n",
                        encoding="utf-8",
                    )
                elif policy == "retry":
                    try:
                        completion = client_instructor.chat.completions.create(
                            model=params.llm.model,
                            messages=messages,
                            temperature=params.llm.temperature,
                            max_retries=max(1, params.llm.max_retries),
                            response_model=response_model,
                        )
                        if container == "List":
                            items = completion
                            data = [item.model_dump() for item in items]
                        else:
                            item = completion
                            data = item.model_dump()
                        text = json.dumps(data, indent=2)
                        out_file.write_text(text, encoding="utf-8")
                        processed += 1
                        failed -= 1  # retried successfully
                    except Exception:
                        pass
            # else skip silently

        if params.run.sleep_s and params.run.sleep_s > 0:
            time.sleep(params.run.sleep_s)

    return {
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "output_root": str(out_root),
        "provider": params.llm.provider,
        "model": params.llm.model,
        "mode": params.prompt.mode,
    }
