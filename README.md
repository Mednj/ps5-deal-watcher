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

The default port binds only to this PC's loopback address. There is no elaborate user system; an optional single password is provided for deployment beyond local evaluation.

## What works and what is limited

| Source | Implementation | Practical coverage |
| --- | --- | --- |
| Dealabs | Public PS5 RSS, verified live from the local Docker environment | Recent feed entries, usually 20–30 items, not an exhaustive search. Disc, shipping, fees, edition and stock often need review. |
| Easy Cash | Experimental public catalogue parser; disabled by default | First page only, currently 30 references. Aggregate “from” prices stay candidates and cannot trigger alerts. No private offer endpoint is fetched. |
| Leboncoin | Native search/manual entry fallback | Direct collection restricted by current terms/robots. No automatic fetching or alert ingestion. |
| Vinted | Native search/manual entry fallback | Terms restrict scraping. The supplied category includes several platforms, not just PS5. No automatic fetching or alert ingestion. |

See [SOURCES.md](SOURCES.md) for dated evidence and tested methods. Feed access does **not** guarantee a qualifying all-in alert: incomplete prices and formats deliberately stay candidates. The app does not infer zero fees from silence. A manually entered real offer with confirmed costs and format can qualify and trigger Telegram.

Email/native-alert ingestion is not implemented in this version. No source credentials, CAPTCHA bypass, stealth automation, proxies, browser scraping, automatic purchases or seller messages are used. The app makes no AI/API calls and has no paid service dependency.

## Watches and matching

- Create, edit, duplicate, pause, resume and delete watches. Duplicates are paused.
- Game name, comma-separated aliases, edition/language preferences, excluded terms, new/used condition, bundles and explicit PS4-upgrade opt-in.
- All-in budget by default: item + known delivery + known mandatory fees. Eligible pickup has a separate item + pickup-fees total. Blank costs are unknown, not zero.
- Titles normalize case, accents, apostrophes and punctuation. Wrong sequel numbers, digital/account/accessory/empty-case titles are excluded. Extra subtitle wording and uncertain disc/edition details need review. Matching is intentionally conservative and can need explicit aliases.
- Pickup is a geographic radius from Lyon centre (45.7640, 4.8357) and/or Mantes-la-Jolie centre (48.9900, 1.7160). No geocoder sends your location elsewhere. A manually recorded listing needs coordinates for confident pickup qualification.
- Each watch has start/end times, checking hours and an IANA timezone. Equal checking-hour boundaries mean all day. Spring DST times that do not exist are rejected. Ambiguous autumn times use the first occurrence.
- Hourly watch checks by default. Source fetch minimums are 60 minutes for Dealabs and 4 hours for Easy Cash; these are conservative app limits, not published permission or guaranteed quotas. Shared source checks serve all due watches. Check now respects limits, dates, pauses and checking hours.
- Failed or partial checks never mark existing offers as sold. Availability remains explicitly unverified or source-reported.

## Telegram

Use the official [bot tutorial](https://core.telegram.org/bots/tutorial#obtain-your-bot-token) to create a bot through @BotFather. Send your bot a message before testing. Obtain your chat ID locally using the official `getUpdates` endpoint or your trusted Telegram tooling; don't give a third-party website your token. Settings accepts the token and chat ID without displaying stored values.

Alternatively fill `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your private `.env`; environment values take precedence. Dashboard configuration is stored in the SQLite volume. Both the volume and backups therefore contain secrets and must be protected.

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

For a simple login, generate a password hash locally:

```sh
docker compose run --rm --no-deps web python -m scripts.password
```

Copy the printed `APP_PASSWORD_HASH='...'` assignment into `.env`. Keep its **single quotes** so Compose does not interpret dollar signs. Recreate services with `docker compose up -d`. Use an existing HTTPS reverse proxy or VPN for remote access; `COOKIE_SECURE=true` is appropriate only over HTTPS. The app defaults to localhost. Explicit LAN binding is possible with `BIND_ADDRESS=<server-LAN-IP>`, but configure authentication first. Router, firewall, Internet exposure and reverse proxy configuration are outside this package.

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

## Backup and restore

The backup helper uses SQLite's backup API to create a consistent snapshot while the app is running. Never copy only the live `.sqlite3` file while WAL writes are in progress.

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
