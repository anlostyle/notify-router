import ast
import json
import re
import shutil
import sqlite3
import tarfile
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2.sandbox import SandboxedEnvironment


_jinja = SandboxedEnvironment(autoescape=False)


def default_templates():
    try:
        raw = files("notifyhub").joinpath("emby_templates.json").read_text(encoding="utf-8")
        value = json.loads(raw)
        templates = value.get("template", [])
        return templates if isinstance(templates, list) else []
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []


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
            self.templates_path.write_text(
                json.dumps({"template": default_templates()}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
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
                CREATE TABLE IF NOT EXISTS platform_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    entity_key TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_platform_events_domain_created
                    ON platform_events(domain, id DESC);
                CREATE TABLE IF NOT EXISTS monitors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    entity_key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    last_checked_at TEXT NOT NULL,
                    last_changed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS platform_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    plugin_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    last_status TEXT NOT NULL DEFAULT 'never',
                    last_started_at TEXT,
                    last_finished_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id, id DESC);
                """
            )
            db.execute(
                "UPDATE deliveries SET status='retry', next_attempt_at=? WHERE status='processing'",
                (time.time(),),
            )
            db.execute(
                """UPDATE monitors SET status='healthy'
                   WHERE provider='pve' AND status='error' AND
                     (lower(summary) LIKE '%successful%' OR lower(summary) LIKE '% success%' OR lower(summary) LIKE '% ok%')"""
            )
            db.execute(
                """UPDATE platform_events SET status='resolved'
                   WHERE source='pve' AND status='open' AND entity_key IN
                     (SELECT entity_key FROM monitors WHERE provider='pve' AND status='healthy')"""
            )
            db.execute(
                """UPDATE monitors SET name='Watchtower · ' || name,
                     summary='Watchtower 已上报容器镜像检查结果'
                   WHERE provider='watchtower' AND name NOT LIKE 'Watchtower · %'"""
            )
        self.db_path.chmod(0o600)

    def maintain(self, now=None):
        now = now or datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
        backup = self._daily_backup(now.date())
        try:
            retention_days = int(self.config.get("app", {}).get("record_retention_days", 90))
        except (TypeError, ValueError):
            retention_days = 90
        retention_days = max(1, min(retention_days, 3650))
        cutoff = (now - timedelta(days=retention_days)).isoformat(sep=" ", timespec="microseconds")
        with self.connect() as db:
            records = db.execute("DELETE FROM notify_records WHERE created_at < ?", (cutoff,)).rowcount
            outbox = db.execute(
                "DELETE FROM outbox WHERE status IN ('sent','failed') AND updated_at < ?",
                (cutoff,),
            ).rowcount
            summaries = db.execute(
                "DELETE FROM notify_daily_summary WHERE date < ?",
                (cutoff[:10],),
            ).rowcount
            db.execute("PRAGMA optimize")
        return {"backup": str(backup), "records": records, "outbox": outbox, "summaries": summaries}

    def _daily_backup(self, today=None):
        today = today or date.today()
        backup_dir = self.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"notify-router-{today.isoformat()}.tar.gz"
        if not target.exists():
            database_copy = backup_dir / ".main.db.tmp"
            archive_copy = backup_dir / ".backup.tar.gz.tmp"
            database_copy.unlink(missing_ok=True)
            archive_copy.unlink(missing_ok=True)
            source = self.connect()
            destination = sqlite3.connect(database_copy)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            try:
                with tarfile.open(archive_copy, "w:gz", compresslevel=1) as archive:
                    archive.add(database_copy, arcname="db/main.db")
                    archive.add(self.config_path, arcname="conf/config.json")
                    archive.add(self.templates_path, arcname="conf/notify_template.json")
                archive_copy.replace(target)
                target.chmod(0o600)
            finally:
                database_copy.unlink(missing_ok=True)
                archive_copy.unlink(missing_ok=True)
        self._prune_backups(backup_dir)
        return target

    @staticmethod
    def _prune_backups(backup_dir):
        backups = []
        for path in backup_dir.glob("notify-router-????-??-??.tar.gz"):
            try:
                backups.append((date.fromisoformat(path.name[14:24]), path))
            except ValueError:
                continue
        backups.sort(reverse=True)
        keep = {path for _, path in backups[:7]}
        weeks = set()
        for day, path in backups[7:]:
            week = (day.isocalendar().year, day.isocalendar().week)
            if week not in weeks and len(weeks) < 4:
                weeks.add(week)
                keep.add(path)
        for _, path in backups:
            if path not in keep:
                path.unlink()

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

    def record_event(self, domain, source, event_type, entity_key, severity, title, summary, status="open"):
        now = localnow()
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO platform_events
                   (domain, source, event_type, entity_key, severity, title, summary, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (domain, source, event_type, entity_key, severity, str(title), redact_secret_text(summary)[:2000], status, now),
            )
            return cursor.lastrowid

    def update_monitor(self, provider, entity_key, name, category, status, summary="", metadata=None):
        now = localnow()
        payload = json.dumps(metadata or {}, ensure_ascii=False)
        with self.connect() as db:
            previous = db.execute("SELECT status FROM monitors WHERE entity_key=?", (entity_key,)).fetchone()
            changed = not previous or previous[0] != status
            db.execute(
                """INSERT INTO monitors
                   (provider, entity_key, name, category, status, summary, metadata, last_checked_at, last_changed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(entity_key) DO UPDATE SET
                     provider=excluded.provider, name=excluded.name, category=excluded.category,
                     status=excluded.status, summary=excluded.summary, metadata=excluded.metadata,
                     last_checked_at=excluded.last_checked_at,
                     last_changed_at=CASE WHEN monitors.status<>excluded.status THEN excluded.last_changed_at ELSE monitors.last_changed_at END""",
                (provider, entity_key, name, category, status, redact_secret_text(summary)[:1000], payload, now, now),
            )
        if changed:
            unhealthy = status in {"down", "error", "warning"}
            severity = "error" if status in {"down", "error"} else "warning" if status == "warning" else "info"
            self.record_event("monitor", provider, "status_changed", entity_key, severity, name, summary, "open" if unhealthy else "resolved")

    def list_monitors(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM monitors ORDER BY status IN ('down','error') DESC, name")]

    def list_events(self, domain=None, limit=100):
        with self.connect() as db:
            if domain:
                rows = db.execute("SELECT * FROM platform_events WHERE domain=? ORDER BY id DESC LIMIT ?", (domain, limit))
            else:
                rows = db.execute("SELECT * FROM platform_events ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in rows]

    def register_task(self, task_id, plugin_id, name, category, schedule, enabled_value=True):
        now = localnow()
        with self.connect() as db:
            db.execute(
                """INSERT INTO platform_tasks (task_id, plugin_id, name, category, schedule, enabled, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET plugin_id=excluded.plugin_id, name=excluded.name,
                     category=excluded.category, schedule=excluded.schedule, enabled=excluded.enabled, updated_at=excluded.updated_at""",
                (task_id, plugin_id, name, category, schedule, int(bool(enabled_value)), now),
            )

    def prune_plugin_tasks(self, plugin_id, active_task_ids):
        active = list(dict.fromkeys(active_task_ids or []))
        with self.connect() as db:
            if active:
                placeholders = ",".join("?" for _ in active)
                db.execute(
                    f"DELETE FROM platform_tasks WHERE plugin_id=? AND task_id NOT IN ({placeholders})",
                    (plugin_id, *active),
                )
            else:
                db.execute("DELETE FROM platform_tasks WHERE plugin_id=?", (plugin_id,))

    def start_task_run(self, task_id):
        now = localnow()
        with self.connect() as db:
            db.execute("UPDATE platform_tasks SET last_status='running', last_started_at=?, updated_at=? WHERE task_id=?", (now, now, task_id))
            return db.execute("INSERT INTO task_runs (task_id,status,started_at) VALUES (?,'running',?)", (task_id, now)).lastrowid

    def finish_task_run(self, task_id, run_id, started, error=None):
        now = localnow()
        duration = max(0, int((time.time() - started) * 1000))
        status = "failed" if error else "success"
        safe_error = redact_secret_text(error)[:2000] if error else ""
        with self.connect() as db:
            db.execute("UPDATE task_runs SET status=?, finished_at=?, duration_ms=?, error=? WHERE id=?", (status, now, duration, safe_error, run_id))
            db.execute("UPDATE platform_tasks SET last_status=?, last_finished_at=?, updated_at=? WHERE task_id=?", (status, now, now, task_id))

    def list_tasks(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM platform_tasks ORDER BY plugin_id, name")]

    def list_task_runs(self, limit=100):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM task_runs ORDER BY id DESC LIMIT ?", (limit,))]

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
