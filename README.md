# Notify Router

Notify Router is a self-hosted notification and plugin service compatible with the public
NotifyHub API and data layout. It includes a responsive management console,
durable SQLite delivery queue, retries, templates, plugins, and native
Enterprise WeChat channels with a configurable API server.

Supported notification sources include generic HTTP calls, Emby, PVE/Gotify,
Watchtower, Uptime Kuma, VoHive, DSM, and existing NotifyHub plugins.

## Install

Requirements: Docker Engine with Docker Compose v2.

```bash
cp .env.example .env
```

The first login is `admin / password`. Change it immediately from
“系统设置 → 修改密码”; the new password is stored in the persistent `data/conf`
directory and takes effect without restarting the container. For a fully
automated deployment, set `NH_PASSWORD` to another value before starting.
`SESSION_SECRET` is optional; when omitted, Notify creates a persistent signing
secret after the first password change.

Then start the pinned release:

```bash
docker compose pull
docker compose up -d
```

The console listens on `http://127.0.0.1:5401` by default. Set
`NOTIFY_BIND=0.0.0.0` only when a firewall or trusted LAN protects the port.
For public access, keep the loopback binding and publish it through an HTTPS
reverse proxy, then set `COOKIE_SECURE=1`.

To build the source instead of pulling the release image:

```bash
docker compose up -d --build
```

## Configuration and security

- `NH_USER` and `NH_PASSWORD` provide the initial management-console credentials.
- After a password change, the hashed password and (when needed) session signing
  secret are stored under `data/conf/security.json` with mode `0600`.
- `NOTIFY_API_TOKEN` optionally protects notification endpoints with
  `Authorization: Bearer <token>`. Leave it empty only for legacy callers that
  cannot add headers.
- Access logs are disabled by default because legacy GET requests may contain
  notification text in the URL.
- Authenticated management APIs return saved configuration values in plaintext.
  The management console also displays API keys, tokens, passwords, webhook
  URLs, and application secrets as plaintext. Restrict console access to trusted
  administrators and always publish it through HTTPS.

Runtime data is stored only in `./data`. Images and source archives do not
contain channels, routes, tokens, phone numbers, or notification history.

Fresh installations start with an empty notification-template list. Templates
are created and managed explicitly in the management console; startup never
adds or replaces templates in an existing data directory.

When creating a template, the event type field lists all registered Emby, PVE,
and Watchtower event types with Chinese labels. Select “自定义事件类型” for
other integrations.

## Backups and retention

When the delivery queue is idle, the service creates one SQLite-consistent
archive per day under `data/backups`. It keeps seven daily copies plus one copy
from each of the previous four weeks. Each archive contains:

- `db/main.db`
- `conf/config.json`
- `conf/notify_template.json`

The console's `record_retention_days` setting removes older completed delivery
history only after the daily backup succeeds. Pending and retrying deliveries
are never pruned.

Restore a backup:

```bash
docker compose down
mv data data.before-restore
mkdir data
tar -xzf data.before-restore/backups/notify-router-YYYY-MM-DD.tar.gz -C data
docker compose up -d
```

## Upgrade and rollback

Change `NOTIFY_VERSION` in `.env`, then run:

```bash
docker compose pull
docker compose up -d
```

Rollback uses the same commands with the previous version number. Back up the
`data` directory before migrations or major upgrades.

## Health check

```bash
curl http://127.0.0.1:5401/healthz
```

The Docker image contains the same health check. Uptime Kuma can monitor this
endpoint directly.

## Existing NotifyHub migration

The project can read the existing `/data/conf`, `/data/db/main.db`, and
`/data/plugins` layout. See [COMPATIBILITY.md](COMPATIBILITY.md) for the exact
contract and use the scripts under `scripts/` to validate or copy legacy data.

## Optional plugins

Sanitized optional plugins are provided under `plugins/`. They contain no
runtime configuration or credentials. On Notify Router 0.4.0 and later, open
**插件管理 → 插件源** and add:

```text
https://raw.githubusercontent.com/anlostyle/notify-router/master/plugin-store.json
```

The admin plugin store can then install new plugins and update existing ones.
Since 0.5.0, every third-party plugin runs in an isolated worker process. Store
changes hot-switch only the affected plugin, keep the router online, and roll
back automatically if the candidate fails its startup check. Plugin dependencies
live under `/data/plugin-runtime/<plugin-id>` and mutable state lives under
`/data/plugin-data/<plugin-id>`. Manual installation remains
available:

```bash
mkdir -p data/plugins
cp -R plugins/* data/plugins/
docker compose restart
```

Open the plugin settings page after restart and enter your own service URLs,
API keys, Enterprise WeChat credentials, routes, and keywords. See
[`plugins/README.md`](plugins/README.md) for the included plugins and required
configuration.

## Platform domains

The 0.6 architecture keeps one deployable container while separating product
domains internally. Notification delivery remains compatible with the original
API. Monitoring owns normalized health state and incidents; Tasks owns schedules
and run history; Marketplace owns plugin distribution; the worker runtime is a
shared core capability. Manifest schema v2 lets plugins declare capabilities
such as `monitor.provider`, `task.handler`, `notify.action`, and
`integration.provider` so features can appear in the appropriate center instead
of being grouped only by installation package.

## Development

```bash
uv sync --extra test
uv run pytest
```
