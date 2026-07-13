import importlib.util
from pathlib import Path

from notifyhub.store import Store
from test_store import legacy_config


def load_migrator():
    path = Path(__file__).parents[1] / "scripts/migrate_legacy_data.py"
    spec = importlib.util.spec_from_file_location("migrate_legacy_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_atomic_legacy_migration_keeps_rollback_copy(tmp_path):
    source, destination = tmp_path / "old", tmp_path / "new"
    old = Store(source)
    old.save_config(legacy_config())
    Store(destination)
    result = load_migrator().migrate(source, destination, stamp="test")
    assert result["channels"] == 1
    assert Path(result["backup"]).name == "new.backup-test"
    assert Store(destination).routes[0]["route_id"] == "route_sms"
