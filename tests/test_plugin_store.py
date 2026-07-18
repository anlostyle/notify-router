import io
import json
import zipfile
from pathlib import Path

import pytest

from notifyhub.plugin_store import PluginStore
from notifyhub.store import Store


SOURCE = "https://plugins.example.com/index.json"
ARCHIVE = "https://plugins.example.com/bundle.zip"
REPOSITORY = Path(__file__).parents[1]


def bundle(version="1.0.0", extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "repo/plugins/demo/manifest.json",
            json.dumps({"id": "demo", "name": "Demo", "version": version}),
        )
        archive.writestr("repo/plugins/demo/__init__.py", "VALUE = 1\n")
        for name, content in extra or []:
            archive.writestr(name, content)
    return output.getvalue()


def index(version="1.0.0"):
    return json.dumps(
        {
            "schema_version": 1,
            "name": "Test plugins",
            "plugins": [
                {
                    "id": "demo",
                    "name": "Demo",
                    "version": version,
                    "archive_url": ARCHIVE,
                    "subdir": "repo/plugins/demo",
                }
            ],
        }
    ).encode()


def test_install_and_update_plugin_with_backup(tmp_path, monkeypatch):
    store = Store(tmp_path)
    manager = PluginStore(store)
    versions = {"current": "1.0.0"}

    monkeypatch.setattr("notifyhub.plugin_store._validate_remote_url", lambda url: url)
    monkeypatch.setattr(
        manager,
        "_fetch_bytes",
        lambda url, _limit: index(versions["current"]) if url == SOURCE else bundle(versions["current"]),
    )

    result = manager.install(SOURCE, "demo")
    assert result["restart_required"] is True
    assert result["backup"] is None
    assert json.loads((store.plugins_dir / "demo" / "manifest.json").read_text())["version"] == "1.0.0"

    versions["current"] = "1.1.0"
    catalog = manager.catalog([SOURCE])
    assert catalog["plugins"][0]["update_available"] is True
    result = manager.install(SOURCE, "demo")
    assert result["backup"]
    assert json.loads((store.plugins_dir / "demo" / "manifest.json").read_text())["version"] == "1.1.0"
    assert (tmp_path / "plugin-backups").is_dir()


def test_uninstall_moves_plugin_to_recoverable_backup(tmp_path):
    store = Store(tmp_path)
    plugin = store.plugins_dir / "demo"
    plugin.mkdir()
    (plugin / "manifest.json").write_text('{"id":"demo","version":"1"}')
    result = PluginStore(store).uninstall("demo")
    assert not plugin.exists()
    assert result["restart_required"] is True
    assert (tmp_path / "plugin-backups" / result["backup"].split("/")[-1] / "manifest.json").exists()


def test_archive_rejects_path_traversal(tmp_path):
    archive = bundle(extra=[("repo/plugins/demo/../escape.py", "bad")])
    with pytest.raises(ValueError, match="不安全路径"):
        PluginStore._extract_plugin(archive, "repo/plugins/demo", tmp_path)


def test_catalog_reports_source_failure_without_hiding_other_sources(tmp_path, monkeypatch):
    manager = PluginStore(Store(tmp_path))
    monkeypatch.setattr("notifyhub.plugin_store._validate_remote_url", lambda url: url)
    monkeypatch.setattr(manager, "_fetch_bytes", lambda url, _limit: index() if url == SOURCE else b"not-json")
    result = manager.catalog(["https://bad.example.com/index.json", SOURCE])
    assert result["sources"][0]["status"] == "error"
    assert result["sources"][1]["status"] == "ok"
    assert result["plugins"][0]["id"] == "demo"


def test_official_index_matches_plugin_manifests():
    catalog = json.loads((REPOSITORY / "plugin-store.json").read_text())
    indexed = {item["id"]: item for item in catalog["plugins"]}
    manifests = {}
    for path in (REPOSITORY / "plugins").glob("*/manifest.json"):
        manifest = json.loads(path.read_text())
        manifests[manifest["id"]] = (manifest, path.parent.name)
    assert catalog["schema_version"] == 1
    assert indexed.keys() == manifests.keys()
    for plugin_id, (manifest, directory) in manifests.items():
        assert indexed[plugin_id]["version"] == manifest["version"]
        assert indexed[plugin_id]["subdir"].endswith(f"/plugins/{directory}")
