# Compatibility contract

This project is independently implemented from the public API documentation, the public plugin-development guide, and observed data formats. The upstream repository does not publish the application core or a license for it, so no upstream core code is copied.

## Data volume

- `/data/conf/config.json`: top-level `app`, `channels`, and `routes` objects.
- `/data/conf/notify_template.json`: top-level `template` array.
- `/data/db/main.db`: existing `cache`, `notify_daily_summary`, `notify_records`, and `plugins` tables are preserved.
- `/data/plugins/<plugin_id>`: unchanged plugin directory layout.

## Plugin Python surface

- `notifyhub.plugins.utils.get_plugin_data/get_plugin_config`
- `notifyhub.plugins.common.after_setup`
- `notifyhub.controller.server.Server/server`
- `notifyhub.controller.schedule.register_cron_job`
- `notifyhub.common.response.data_to_json/json_with_status/json_500`
- `notifyhub.plugins.components.qywx_Crypt.WXBizMsgCrypt`
- automatic discovery of FastAPI `APIRouter` objects whose variable names end in `router`
- plugin frontend files under `/api/plugins/<plugin_id>/frontend`

## Delivery semantics

Requests are committed to SQLite before the API returns. Channel delivery happens from a durable outbox, with bounded retries and a permanent failure record. Existing `notify_records` and `notify_daily_summary` rows continue to be populated.

The generic `/api/service/notify` endpoint accepts `route_id`, `title`, `content`, and optional link/image fields from either a JSON POST body or URL query parameters. When both are present, JSON body values take precedence and query parameters fill missing fields. This supports webhook callers such as Flowlink that use URLs in the following form:

```text
/api/service/notify?route_id=route_id&title={title}&content={content}
```

URL callers should encode a real line break as `%0A`, not a literal `\\n`
(`%5Cn`). For labelled line-oriented payloads, Notify Router also accepts the
common double-escaped form and decodes it before delivery.

## Native service endpoints

- Emby: `/api/service/emby/notify/{route_id}`
- PVE/Gotify: `/api/service/pve/notify/{route_id}/message`
- Watchtower/Shoutrrr: `/api/service/watchtower/notify/{route_id}`
- Built-in enterprise WeChat callbacks: `/api/plugins/chatbot/chat` and `/api/plugins/qywx_receive/verify`

All three service adapters select the route's existing bound Jinja template and enqueue the rendered result through the same durable delivery path.

### Notification templates

A fresh data volume starts with an empty `notify_template.json`. Startup does
not seed, merge, or replace notification templates. Administrators create the
templates required by their Emby, PVE, Watchtower, and custom integrations.

The template editor exposes all registered native event type values with
Chinese labels and accepts custom event type values for other integrations.

Configure Emby to POST its webhook JSON to:

```text
/api/service/emby/notify/<route_id>?emby_url=https://your-emby.example
```

The route must bind the corresponding `emby_*` templates. `emby_url` is used to generate the media image and Emby item link; an explicit `push_link_url` in the JSON body still takes precedence.
