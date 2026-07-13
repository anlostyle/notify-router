import importlib.util
from pathlib import Path

from notifyhub.store import Store
from test_store import legacy_config


def load_validator():
    path = Path(__file__).parents[1] / "scripts" / "validate_legacy_data.py"
    spec = importlib.util.spec_from_file_location("validate_legacy_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_validator_accepts_compatible_volume(tmp_path):
    store = Store(tmp_path)
    store.save_config(legacy_config())
    result = load_validator().validate(tmp_path)
    assert result["errors"] == []
    assert result["channels"] == 1
    assert result["routes"] == 1
