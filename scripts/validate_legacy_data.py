#!/usr/bin/env python3
import argparse
import ast
import json
import sqlite3
from pathlib import Path


SUPPORTED_CHANNELS = {
    "qywx", "bark", "telegram", "discord", "dingtalk",
    "pushdeer", "feishu", "serverchan3", "email", "webhook",
}
SUPPORTED_IMPORTS = {
    "notifyhub.common.response",
    "notifyhub.controller.schedule",
    "notifyhub.controller.server",
    "notifyhub.plugins.common",
    "notifyhub.plugins.components.qywx_Crypt.WXBizMsgCrypt",
    "notifyhub.plugins.utils",
}
REQUIRED_TABLES = {
    "cache", "notify_daily_summary", "notify_records", "plugins",
}


def validate(data_dir):
    data_dir = Path(data_dir)
    errors = []
    warnings = []
    config_path = data_dir / "conf" / "config.json"
    db_path = data_dir / "db" / "main.db"
    if not config_path.exists():
        return {"errors": ["conf/config.json missing"], "warnings": []}
    config = json.loads(config_path.read_text(encoding="utf-8"))
    channels = config.get("channels") or []
    routes = config.get("routes") or []
    channel_names = [x.get("name") for x in channels]
    if len(channel_names) != len(set(channel_names)):
        errors.append("duplicate channel names")
    unsupported = sorted({str(x.get("type") or "").lower() for x in channels} - SUPPORTED_CHANNELS)
    if unsupported:
        errors.append(f"unsupported channel types: {', '.join(unsupported)}")
    route_ids = [x.get("route_id") for x in routes]
    if len(route_ids) != len(set(route_ids)):
        errors.append("duplicate route ids")
    known_channels = set(channel_names)
    for route in routes:
        missing = set(route.get("channel_name") or []) - known_channels
        if missing:
            errors.append(f"route {route.get('route_id')} references missing channels: {sorted(missing)}")
    if not db_path.exists():
        errors.append("db/main.db missing")
    else:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            tables = {x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing_tables = REQUIRED_TABLES - tables
        if missing_tables:
            errors.append(f"database tables missing: {sorted(missing_tables)}")
    manifests = []
    unsupported_imports = set()
    for manifest_path in sorted((data_dir / "plugins").glob("*/manifest.json")):
        manifests.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        for source in manifest_path.parent.rglob("*.py"):
            try:
                tree = ast.parse(source.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError) as exc:
                errors.append(f"plugin source invalid: {source}: {exc}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("notifyhub"):
                    if node.module not in SUPPORTED_IMPORTS and not node.module.startswith("notifyhub.plugins."):
                        unsupported_imports.add(node.module)
    if unsupported_imports:
        warnings.append(f"plugin imports need review: {sorted(unsupported_imports)}")
    return {
        "channels": len(channels),
        "routes": len(routes),
        "plugins": len(manifests),
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir")
    args = parser.parse_args()
    result = validate(args.data_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result["errors"] else 0)


if __name__ == "__main__":
    main()
