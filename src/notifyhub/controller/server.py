import os
import signal


class Server:
    _instance = None
    _store = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def configure(cls, store):
        cls._store = store

    @property
    def notify_channels_config(self):
        return self._store.channels if self._store else []

    @property
    def notify_channels_name(self):
        return [x.get("name") for x in self.notify_channels_config]

    @property
    def notify_routers_config(self):
        return self._store.routes if self._store else []

    @property
    def notify_routers_name(self):
        return [x.get("route_name") for x in self.notify_routers_config]

    @property
    def router_list(self):
        return self.notify_routers_config

    @property
    def site_url(self):
        return self._store.site_url if self._store else ""

    def send_notify_by_channel(self, channel_name, title, content, push_img_url=None, push_link_url=None):
        if not self._store:
            raise RuntimeError("server not initialized")
        return self._store.enqueue_channel(channel_name, title, content, push_img_url, push_link_url)

    def send_notify_by_router(self, route_id, title, content, push_img_url=None, push_link_url=None):
        if not self._store:
            raise RuntimeError("server not initialized")
        return self._store.enqueue_router(route_id, title, content, push_img_url, push_link_url)

    def restart_app(self):
        os.kill(os.getpid(), signal.SIGTERM)


server = Server()
