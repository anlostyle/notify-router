from notifyhub.controller.server import server


def get_plugin_data(plugin_id):
    return server._store.get_plugin_data(plugin_id) if server._store else None


def get_plugin_config(plugin_id):
    return server._store.get_plugin_config(plugin_id) if server._store else {}
