# Notify Router

Clean-room implementation of the public NotifyHub API and plugin contract. It reads the existing `/data/conf/config.json`, `/data/conf/notify_template.json`, `/data/db/main.db`, and `/data/plugins` layout directly, so migration can use a copied data volume instead of re-entering channels and routes.

Current compatibility target:

- `POST /api/service/notify`
- Bark-style `GET|POST /api/service/notify/{route_id}/{title}/{content}`
- native Emby, PVE/Gotify, and Watchtower endpoints
- existing channel and route JSON shape
- existing notification records database tables
- `/data/plugins/*/manifest.json`, FastAPI routers, `after_setup`, cron jobs, plugin config helpers, and `server.send_notify_*`
- built-in `chatbot` and `qywx_receive` callback routes
- durable SQLite outbox with retries
- native Enterprise WeChat channels with a configurable API server

Run locally:

```bash
docker compose up --build
```

The compatibility instance listens on `127.0.0.1:5401` by default.

## Parallel deployment

The production compose file is `deploy/compose.sg.yaml`. It mounts `/appdata/notify-router/data`, reads root-only credentials from `/opt/notify-router/.env`, and deliberately binds only to `127.0.0.1:5401` until the reverse proxy is switched. `PLUGIN_TASKS_ENABLED=0` prevents duplicate cron jobs and bot polling while the old instance is still active.

## Final data migration

Check the old volume while both services are still online:

```bash
python scripts/migrate_legacy_data.py --check /appdata/notifyhub/data /appdata/notify-router/data
```

For final cutover, stop both containers first, then run:

```bash
python scripts/migrate_legacy_data.py --confirm-stopped /appdata/notifyhub/data /appdata/notify-router/data
# Change PLUGIN_TASKS_ENABLED to "1" after the old container is stopped.
docker compose -f deploy/compose.sg.yaml up -d
```

The migration takes a SQLite-consistent snapshot, atomically replaces the destination directory, and retains the previous destination as `data.backup-<timestamp>` for rollback. Start the new service and run the compatibility validator before changing the reverse proxy.
