import json
import re
from pathlib import Path


PLUGIN_DIR = Path(__file__).parents[1] / "plugins"


def test_release_plugins_compile_and_have_no_embedded_secrets():
    for path in PLUGIN_DIR.rglob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in PLUGIN_DIR.rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".html", ".txt", ".md"}
    )
    assert "andp.cc" not in text
    assert not re.search(r"eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{30,}", text)
    assert not list(PLUGIN_DIR.rglob("plugin_state.json"))


def test_release_plugin_secret_defaults_are_empty():
    for path in PLUGIN_DIR.glob("*/manifest.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for field in manifest.get("configField", []):
            name = str(field.get("fieldName") or "").lower()
            if any(part in name for part in ("token", "secret", "password", "api_key", "apikey", "chatid")):
                assert field.get("defaultValue", "") == "", f"{path}: {name}"
