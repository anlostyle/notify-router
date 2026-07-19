# Changelog

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
