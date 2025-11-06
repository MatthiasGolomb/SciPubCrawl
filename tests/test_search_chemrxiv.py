import json
import importlib.util
import sys
from pathlib import Path


def test_params_load_and_defaults(tmp_path: Path):
    # Arrange: create a minimal params JSON
    params_path = tmp_path / "chemrxiv_params.json"
    data = {
        "start_date": "2020-01-01",
        "end_date": "2020-03-01",
        "dump_dir": "chemrxiv_dumps",
        "result_dir": "chemrxiv_results",
        "sleep_seconds": 1.0,
        "query": [["a", "b"], ["c"]],
    }
    params_path.write_text(json.dumps(data))

    # Act: import and load
    # Load module by file location to avoid package install requirements
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "refactor_skeleton" / "src" / "alchemy_refactor" / "search_chemrxiv.py"
    spec = importlib.util.spec_from_file_location("alchemy_refactor.search_chemrxiv", str(module_path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    ChemRxivParams = getattr(mod, "ChemRxivParams")

    p = ChemRxivParams.load(params_path)

    # Assert: fields populated and dirs resolved relative to file
    assert p.start_date == "2020-01-01"
    assert p.end_date == "2020-03-01"
    assert Path(p.dump_dir).is_absolute()
    assert Path(p.result_dir).is_absolute()
    assert p.sleep_seconds == 1.0
    assert p.query == [["a", "b"], ["c"]]

    # Default query has at least two groups
    dq = ChemRxivParams.default_query()
    assert isinstance(dq, list) and len(dq) >= 2
