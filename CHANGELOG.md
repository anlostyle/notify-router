# Changelog

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
