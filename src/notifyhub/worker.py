import logging
import threading
import time

from .channels import send


logger = logging.getLogger(__name__)


class DeliveryWorker:
    def __init__(self, store):
        self.store = store
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="delivery-worker", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=10)

    def wake(self):
        self._stop.wait(0)

    def _run(self):
        next_maintenance = 0
        while not self._stop.is_set():
            item = self.store.claim_delivery()
            if not item:
                if time.monotonic() >= next_maintenance:
                    try:
                        result = self.store.maintain()
                        logger.info(
                            "maintenance complete backup=%s records=%s outbox=%s summaries=%s",
                            result["backup"],
                            result["records"],
                            result["outbox"],
                            result["summaries"],
                        )
                    except Exception:
                        logger.exception("maintenance failed")
                    next_maintenance = time.monotonic() + 21600
                self._stop.wait(0.5)
                continue
            try:
                channel = self.store.channel(item["channel_name"])
                if not channel:
                    raise KeyError(f"channel not found: {item['channel_name']}")
                if channel.get("enabled") is False:
                    raise ValueError(f"channel disabled: {item['channel_name']}")
                send(channel, item)
                self.store.complete_delivery(item)
                logger.info("notification sent", extra={"route_id": item["route_id"], "channel": item["channel_name"]})
            except Exception as exc:
                self.store.fail_delivery(item, exc)
                logger.error(
                    "notification failed route=%s channel=%s: %s",
                    item["route_id"],
                    item["channel_name"],
                    exc,
                )
