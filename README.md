# PS5 Deal Watcher

Version 0.1.0 · personal local evaluation · English dashboard · France

A self-hosted dashboard for physical PS5 games you choose, with individual budgets, schedules, delivery and pickup rules, review candidates, source health, and Telegram alerts. Pickup areas default to Lyon/Villeurbanne and Mantes-la-Jolie/Magnanville/Mantes-la-Ville, with a configurable radius around each centre.

## Start locally

Docker Desktop must be running in Linux-container mode.

```powershell
cd <path-to-this-folder>
Copy-Item .env.example .env
docker compose up -d --build
```

Or run `scripts/start-local.ps1`. Open **http://127.0.0.1:8765**. Both services restart automatically while Docker is running; the PC must remain awake for monitoring. No active watches or demo deals are seeded.

1. Create a watch for a specific game and a budget.
2. Open Sources to see actual support. Enable Easy Cash only if you want its experimental review candidates.
3. Configure Telegram in Settings, save, and click Send Telegram test. Do not paste tokens into chats or source code.
4. Use Deals for matches and Activity for runs and the persistent outbox.

The default port binds only to this PC's loopback address. A fresh local database bootstraps **admin / admin@** and forces a password change at first login. For unattended remote provisioning, set a unique `BOOTSTRAP_ADMIN_PASSWORD`; on upgrade, an existing protected `APP_PASSWORD_HASH` is reused as the admin's temporary password. The admin can create and disable accounts. Watches, manual entries, deal/match history, alert events, schedule preferences and Telegram destinations are private to each account. Public source results and source-health status are shared by the service.

## What works and what is limited

| Source | Implementation | Practical coverage |
| --- | --- | --- |
| Dealabs | Public PS5 RSS, verified live from the local Docker environment | Recent feed entries, usually 20–30 items, not an exhaustive search. Disc, shipping, fees, edition and stock often need review. |
| Easy Cash | Experimental public catalogue parser; disabled by default | First page only, currently 30 references. Aggregate “from” prices stay candidates and cannot trigger alerts. No private offer endpoint is fetched. |
| Leboncoin | Experimental headed Chromium service in Docker | Up to five cheapest and five newest result pages per game/alias query, with duplicate pages and listings removed. Processes up to 4 distinct searches per pass and rotates through larger watch sets over successive successful checks. Empty/repeated pages stop early. Bounded coverage, not a full-site crawl. Disabled by default; no long-term reliability guarantee. |
| Vinted | Experimental anonymous catalogue searches for configured games | First 24 cheapest plus 24 newest results per game/alias, deduplicated. Processes up to 8 distinct searches per pass and rotates through larger watch sets over successive successful checks. Item prices only; disc and delivery costs require review. Disabled by default. |

See [SOURCES.md](SOURCES.md) for dated evidence and tested methods. Feed access does **not** guarantee a qualifying all-in alert: incomplete prices and formats deliberately stay candidates. The app does not infer zero fees from silence. A manually entered real offer with confirmed costs and format can qualify and trigger Telegram.

Email/native-alert ingestion is not implemented in this version. No source credentials, CAPTCHA bypass, stealth automation, proxies, browser scraping, automatic purchases or seller messages are used. The app makes no AI/API calls and has no paid service dependency.

## Watches and matching

- Create, edit, duplicate, pause, resume and delete watches. Duplicates are paused.
- Game name, comma-separated aliases, edition/language preferences, excluded terms, new/used condition, bundles and explicit PS4-upgrade opt-in.
- All-in budget by default: item + known delivery + known mandatory fees. Eligible pickup has a separate item + pickup-fees total. Blank costs are unknown, not zero.
- Titles normalize case, accents, apostrophes and punctuation. Wrong sequel numbers, digital/account/accessory/empty-case titles are excluded. Extra subtitle wording and uncertain disc/edition details need review. Matching is intentionally conservative and can need explicit aliases.
- Pickup is a geographic radius from Lyon centre (45.7640, 4.8357) and/or Mantes-la-Jolie centre (48.9900, 1.7160). No geocoder sends your location elsewhere. A manually recorded listing needs coordinates for confident pickup qualification.
- Each watch has start/end times, checking hours and an IANA timezone. Equal checking-hour boundaries mean all day. Spring DST times that do not exist are rejected. Ambiguous autumn times use the first occurrence.
- Five-minute watch checks by default. Source fetch minimums are 5 minutes for Dealabs, Vinted and Leboncoin and 4 hours for Easy Cash; these are conservative app limits, not published permission or guaranteed quotas. Shared source checks serve all due watches. Check now respects limits, dates, pauses and checking hours.
- Failed or partial checks never mark existing offers as sold. Availability remains explicitly unverified or source-reported.

