import logging
import threading
import time

from .channels import send


logger = logging.getLogger(__name__)


class DeliveryWorker:
    # A loop iteration normally finishes within a few seconds; a channel send can
    # take up to ~60s in the worst case (WeCom token + upload + send, each with a timeout).
    STALE_AFTER = 180

    def __init__(self, store):
        self.store = store
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="delivery-worker", daemon=True)
        self.last_beat = 0.0

    def start(self):
        self.last_beat = time.time()
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=10)

    def wake(self):
        self._wake.set()

    def health(self):
        alive = self._thread.is_alive()
        age = time.time() - self.last_beat if self.last_beat else None
        return {"alive": alive, "heartbeat_age": round(age, 1) if age is not None else None, "healthy": alive and age is not None and age < self.STALE_AFTER}

    def _idle(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()

    def _run(self):
        next_maintenance = 0
        while not self._stop.is_set():
            self.last_beat = time.time()
            try:
                item = self.store.claim_delivery()
            except Exception:
                logger.exception("delivery claim failed")
                self._idle(2)
                continue
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
                self._idle(0.5)
                continue
            try:
                self._deliver(item)
            except Exception:
                logger.exception("delivery bookkeeping failed delivery=%s", item.get("delivery_id"))
                self._idle(2)

    def _deliver(self, item):
        try:
            channel = self.store.channel(item["channel_name"])
            if not channel:
                raise KeyError(f"channel not found: {item['channel_name']}")
            if channel.get("enabled") is False:
                raise ValueError(f"channel disabled: {item['channel_name']}")
            send(channel, item)
        except Exception as exc:
            self.store.fail_delivery(item, exc)
            logger.error(
                "notification failed route=%s channel=%s: %s",
                item["route_id"],
                item["channel_name"],
                exc,
            )
            return
        # The message already left; a bookkeeping error must not resend it.
        for attempt in range(3):
            try:
                self.store.complete_delivery(item)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1)
        logger.info("notification sent", extra={"route_id": item["route_id"], "channel": item["channel_name"]})
