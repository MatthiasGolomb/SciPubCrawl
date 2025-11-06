from pathlib import Path
import importlib.util
import sys

MODULE_FILE = Path(__file__).resolve().parents[1] / "src" / "alchemy_refactor" / "extract_markers.py"
spec = importlib.util.spec_from_file_location("alchemy_refactor.extract_markers", str(MODULE_FILE))
assert spec is not None and spec.loader is not None, f"Cannot load module from {MODULE_FILE}"
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod  # register before exec for dataclasses
spec.loader.exec_module(mod)  # type: ignore[attr-defined]


def test_extract_entities_from_md_basic():
    text = (
        "Electrolyte comprised of 1.0 M LiPF6 in EC:EMC with 10 wt% FEC additive.\n"
        "We also tested 0.5M LiTFSI in DME and 3 mol/L NaPF6 in propylene carbonate."
    )
    ents = mod.extract_entities_from_md(text)
    assert any(s.lower() == "lipf6" for s in ents["salts"])  # salt present
    assert any(s.lower() in {"ec", "emc", "fec"} for s in ents["solvents"])  # solvents/additives present
    assert any("m" in c.lower() or "%" in c for c in ents["concentrations"])  # concentrations found