## Telegram

Use the official [bot tutorial](https://core.telegram.org/bots/tutorial#obtain-your-bot-token) to create a bot through @BotFather. Send your bot a message before testing. Obtain your chat ID locally using the official `getUpdates` endpoint or your trusted Telegram tooling; don't give a third-party website your token. Each account adds its own token and chat ID in Settings. Deal alerts never use another user's Telegram destination.

Optional `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` environment variables can send system-monitoring alerts and serve as a fallback for the admin's deal alerts. Other accounts always use their private credentials. Per-user deal-alert credentials and settings are stored in the SQLite volume. Protect the volume and backups.

Alerts contain the source, title, item/shipping/fees/total, condition, location, reason, and original link. First qualification alerts once; further alerts require a strictly lower qualifying price if enabled. Events and attempts survive restarts. Failed sends retry with backoff. Quiet-hour events are queued and re-matched before delivery; observations older than 6 hours wait for a new check or manual update.

**Telegram delivery has a narrow duplicate possibility:** if Telegram accepts a message and the worker crashes before recording success, recovering the uncertain send can deliver it again. Telegram `sendMessage` has no application idempotency key. Normal polling/restarts do not create a fresh event for the same price.

## Server manager handoff

The folder/ZIP contains the complete source, Dockerfile, Compose definition, dependency lock, tests and scripts. It excludes local credentials and database contents.

Requirements: Docker Engine with Compose v2; outbound HTTPS to supported sources and Telegram; available host port (8765 by default). Only one worker instance is intended. The image runs as UID/GID 10001, with a read-only root filesystem and a persistent named volume. No Redis, separate database server or browser runtime is required. Final resource measurements are in [VALIDATION.md](VALIDATION.md).

On a Linux host, extract into an isolated directory, then:

```sh
umask 077
cp .env.example .env
chmod 600 .env
sh scripts/deploy.sh
docker compose ps
```

Confirm CPU architecture and build the image on the target host. Local validation is on Linux/amd64; ARM is not yet verified.

After the first login as `admin / admin@`, set a private password before continuing. Create additional accounts from **Users**; each new account must change its temporary password at login. Use a unique, long password, especially if the service is reachable over a LAN or HTTPS reverse proxy. `COOKIE_SECURE=true` is appropriate only over HTTPS. The app defaults to localhost. Explicit LAN binding is possible with `BIND_ADDRESS=<server-LAN-IP>`. Router, firewall, Internet exposure and reverse proxy configuration are outside this package.

An optional `https` Compose profile includes Caddy. For a server with a public DNS name, set `WATCHER_DOMAIN` to that name, change `COOKIE_SECURE=true`, ensure DNS points to the server and ports 80/443 reach it, then run `docker compose --profile https up -d`. Caddy obtains and renews a public TLS certificate; the web service remains loopback-bound on the host. This profile has not been activated or tested against a real server/domain. Keep local evaluation on the default localhost-only profile.

## Operations

```sh
docker compose up -d                  # start
docker compose stop                  # stop, preserve data
docker compose logs --tail=100 web worker
docker compose ps
docker compose exec -T web python -m pytest -q -p no:cacheprovider
docker compose exec -T web python -m scripts.verify_sources  # optional bounded live checks
```

Do not use `docker compose down -v`: that removes the app's persistent volume. Checks need an awake host. Docker restart policies restart processes, not the host or Docker Desktop itself.

Health URLs: `/health/live`, `/health/ready` and `/health/worker` (503 for stale worker heartbeat). Source health and recent errors are in the dashboard. Logs are capped at three 5 MB files per service. The SQLite database uses WAL, transactions, uniqueness constraints and scheduler/source/delivery leases.

`.github/workflows/external-uptime.yml` runs from a GitHub-hosted runner every 15 minutes and can be started manually from Actions. It checks the public login, database-readiness and worker-health endpoints without credentials, so it can detect a home-server outage independently. GitHub may delay or drop scheduled runs during high load; configure GitHub Actions failure notifications in your account if you want email/web alerts.

## Backup and restore

The backup helper uses SQLite's backup API to create a consistent snapshot while the app is running. Never copy only the live `.sqlite3` file while WAL writes are in progress.

Compose runs a dedicated backup container. It creates an integrity-checked snapshot at startup and every 24 hours, retaining the latest 14 snapshots in a separate `watcher-backups` volume. Before promoting a new snapshot, it restores it into a disposable directory and verifies integrity, schema, and table row counts. An existing unverified snapshot gets the same drill at startup. The monitor considers the latest backup healthy only when a matching restore-verification marker exists; Docker also runs an integrity check hourly. The service reads the live data volume read-only and has no Telegram credentials. Both volumes are still on the same host, so copy important snapshots off-host for protection from host or disk loss. A database or disk failure can also prevent creation of new backups.

```sh
docker compose exec -T web python -m scripts.backup /data/backups/watcher.sqlite3
mkdir -p backups
chmod 700 backups
docker compose cp web:/data/backups/watcher.sqlite3 ./backups/watcher.sqlite3
chmod 600 ./backups/watcher.sqlite3
```

Keep an off-host protected copy. Files left inside `/data/backups` use the same named volume and are not disaster recovery on their own.

To restore, first stop **both** services. Preserve the current backup and record the current image/release. Then mount the backup read-only into a temporary container:

```sh
docker compose stop
docker compose run --rm --no-deps -v "$PWD/backups/watcher.sqlite3:/restore.sqlite3:ro" web python -m scripts.restore /restore.sqlite3 --confirm-replace
docker compose up -d
docker compose ps
```

The restore helper validates integrity and schema version 1 and preserves an existing app database as `/data/pre-restore.sqlite3`. Restore explicitly replaces this app's database only; don't run it while either service is writing.

## Update and rollback

1. Back up the database and private `.env`, and keep the old source ZIP and image.
2. Stop services. Build the new tagged image and run its migration helper. Start and verify both health checks, persisted watches, and source status.
3. If rolling back, stop both services, restore the old source/Compose image tag and its matching pre-upgrade database backup, then start again. An old image alone does not reverse a database migration.

Version 0.1.0 has one idempotent initial migration, schema version 1. No future schema downgrade is implied. The dependency versions are locked and the base image digest is recorded in validation. Do not run multiple replicas against the same local SQLite volume.

## GitHub CI/CD deployment

`.github/workflows/ci-cd.yml` runs the test suite and builds all Compose images for pull requests and pushes to `main`. A successful push to `main` then deploys that exact commit through a self-hosted GitHub Actions runner on the home server. The runner initiates its connection to GitHub, so the server can stay on its private LAN address. Deployment rebuilds and restarts changed Compose services, preserves named data volumes, and waits for the web, worker, monitor and browser health checks.

Use a private GitHub repository. Only the trusted `main` branch runs deployment jobs on the self-hosted runner; pull-request tests use GitHub-hosted runners. Anyone able to change workflow or Compose files on `main` can execute code with the runner's Docker access, which is effectively root access to that server. Keep repository write access limited to trusted maintainers and do not run pull-request jobs on the home-server runner.

Before enabling the workflow, configure the server runner with the label `ps5-deal-watcher`, make Docker available to its service account, and provision `/etc/ps5-deal-watcher.env` with mode `0600`. This file must remain outside the checkout and contains monitoring Telegram credentials (if used), bind address and port. User accounts live in the protected database volume. Do not commit `.env` or server data. The runner must check out the repository with `main` as its default branch. The workflow does not expose SSH to GitHub-hosted runners and does not store server passwords or SSH keys in GitHub Actions secrets.

The deploy step leaves the previous data volumes intact. It reports a failed health check in Actions but does not automatically roll back code or database migrations; review the failed deployment and use the backup/restore procedure before any schema rollback.

## Development without Docker

Python 3.13:

```sh
python -m venv .venv
# activate the environment using your platform's standard command
python -m pip install -r requirements.lock
python -m pytest -q
python -m uvicorn app.web:app --host 127.0.0.1 --port 8765 --no-access-log
# separate terminal, same environment/data directory:
python -m app.worker
```

Set `DATA_DIR` to a private writable directory if needed. Production does not run test fixtures or demo seed data.

Alert qualification defaults to game name (or explicit alias) plus advertised item price. Platform, physical format, edition, delivery and fees are displayed but do not block alerts. Source selection, availability, schedule and deduplication still apply. Detailed filters and evidence mode remains available per watch.

Leboncoin requires the additional internal `browser` Compose service (Chromium + Xvfb). It has no published port or access to the application data volume. Browser binaries increase image size and resource usage; reserve roughly 1 GB of RAM for evaluation. Local monitoring is experimental and may be blocked on another network.

Leboncoin debugging: `docker compose logs --tail 100 browser`. Structured logs include a run ID, stage, elapsed time, Chromium version, HTTP status, anti-bot/consent flags and card counts. Credentials, cookies, search terms, full URLs and page contents are excluded. Source errors include the matching diagnostics ID.

### Persistent Leboncoin session
Browser cookies and profile are stored in the private browser-profile Docker volume, surviving container recreation. docker compose down -v deletes it. Do not distribute this volume. Automatic device checks get a bounded 12-second wait; interactive CAPTCHA solving is not implemented. Unresolved challenges remain blocked. Logs contain counts, never cookies.

### Experimental interactive challenge handler
Set LEBONCOIN_INTERACTIVE_SOLVER=true in your Compose environment to enable one attempt on the observed DataDome slide-to-end challenge. It uses the visible handle and target positions, then requires the challenge to disappear and visible listings to load. Unsupported challenge types are left blocked. No audio transcription or image-puzzle solver is implemented. Disabled by default because the live test moved the slider but resulted in Access is temporarily restricted, without listings. Persistent profile storage remains enabled.

### Leboncoin profile mode
Compose defaults to a persistent Leboncoin profile in the private `browser-profile` volume so cookies survive container recreation. Set `LEBONCOIN_PROFILE_MODE=fresh` to use an isolated temporary profile per cheapest/newest search; it is removed after the check. Fresh profiles have not demonstrated reliable access. When a container is recreated, stale Chromium singleton lock links are removed only when their recorded process is gone; stored cookies and profile data are preserved.

### Challenge classification and dispatch
Leboncoin inspects challenge-frame visibility, frame content and visible controls. Detected types: slide_to_end, image_slider, image_puzzle, audio, device_check, restriction, hidden_frame and unknown. Hidden frames alone do not mark HTTP200 results blocked. Visible device checks get bounded waiting and reclassification; slide_to_end routes to the existing handler only when LEBONCOIN_INTERACTIVE_SOLVER=true. Restriction pages back off. Image and audio solvers are not implemented and are explicitly unsupported. Unrecognised visible challenges remain blocked. Classification is heuristic and can require refinement as site markup changes. Logs record type, confidence and handler without page content, tokens or URLs.

### Experimental canvas image-slider solver
Image-slider routing now supports a CPU-only silhouette matcher for readable same-sized background and transparent-piece canvases (maximum600x400). It estimates a dark gap using the piece boundary, rejects ambiguous matches, performs one drag and requires listings without the challenge before reporting success. No AI downloads or audio processing. It does not solve image-selection grids, rotations or arbitrary visual puzzles. Enabled with LEBONCOIN_INTERACTIVE_SOLVER=true; otherwise remains disabled. French simple slide-to-end prompts are recognised separately; page logos and zero-height canvases no longer count as image puzzles.

### Live Docker browser viewer
Open http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale to watch the virtual display. The viewer is view-only and bound to host localhost. It is blank when no Chromium check is running; it is not a recording. No VNC port is published. BROWSER_VIEW_PORT can change the local port.

### Current Leboncoin adapter: ordinary Chromium + CDP
Compose now uses LEBONCOIN_BROWSER_MODE=normal and LEBONCOIN_PROFILE_MODE=persistent, with the dedicated private /browser-data/app-profile in the browser-profile volume. Chromium is started directly, allowed to load the homepage, then Playwright attaches through a dynamic loopback-only CDP port. The same context serves cheapest/newest and multiple game queries. Browser and owned subprocess are closed after each check; cookies are retained. The viewer remains localhost-only and view-only. Existing source interval, matching and Telegram deduplication still apply.

This local installation was seeded by copying the successful manual/test session into the app profile; references were preserved. The deployment ZIP contains no cookies or profiles. A new server starts with an empty profile and needs its own validation: local success does not establish access on another server or IP.

### Check now
Check now queues an immediate parallel pass for active, unexpired watches across every source selected in those watches, including sources disabled for automatic polling. This pass bypasses checking hours, future start times, next-check schedules and source cooldowns. It retains watch configuration, pause/expiry rules, matching and notification deduplication. New alerts from the manual pass can be delivered outside checking hours; global Telegram quiet hours still apply. A running source check is not duplicated: repeated clicks coalesce, and a request made during an existing scheduler pass waits for that pass to finish. An idle worker wakes within about one second. Network checks take time to complete. Regular polling continues to respect the configured schedules and enabled sources.

### Monitoring

Compose includes an independent `monitor` service using the existing image, SQLite volume and Telegram credentials. It probes web readiness and browser health every 30 seconds, reads worker heartbeat, source runs and delivery attempts, and exposes the results in the dashboard's Monitoring tab at `/monitoring`. No additional marketplace requests, ports or credentials are required. Seven days of monitoring samples are retained; source and Telegram performance summaries cover the last 24 hours. Reload the page for updated data. Each container has its own Docker health check; Docker's restart policy restarts exited processes, not merely unhealthy containers.

Source parser diagnostics use saved synthetic, redacted fixtures in `tests/fixtures/parsers/`. Activity reports `Challenge detected` when a challenge page is identified and `Format change` when an expected response schema or card structure is missing; neither result is recorded as an empty search or ingested. Valid parsed zero-result responses remain successful and display an explicit empty-result message. Fixtures must stay minimal and must not contain raw pages, cookies, tokens, seller details or other personal data.

Web/browser/worker failures alert after three minutes of observed failure. Sources alert after three consecutive failed checks; active schedules overdue by ten minutes and checks running longer than 180 seconds also alert. Continuously eligible undelivered notifications alert after ten minutes, including retry backoff; watch hours, global quiet hours, stale observations and nonqualifying offers reset this timer. Monitoring alerts themselves bypass deal quiet hours. A successful zero-result search is healthy. One failure and one recovery message are sent per observed incident, with failed-send retries. Telegram confirmation is API acceptance, not proof the user read the message.

The monitor is independent of the worker but shares the host and database. It cannot notify during a total host outage or a Telegram outage, and Docker/DB failure can stop monitoring too. Its sample timestamp and Docker health check identify a stalled monitor locally; external uptime monitoring needs another machine. Adapter success does not prove complete marketplace coverage. See `IMPROVEMENTS.md` for proposed resilience and accuracy work.

Worker startup recovers orphaned running checks and scheduler/source leases. This deployment supports exactly one worker; do not scale replicas without implementing coordinated startup ownership. Existing delivery leases retain their timeout-based recovery.
