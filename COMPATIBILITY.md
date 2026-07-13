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

## Native service endpoints

- Emby: `/api/service/emby/notify/{route_id}`
- PVE/Gotify: `/api/service/pve/notify/{route_id}/message`
- Watchtower/Shoutrrr: `/api/service/watchtower/notify/{route_id}`
- Built-in enterprise WeChat callbacks: `/api/plugins/chatbot/chat` and `/api/plugins/qywx_receive/verify`

All three service adapters select the route's existing bound Jinja template and enqueue the rendered result through the same durable delivery path.
