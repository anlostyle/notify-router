# Changelog

## 0.6.21 - 2026-10-10

- 插件接口 `/api/plugins/<插件>/...` 默认需要管理后台登录（会话 Cookie 或 HTTP Basic）。插件可以在 manifest 的 `public_paths` 里声明公开地址；未声明时只有企业微信回调 `chat` 公开。未登录的浏览器打开插件页面会跳回管理后台。
- FlowLink 插件 0.4.1 声明 `chat` 和 `shortcut` 为公开地址，iOS 快捷指令入口不受影响。

## 0.6.20 - 2026-10-10

可靠性：
- 投递线程在数据库短暂报错时自动恢复，不再静默退出；入队和手动重试会立即唤醒线程，不再依赖轮询。
- 消息已发出但写回状态失败时不再重复发送。
- `/healthz` 返回投递线程心跳，线程停止或卡住时返回 503，容器健康检查能发现问题。
- 手动重试失败投递时重新开始完整的重试周期。
- 单个插件的 manifest.json 损坏时跳过该插件，不再阻止服务启动。
- Telegram 消息转义 `<`、`&` 等字符，保留 Telegram 支持的 HTML 标签。

安全：
- 插件 Worker 不再继承 `NH_PASSWORD`、`SESSION_SECRET`、`NOTIFY_API_TOKEN`，插件代理也不再转发管理后台的会话 Cookie。

界面：
- “通知通道”更名为“通知路由”，避免与“通知渠道”混淆。
- 看板：默认密码提示条、累计投递趋势线、无数据时成功率显示“—”、渠道状态面板，最近活动可直接打开详情。
- 渠道卡片按渠道类型显示关键配置，并显示最近投递时间、失败原因和被几个路由使用。
- 模板按来源分组，标题显示中文事件名，内容预览最多三行。
- 投递历史：状态分段切换、路由/渠道下拉筛选、今天/近 7 天/近 30 天快捷范围、手机端筛选可折叠；点整行查看详情，失败投递可在详情里重新发送。
- 接口失败时显示错误状态和“重新加载”，顶栏与侧栏的服务状态改为实时检测。
- 修复手机端表格卡片中多个渠道标签溢出、状态标签被拉满整行的问题。
- 插件页把已加载插件放在最前，没有插件源时只显示一行引导。
- 设置页不再明文显示 GitHub Token。
- 默认密码提醒每个浏览器会话只自动弹出一次。
- 静态资源地址带版本号，升级后浏览器会立即加载新界面。

## 0.6.15 - 2026-09-05

- 将 NS/DF 论坛 RSS 的发布时间从 GMT 转换为北京时间。
- 让 Emby 内置模板、前端实时预览和实际通知使用同一份可编辑模板。

## 0.6.14 - 2026-09-01

- 初始化插件 Worker 日志处理器，确保插件业务 INFO 日志进入插件日志面板。
- 保持插件通知测试能力在持久化插件目录升级后可用。

## 0.6.13 - 2026-09-01

- 独立展示插件使用说明与企业微信回调地址，保持配置页简洁。
- 增加插件 Worker 日志查看与中文生命周期状态。
- 增加 NDU、NSRSS、Reminder 的插件级通知测试。

## 0.6.12 - 2026-09-01

- Add CleanLLM-style theme palettes, per-event template variable helpers, delivery filters, connection probes, and configuration export/import.
- Include plugin settings in configuration exports and validate imports before applying them.

## 0.6.11 - 2026-08-31

- Seed built-in notification templates only for fresh data volumes, preserving later user edits and deletions across restarts.
- Leave the login username field empty instead of prefilling `admin`.

## 0.6.10 - 2026-08-30

- Group registered template event types by module in the event selector, with Chinese labels and a custom-event option.

## 0.6.9 - 2026-08-30

- Preserve explicit empty image URLs so a request can disable a route default image.
- Normalize legacy scalar route channel and template bindings to arrays.

## 0.6.8 - 2026-08-30

- Add a Chinese-labelled picker for all registered native event types when creating or editing templates, with support for custom event type values.

## 0.6.7 - 2026-08-30

- Keep only the four built-in Emby templates used by the default setup: playback start/stop and movie/series library additions.

## 0.6.6 - 2026-08-30

- Decode clearly labelled double-escaped line breaks without changing command text.
- Seed and merge built-in Emby, PVE, and Watchtower notification templates.
- Update Compose examples to the current release.

## 0.6.1 - 2026-07-20

- Load monitoring and task navigation counts during the initial console refresh.
- Remove stale plugin task registrations after each successful worker activation.
- Classify descriptive PVE successful statuses correctly and treat unknown states as warnings.
- Label Watchtower passive reports clearly in the monitoring center.

## 0.6.0 - 2026-07-19

- Establish notification, monitoring, task, and marketplace domain boundaries.
- Add normalized monitor state, status events, scheduled tasks, and task run history.
- Add Monitoring Center and Task Center pages to the administration console.
- Record NDU, Watchtower, Nezha, and PVE backup health in the monitoring domain.
- Track Reminder and NSRSS cron execution through the shared task runtime.
- Introduce plugin manifest schema v2 capability declarations.

## 0.5.0 - 2026-07-19

- Run every third-party plugin in an isolated supervised worker process.
- Hot-apply plugin installs, updates, and removals without restarting the router.
- Keep the previous worker serving when candidate startup fails and restore plugin code automatically.
- Isolate plugin dependencies and persistent runtime data by plugin ID.

## 0.4.0 - 2026-07-19

- Add configurable JSON plugin sources and an admin plugin store.
- Support online plugin install, update detection, upgrade, and recoverable uninstall.
- Validate HTTPS endpoints and safely unpack plugin archives with size, path, symlink, manifest, and version checks.
- Keep replaced and removed plugin files under the persistent `plugin-backups` directory.

## 0.3.0 - 2026-07-14

- Restore Emby poster images for movie and episode notifications.
- Add daily SQLite-consistent backups with seven daily and four weekly copies.
- Enforce the configured notification history retention period.
- Add administrator login rate limiting and disable access logs by default.
- Add portable Docker Compose and tagged GHCR image releases.
