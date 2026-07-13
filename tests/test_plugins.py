import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from notifyhub.builtin_plugins import register_builtin_plugins
from notifyhub.controller.server import Server
from notifyhub.plugin_loader import PluginLoader
from notifyhub.store import Store
from notifyhub.plugins.components.qywx_Crypt.WXBizMsgCrypt import WXBizMsgCrypt


def test_existing_plugin_import_surface_and_router(tmp_path, monkeypatch):
    plugin = tmp_path / "plugins" / "demo"
    plugin.mkdir(parents=True)
    (plugin / "manifest.json").write_text(json.dumps({"id": "demo", "name": "Demo", "path": "/demo"}))
    (plugin / "__init__.py").write_text("")
    (plugin / "event.py").write_text(
        "from fastapi import APIRouter\n"
        "from notifyhub.plugins.utils import get_plugin_config\n"
        "demo_router=APIRouter(prefix='/demo')\n"
        "@demo_router.get('/ping')\n"
        "def ping(): return get_plugin_config('demo')\n"
    )
    store = Store(tmp_path)
    store.save_plugin_config("demo", "Demo", {"ok": True})
    Server.configure(store)
    app = FastAPI()
    manifests = PluginLoader(app, store).load()
    assert manifests[0]["id"] == "demo"
    assert TestClient(app).get("/api/plugins/demo/ping").json() == {"ok": True}


def test_builtin_wecom_callback_verifier(tmp_path):
    store = Store(tmp_path)
    key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    store.save_plugin_config("qywx_receive", "企业微信回调工具", {"corpid": "corp", "token": "token", "encodingAesKey": key})
    app = FastAPI()
    assert len(register_builtin_plugins(app, store)) == 2
    crypt = WXBizMsgCrypt("token", key, "corp")
    code, envelope = crypt.EncryptMsg("verified", "nonce", "1700000000")
    assert code == 0
    import xml.etree.ElementTree as ET

    root = ET.fromstring(envelope)
    response = TestClient(app).get(
        "/api/plugins/qywx_receive/verify",
        params={
            "msg_signature": root.findtext("MsgSignature"),
            "timestamp": root.findtext("TimeStamp"),
            "nonce": root.findtext("Nonce"),
            "echostr": root.findtext("Encrypt"),
        },
    )
    assert response.text == "verified"
