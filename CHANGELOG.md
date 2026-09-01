# Changelog

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
