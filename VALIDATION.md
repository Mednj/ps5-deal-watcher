# Validation record

Release: **0.1.0**, local Git tag `v0.1.0`. Date: **2026-10-01**, Europe/Paris.

## Results

- 36 deterministic tests passed on Windows/Python 3.13 and inside the final Linux Docker image.
- Cases cover all-in arithmetic, unknown costs, separate pickup totals/radius, excluded listing types, wrong sequels/platforms, aliases/accents/edition ambiguity, bundles, from/trade-in prices, persistent deduplication/lower-price events, retries, quiet hours with changed offers, DST/pauses/expiry, shared source fetches, offset watch schedules reusing cached snapshots, source failure preservation, leases, backup restoration, RSS challenge detection, URL restrictions, separate catalogue card prices, HTTP 403/429/500, redirect refusal, CRUD, CSRF, escaped untrusted titles, secret redaction, single-password login and manual-listing/outbox flow.
- One dependency deprecation warning: Starlette's test client says its httpx backend is deprecated. Tests passed; the application still uses the official HTTP client. No production failure was observed.
- Built and started both web and worker with Docker Compose. Both health checks passed.
- `/health/ready` and `/health/worker` returned success from the host.
- The SQLite backup command completed. The actual restore command restored that backup into an isolated temporary data directory and validated schema/integrity. The production database was not replaced.
- Both production containers restarted successfully. The persisted verification marker and all 59 real source references survived. Database and backup file permissions were verified as 0600 in Linux.
- Desktop dashboard was visually inspected at the normal app viewport; mobile layout was inspected with a 390×844 viewport override. The override was then reset. No production test watches or demo listings remain; there are zero user watches until the user creates one.

## Live sources

- Dealabs RSS: **verified working**, 29 genuine priced entries fetched and parsed from inside Docker.
- Easy Cash public category: **experimental**, 30 genuine catalogue references parsed, with separate card prices; all are aggregate/from candidates, never alerts. Disabled by default.
- Leboncoin and Vinted: **blocked for direct collection by policy/terms**, manual/native-alert fallback only. No live automatic monitoring claimed.

See SOURCES.md for URLs and limits. Source access from the eventual home server remains unverified.

## Measured resources

One idle snapshot after the final restart, Docker Desktop Linux/amd64:

| Component | Memory | CPU |
| --- | --- | --- |
| Web | 41.91 MiB | 0.22% |
| Worker | 29.20 MiB | 0.01% |

Image size: approximately 152 MB uncompressed. These are idle measurements, not worst-case guarantees. Catalogue parsing and HTTPS requests can briefly increase memory; reserving 512 MB RAM and 1 GB disk for a small installation is a practical initial allowance, to be checked on the target server. Host Docker overhead is additional. ARM build/runtime was not tested.

Base image pinned to `python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b`. App image uses tag `ps5-deal-watcher:0.1.0`. Python dependencies are pinned in requirements.lock. Local final built worker image ID: `sha256:c99b6c13d6f9540d43e064d959e7b72711b62117ff23016f4121b8e8d1d86419`; Compose's parallel build may assign distinct provenance IDs to otherwise equivalent service images.

## Deployment status and remaining setup

**Running locally:** http://127.0.0.1:8765, loopback only. Not deployed to 192.168.1.2 or any other server. Docker must remain running and the PC awake for checks.

**Telegram:** implementation and fake-channel delivery/retry tests passed. No real phone message was sent because no bot token/chat ID was supplied. Enter those locally in Settings, save, then send the labelled test. The user's first game and budget must also be entered before automatic monitoring begins.

**Server handoff:** Compose support confirmed by the user; target OS, architecture, deployment path, HTTPS/VPN and server source access remain for the manager to confirm. ZIP contains source/configuration templates only, not credentials or local database contents.
