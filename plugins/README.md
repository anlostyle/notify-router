# Optional plugins

These plugins are copied manually into `data/plugins`; the release image does
not install or configure them automatically.

Notify Router 0.4.0 and later can also install and update them from the admin
plugin store. Add this source URL under **插件管理 → 插件源**:

```text
https://raw.githubusercontent.com/anlostyle/notify-router/master/plugin-store.json
```

Plugin changes are downloaded into the persistent `data/plugins` directory and
take effect after the Notify Router container is restarted. Replaced or removed
plugin files are retained under `data/plugin-backups` for rollback.

| Plugin | Purpose | Required configuration |
| --- | --- | --- |
| `TGForwardBot` | Telegram private-message relay | Bot Token, administrator Chat ID |
| `nextfind_assistant` | Search, subscribe, and save NextFind resources through Enterprise WeChat | NextFind OpenAPI, Enterprise WeChat application |
| `ndu_monitor` | Forward Docker image and GitHub release updates through Notify Router | Images, GitHub repositories, notification route |
| `nsrss` | NodeSeek and DeepFlood RSS keyword monitoring | Sites, keywords, routes, cron |
| `reminder` | One-time, recurring, and subscription reminders | Notification routes configured in Notify Router |
| `wx-media302-save` | Save 115 links through Media302 and Enterprise WeChat | Media302 and Enterprise WeChat credentials |
| `wx-nullbr` | Search Nullbr and save results through Media302 | Nullbr, TMDB, Media302, and Enterprise WeChat credentials |

Install all plugins:

```bash
mkdir -p data/plugins
cp -R plugins/* data/plugins/
docker compose restart
```

To install one plugin, copy only its directory. Runtime configuration remains
inside the instance database and is intentionally excluded from this repository.

The original author is retained in each `manifest.json`. Imported plugins keep
their original authorship; inclusion here does not transfer copyright.
