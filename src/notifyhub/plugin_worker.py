import argparse
import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException

from .controller.schedule import start_scheduler, stop_scheduler
from .controller.server import Server
from .plugin_loader import PluginLoader
from .plugins.common import run_after_setup_hooks
from .store import Store, enabled


logger = logging.getLogger("notifyhub.plugin-worker")


def create_worker(plugin_dir, data_dir):
    plugin_dir = Path(plugin_dir)
    data_dir = Path(data_dir)
    plugin_id = plugin_dir.name
    plugin_data = data_dir / "plugin-data" / plugin_id
    plugin_data.mkdir(parents=True, exist_ok=True)
    manifest_data = json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
    legacy_state_paths = {"state.json", "plugin_state.json"}
    for relative in legacy_state_paths | set(manifest_data.get("preserve") or []):
        source = plugin_dir / relative
        destination = plugin_data / relative
        if source.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    os.environ["WORKDIR"] = str(data_dir)
    os.environ["PLUGIN_ID"] = plugin_id
    os.environ["PLUGIN_DATA_DIR"] = str(plugin_data)
    store = Store(data_dir)
    Server.configure(store)
    runtime = data_dir / "plugin-runtime" / plugin_id / "python"
    loader = PluginLoader(None, store)
    app = FastAPI(title=f"Plugin Worker: {plugin_id}")
    loader.app = app
    manifest = loader.load_one(plugin_dir, runtime)
    if not manifest:
        raise RuntimeError(f"plugin is disabled: {plugin_id}")
    state = {"active": False}

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if state["active"]:
            stop_scheduler()

    app.router.lifespan_context = lifespan

    @app.get("/__health")
    def health():
        return {"status": "ok", "id": manifest["id"], "version": str(manifest.get("version") or ""), "active": state["active"]}

    @app.post("/__activate")
    async def activate():
        if not state["active"] and enabled(os.environ.get("PLUGIN_TASKS_ENABLED", "1")):
            start_scheduler()
            await run_after_setup_hooks(logger)
        state["active"] = True
        return {"status": "ok", "active": True}

    @app.post("/__deactivate")
    def deactivate():
        if state["active"]:
            stop_scheduler()
        state["active"] = False
        return {"status": "ok", "active": False}

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--data-dir", default=os.environ.get("WORKDIR", "/data"))
    args = parser.parse_args()
    socket = Path(args.socket)
    socket.parent.mkdir(parents=True, exist_ok=True)
    socket.unlink(missing_ok=True)
    uvicorn.run(create_worker(args.plugin_dir, args.data_dir), uds=str(socket), access_log=False, log_level=os.environ.get("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
