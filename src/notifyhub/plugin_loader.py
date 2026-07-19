import hashlib
import importlib
import importlib.util
import json
import logging
import os
import pkgutil
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

from fastapi import APIRouter
from fastapi.staticfiles import StaticFiles


logger = logging.getLogger(__name__)


class PluginLoader:
    def __init__(self, app, store):
        self.app = app
        self.store = store
        self.manifests = []

    def load(self):
        for directory in sorted(self.store.plugins_dir.iterdir()):
            if directory.name.startswith(".") or not directory.is_dir() or not (directory / "manifest.json").exists():
                continue
            try:
                self.load_one(directory)
            except Exception:
                logger.exception("plugin load failed: %s", directory.name)
        return self.manifests

    def load_one(self, directory, target=None):
        target = Path(target or self.store.data_dir / "python")
        target.mkdir(parents=True, exist_ok=True)
        if str(target) not in sys.path:
            sys.path.insert(0, str(target))
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        for cache in directory.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        plugin_id = str(manifest.get("id") or directory.name)
        data = self.store.get_plugin_data(plugin_id)
        if data and not data.get("status"):
            logger.info("plugin disabled: %s", plugin_id)
            return None
        self._install_requirements(directory, target)
        package_name = "_notifyhub_plugin_" + re.sub(r"\W+", "_", plugin_id)
        init_file = directory / "__init__.py"
        if init_file.exists():
            spec = importlib.util.spec_from_file_location(
                package_name,
                init_file,
                submodule_search_locations=[str(directory)],
            )
            package = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = package
            spec.loader.exec_module(package)
        else:
            package = types.ModuleType(package_name)
            package.__path__ = [str(directory)]
            sys.modules[package_name] = package
        modules = [package]
        for info in pkgutil.walk_packages([str(directory)], prefix=package_name + "."):
            modules.append(importlib.import_module(info.name))
        seen = set()
        for module in modules:
            for name, value in vars(module).items():
                if name.endswith("router") and isinstance(value, APIRouter) and id(value) not in seen:
                    self.app.include_router(value, prefix="/api/plugins")
                    seen.add(id(value))
                    logger.info("plugin route loaded: %s.%s", plugin_id, name)
        frontend = directory / "frontend"
        if frontend.is_dir():
            self.app.mount(
                f"/api/plugins/{plugin_id}/frontend",
                StaticFiles(directory=frontend, html=True),
                name=f"plugin-{plugin_id}",
            )
        self.manifests.append(manifest)
        return manifest

    def _install_requirements(self, directory, target):
        requirements = directory / "requirements.txt"
        if not requirements.exists() or os.environ.get("INSTALL_PLUGIN_REQUIREMENTS", "1") == "0":
            return
        digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
        marker = target / f".{directory.name}-{digest}.installed"
        if marker.exists():
            return
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--target", str(target), "-r", str(requirements)],
            check=True,
        )
        for old in target.glob(f".{directory.name}-*.installed"):
            old.unlink()
        marker.touch()
