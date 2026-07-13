#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path


REQUIRED_TABLES = {"cache", "notify_daily_summary", "notify_records", "plugins"}


def validate_source(source):
    source = Path(source)
    config = json.loads((source / "conf/config.json").read_text(encoding="utf-8"))
    if not all(key in config for key in ("app", "channels", "routes")):
        raise ValueError("legacy config is incomplete")
    with sqlite3.connect(f"file:{source / 'db/main.db'}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("legacy database integrity check failed")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if missing := REQUIRED_TABLES - tables:
        raise ValueError(f"legacy database tables missing: {sorted(missing)}")
    return {"channels": len(config["channels"]), "routes": len(config["routes"])}


def migrate(source, destination, stamp=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination in source.parents or source in destination.parents:
        raise ValueError("source and destination must be separate directories")
    result = validate_source(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{destination.name}.migrate-", dir=destination.parent))
    backup = destination.with_name(f"{destination.name}.backup-{stamp or datetime.now().strftime('%Y%m%d-%H%M%S')}")
    moved = False
    try:
        def ignore(path, names):
            return {"main.db", "main.db-wal", "main.db-shm"} & set(names) if Path(path).resolve() == source / "db" else set()

        shutil.copytree(source, temp, dirs_exist_ok=True, symlinks=True, ignore=ignore)
        (temp / "db").mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(f"file:{source / 'db/main.db'}?mode=ro", uri=True) as src, sqlite3.connect(temp / "db/main.db") as dst:
            src.backup(dst)
        (temp / "conf/config.json").chmod(0o600)
        (temp / "db/main.db").chmod(0o600)
        validate_source(temp)
        if destination.exists():
            os.replace(destination, backup)
            moved = True
        os.replace(temp, destination)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        if moved and not destination.exists():
            os.replace(backup, destination)
        raise
    result["plugins"] = len(list((destination / "plugins").glob("*/manifest.json")))
    result["backup"] = str(backup) if moved else None
    return result


def main():
    parser = argparse.ArgumentParser(description="Atomically replace a stopped Notify Router data directory with a stopped legacy NotifyHub volume")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--confirm-stopped", action="store_true", help="confirm both old and new containers are stopped")
    args = parser.parse_args()
    if args.check:
        result = validate_source(args.source)
    elif not args.confirm_stopped:
        parser.error("--confirm-stopped is required for migration")
    else:
        result = migrate(args.source, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
