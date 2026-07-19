import os

from notifyhub.controller.server import server


def record_monitor(entity_key, name, status, summary="", category="service", metadata=None, provider=None):
    if not server._store:
        return
    plugin_id = provider or os.environ.get("PLUGIN_ID") or "plugin"
    server._store.update_monitor(plugin_id, f"{plugin_id}:{entity_key}", name, category, status, summary, metadata)


def record_event(event_type, entity_key, title, summary="", severity="info", domain="plugin", status="open", source=None):
    if not server._store:
        return
    plugin_id = source or os.environ.get("PLUGIN_ID") or "plugin"
    return server._store.record_event(domain, plugin_id, event_type, f"{plugin_id}:{entity_key}", severity, title, summary, status)
