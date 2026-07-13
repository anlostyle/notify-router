import ast
import json
import re
import shutil
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2.sandbox import SandboxedEnvironment


_jinja = SandboxedEnvironment(autoescape=False)


def redact_secret_text(value):
    text = str(value or "")
    text = re.sub(r"(?i)(/bot)[^/\s\"']+", rf"\1••••••", text)
    text = re.sub(
        r"(?i)(access_token|corpsecret|secret|api_key|apikey|token|password|key)=([^&\s\"']+)",
        r"\1=••••••",
        text,
    )
    return re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s\"']+", r"\1••••••", text)

def localnow():
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")


def enabled(value):
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


class Store:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.conf_dir = self.data_dir / "conf"
        self.db_dir = self.data_dir / "db"
        self.plugins_dir = self.data_dir / "plugins"
        self.config_path = self.conf_dir / "config.json"
        self.templates_path = self.conf_dir / "notify_template.json"
        self.db_path = self.db_dir / "main.db"
        self._config_lock = threading.Lock()
        self._prepare_files()
        self._prepare_db()

    def _prepare_files(self):
        self.conf_dir.mkdir(parents=True, exist_ok=True)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.config_path.write_text(
                json.dumps(
                    {
                        "app": {
                            "app_name": "Notify Router",
                            "site_url": "",
                            "record_retention_days": 90,
                        },
                        "channels": [],
                        "routes": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        if not self.templates_path.exists():
            self.templates_path.write_text('{"template": []}\n', encoding="utf-8")
        self.config_path.chmod(0o600)
        self.templates_path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _prepare_db(self):
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    id INTEGER PRIMARY KEY,
                    namespace VARCHAR(255) NOT NULL,
                    "key" VARCHAR(255) NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notify_daily_summary (
                    id INTEGER PRIMARY KEY,
                    date VARCHAR(10) NOT NULL,
                    route_id VARCHAR(255) NOT NULL,
                    route_name VARCHAR(255) NOT NULL,
                    channel_name VARCHAR(255) NOT NULL,
                    success_count INTEGER NOT NULL,
                    fail_count INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    CONSTRAINT uq_summary_date_route_channel UNIQUE (date, route_id, channel_name)
                );
                CREATE TABLE IF NOT EXISTS notify_records (
                    id INTEGER PRIMARY KEY,
                    route_id VARCHAR(255) NOT NULL,
                    route_name VARCHAR(255) NOT NULL,
                    channel_name VARCHAR(255) NOT NULL,
                    msg_title VARCHAR(255) NOT NULL,
                    msg_content TEXT NOT NULL,
                    push_time DATETIME NOT NULL,
                    status INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plugins (
                    id INTEGER PRIMARY KEY,
                    plugin_id VARCHAR(255) NOT NULL UNIQUE,
                    plugin_name VARCHAR(255) NOT NULL UNIQUE,
                    config VARCHAR(255) NOT NULL,
                    status INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY,
                    route_id TEXT NOT NULL,
                    route_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    push_img_url TEXT,
                    push_link_url TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    outbox_id TEXT NOT NULL REFERENCES outbox(id) ON DELETE CASCADE,
                    channel_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(outbox_id, channel_name)
                );
                CREATE INDEX IF NOT EXISTS idx_deliveries_ready
                    ON deliveries(status, next_attempt_at, id);
                """
            )
            db.execute(
                "UPDATE deliveries SET status='retry', next_attempt_at=? WHERE status='processing'",
                (time.time(),),
            )
        self.db_path.chmod(0o600)

    @property
    def config(self):
        with self._config_lock:
            return json.loads(self.config_path.read_text(encoding="utf-8"))

    def save_config(self, config):
        if not isinstance(config, dict) or not isinstance(config.get("app"), dict) or not isinstance(config.get("channels"), list) or not isinstance(config.get("routes"), list):
            raise ValueError("config must contain app, channels and routes")
        channel_names = [x.get("name") for x in config["channels"] if isinstance(x, dict)]
        route_ids = [x.get("route_id") for x in config["routes"] if isinstance(x, dict)]
        if len(channel_names) != len(config["channels"]) or None in channel_names or len(channel_names) != len(set(channel_names)):
            raise ValueError("channel names must be present and unique")
        if len(route_ids) != len(config["routes"]) or None in route_ids or len(route_ids) != len(set(route_ids)):
            raise ValueError("route ids must be present and unique")
        missing = {name for route in config["routes"] for name in (route.get("channel_name") or []) if name not in set(channel_names)}
        if missing:
            raise ValueError(f"routes reference missing channels: {sorted(missing)}")
        with self._config_lock:
            temp = self.config_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            shutil.copy2(self.config_path, self.config_path.with_suffix(".json.bak"))
            temp.replace(self.config_path)

    @property
    def channels(self):
        return self.config.get("channels", [])

    @property
    def routes(self):
        return self.config.get("routes", [])

    @property
    def templates(self):
        return json.loads(self.templates_path.read_text(encoding="utf-8")).get("template", [])

    def save_templates(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("template"), list):
            raise ValueError("templates must contain a template list")
        names = [x.get("name") for x in payload["template"] if isinstance(x, dict)]
        if len(names) != len(payload["template"]) or None in names or len(names) != len(set(names)):
            raise ValueError("template names must be present and unique")
        with self._config_lock:
            temp = self.templates_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            shutil.copy2(self.templates_path, self.templates_path.with_suffix(".json.bak"))
            temp.replace(self.templates_path)

    def render_event(self, route, template_type, context):
        bound = set(route.get("bind_template") or [])
        template = next((x for x in self.templates if x.get("type") == template_type and x.get("name") in bound), None)
        if not template:
            raise ValueError(f"route has no bound template for {template_type}")
        return (
            _jinja.from_string(str(template.get("title") or "")).render(context),
            _jinja.from_string(str(template.get("content") or "")).render(context),
        )

    @property
    def site_url(self):
        return str(self.config.get("app", {}).get("site_url") or "")

    def channel(self, name):
        return next((x for x in self.channels if x.get("name") == name), None)

    def route(self, route_id):
        return next((x for x in self.routes if x.get("route_id") == route_id), None)

    def enqueue_router(self, route_id, title, content, push_img_url=None, push_link_url=None):
        route = self.route(route_id)
        if not route:
            raise KeyError(f"route not found: {route_id}")
        if not enabled(route.get("active", True)):
            raise ValueError(f"route disabled: {route_id}")
        channel_names = list(dict.fromkeys(route.get("channel_name") or []))
        if not channel_names:
            raise ValueError(f"route has no channels: {route_id}")
        return self._enqueue(
            route_id,
            str(route.get("route_name") or route_id),
            channel_names,
            title,
            content,
            push_img_url or route.get("push_img") or None,
            push_link_url,
        )

    def enqueue_channel(self, channel_name, title, content, push_img_url=None, push_link_url=None):
        if not self.channel(channel_name):
            raise KeyError(f"channel not found: {channel_name}")
        return self._enqueue(
            f"@channel:{channel_name}",
            channel_name,
            [channel_name],
            title,
            content,
            push_img_url,
            push_link_url,
        )

    def _enqueue(self, route_id, route_name, channel_names, title, content, push_img_url, push_link_url):
        outbox_id = uuid.uuid4().hex
        now = localnow()
        with self.connect() as db:
            db.execute(
                """INSERT INTO outbox
                   (id, route_id, route_name, title, content, push_img_url, push_link_url, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (outbox_id, route_id, route_name, str(title), str(content), push_img_url, push_link_url, now, now),
            )
            db.executemany(
                """INSERT INTO deliveries
                   (outbox_id, channel_name, status, attempts, next_attempt_at, created_at, updated_at)
                   VALUES (?, ?, 'pending', 0, ?, ?, ?)""",
                [(outbox_id, name, time.time(), now, now) for name in channel_names],
            )
        return outbox_id

    def claim_delivery(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT d.id delivery_id, d.channel_name, d.attempts,
                          o.id outbox_id, o.route_id, o.route_name, o.title, o.content,
                          o.push_img_url, o.push_link_url
                   FROM deliveries d JOIN outbox o ON o.id=d.outbox_id
                   WHERE d.status IN ('pending','retry') AND d.next_attempt_at<=?
                   ORDER BY d.id LIMIT 1""",
                (time.time(),),
            ).fetchone()
            if not row:
                db.commit()
                return None
            db.execute(
                "UPDATE deliveries SET status='processing', updated_at=? WHERE id=?",
                (localnow(), row["delivery_id"]),
            )
            db.commit()
            return dict(row)
        finally:
            db.close()

    def complete_delivery(self, item):
        now = localnow()
        with self.connect() as db:
            db.execute(
                "UPDATE deliveries SET status='sent', attempts=attempts+1, last_error='', updated_at=? WHERE id=?",
                (now, item["delivery_id"]),
            )
            self._record(db, item, 1, now)
            self._finish_outbox(db, item["outbox_id"], now)

    def fail_delivery(self, item, error):
        attempts = int(item["attempts"]) + 1
        now = localnow()
        retry_delays = (10, 60, 300, 1800)
        final = attempts > len(retry_delays)
        with self.connect() as db:
            db.execute(
                """UPDATE deliveries
                   SET status=?, attempts=?, next_attempt_at=?, last_error=?, updated_at=?
                   WHERE id=?""",
                (
                    "failed" if final else "retry",
                    attempts,
                    time.time() if final else time.time() + retry_delays[attempts - 1],
                    redact_secret_text(error)[:2000],
                    now,
                    item["delivery_id"],
                ),
            )
            if final:
                self._record(db, item, 0, now)
                self._finish_outbox(db, item["outbox_id"], now)

    def _record(self, db, item, status, now):
        db.execute(
            """INSERT INTO notify_records
               (route_id, route_name, channel_name, msg_title, msg_content, push_time, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["route_id"],
                item["route_name"],
                item["channel_name"],
                item["title"],
                item["content"],
                now,
                status,
                now,
                now,
            ),
        )
        day = now[:10]
        db.execute(
            """INSERT INTO notify_daily_summary
               (date, route_id, route_name, channel_name, success_count, fail_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date, route_id, channel_name) DO UPDATE SET
                 success_count=success_count+excluded.success_count,
                 fail_count=fail_count+excluded.fail_count,
                 updated_at=excluded.updated_at""",
            (
                day,
                item["route_id"],
                item["route_name"],
                item["channel_name"],
                1 if status else 0,
                0 if status else 1,
                now,
                now,
            ),
        )

    def _finish_outbox(self, db, outbox_id, now):
        states = [x[0] for x in db.execute("SELECT status FROM deliveries WHERE outbox_id=?", (outbox_id,))]
        if any(x in {"pending", "retry", "processing"} for x in states):
            return
        status = "sent" if all(x == "sent" for x in states) else "failed"
        db.execute("UPDATE outbox SET status=?, updated_at=? WHERE id=?", (status, now, outbox_id))

    def recent_records(self, limit=100):
        with self.connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM notify_records ORDER BY id DESC LIMIT ?", (limit,))]

    def dashboard_stats(self, days=14):
        with self.connect() as db:
            totals = db.execute(
                "SELECT COALESCE(SUM(success_count), 0), COALESCE(SUM(fail_count), 0) FROM notify_daily_summary"
            ).fetchone()
            today = db.execute(
                "SELECT COALESCE(SUM(success_count), 0), COALESCE(SUM(fail_count), 0) FROM notify_daily_summary WHERE date=?",
                (localnow()[:10],),
            ).fetchone()
            queue = {
                row["status"]: row["count"]
                for row in db.execute("SELECT status, COUNT(*) count FROM deliveries GROUP BY status")
            }
            trend = [
                dict(row)
                for row in db.execute(
                    """SELECT date, SUM(success_count) success, SUM(fail_count) failed
                       FROM notify_daily_summary GROUP BY date ORDER BY date DESC LIMIT ?""",
                    (days,),
                )
            ][::-1]
            latest_channels = [
                dict(row)
                for row in db.execute(
                    """SELECT d.channel_name, d.status, d.last_error, d.updated_at
                       FROM deliveries d
                       JOIN (SELECT channel_name, MAX(id) id FROM deliveries GROUP BY channel_name) latest
                         ON latest.id=d.id
                       ORDER BY d.channel_name"""
                )
            ]
        success, failed = int(totals[0]), int(totals[1])
        return {
            "total": success + failed,
            "success": success,
            "failed": failed,
            "success_rate": round(success * 100 / (success + failed), 1) if success + failed else 100.0,
            "today": {"success": int(today[0]), "failed": int(today[1])},
            "queue": queue,
            "trend": trend,
            "channel_states": latest_channels,
        }

    def delivery_status(self, limit=100, status=None):
        where = "WHERE d.status=?" if status else ""
        params = (status, limit) if status else (limit,)
        with self.connect() as db:
            return [
                {**dict(x), "last_error": redact_secret_text(x["last_error"])}
                for x in db.execute(
                    f"""SELECT d.*, o.route_id, o.route_name, o.title, o.content,
                               o.push_img_url, o.push_link_url, o.created_at outbox_created_at
                       FROM deliveries d JOIN outbox o ON o.id=d.outbox_id
                       {where} ORDER BY d.id DESC LIMIT ?""",
                    params,
                )
            ]

    def retry_failed(self, delivery_id):
        with self.connect() as db:
            result = db.execute(
                "UPDATE deliveries SET status='retry', next_attempt_at=?, updated_at=? WHERE id=? AND status='failed'",
                (time.time(), localnow(), delivery_id),
            )
            return result.rowcount == 1

    def get_plugin_data(self, plugin_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM plugins WHERE plugin_id=?", (plugin_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["config"] = json.loads(data.get("config") or "{}")
        except (json.JSONDecodeError, TypeError):
            try:
                data["config"] = ast.literal_eval(data.get("config") or "{}")
            except (ValueError, SyntaxError):
                data["config"] = {}
        if not isinstance(data["config"], dict):
            data["config"] = {}
        return data

    def get_plugin_config(self, plugin_id):
        data = self.get_plugin_data(plugin_id)
        return dict(data.get("config") or {}) if data else {}

    def save_plugin_config(self, plugin_id, plugin_name, config, status=1):
        now = localnow()
        payload = repr(config or {})
        with self.connect() as db:
            db.execute(
                """INSERT INTO plugins
                   (plugin_id, plugin_name, config, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(plugin_id) DO UPDATE SET
                     plugin_name=excluded.plugin_name,
                     config=excluded.config,
                     status=excluded.status,
                     updated_at=excluded.updated_at""",
                (plugin_id, plugin_name, payload, int(bool(status)), now, now),
            )
