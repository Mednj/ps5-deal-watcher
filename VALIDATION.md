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
- Leboncoin: manual/native-alert fallback only. Vinted now has an experimental anonymous catalogue adapter; see the evaluation below.

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

## Vinted experimental evaluation — 2026-10-01

Three bounded live searches from the local Docker web container, 15 seconds apart:

| Elden Ring PS5 item-price ceiling | Parsed listings | Locally matched review candidates | Explicit PS5 titles |
| --- | ---: | ---: | ---: |
| EUR 49.99 | 24 | 15 | 6 |
| EUR 39.99 | 24 | 16 | 6 |
| EUR 29.99 | 24 | 11 | 4 |

All three returned experimental success with actual catalogue listings. Combined storage: 32 distinct Vinted listings, deduplicated by source ID. Existing Elden Ring watch had 18 review candidates across searches. Example: Elden Ring PS5, EUR 25 item price, https://www.vinted.fr/items/10207769844-elden-ring-ps5 . Fees, shipping, physical disc and availability remain unconfirmed; no qualifying Telegram deal alert was generated from these candidates.

Local Vinted monitoring enabled; fresh installations retain opt-in disabled default. Five-minute source minimum, maximum eight distinct game/alias queries, first page only. Forty-four automated tests pass including conservative parsing, schema failures, external URL rejection, currency filtering, local budget filtering, deduplication, and stopping on 403/429. These short tests do not establish long-term reliability or platform permission.

## Leboncoin integration — 2026-10-01

Experimental headed browser service integrated with source controls, scheduled checks, advertised-price parsing, unavailable-card detection, matching, deduplication and existing Telegram queue. 49 automated tests pass. Browser service has no published port or application data volume. Fresh deployments opt in; local source enabled.

Isolated browser probes previously returned HTTP 200 with 34/35 listing links. The integrated Compose live check was intermittent: one unrecognized HTTP 200 page with no usable cards, then HTTP 403. No listings or deal alerts were created from these failures. Source health records blocked and a 24-hour backoff. All three Compose services are healthy. This is implemented functionality with unreliable current marketplace access, not a claim of continuous working coverage.

## Persistent session test 2026-10-02
51 tests passed. First live Elden Ring PS5 EUR50 search saved five cookies but remained flagged as a challenge. After container recreation all five cookies loaded; HTTP403 remained blocked after a 12-second automatic check, with zero offers (diagnostics 78fdcd9bb748). Reviewed cipher-x-sudo/captcha-solver: its DataDome module harvests silent clearance rather than solving an interactive challenge. No third-party solver installed. Persistence verified; Leboncoin access remains unresolved.

## Interactive slider experiment — 2026-10-02
52 tests passed. Inspected the live DataDome /captcha/ frame and observed Slide right to secure your access, with .slider and .sliderTarget controls. Implemented bounded single-drag handler. Integrated live run 8218db43cc74 returned unsupported (challenge state differed). A separate live run of the same handler found the visible controls and moved the handle to the target; result was Access is temporarily restricted, zero visible cards, not_cleared. No successful clearance claimed. Handler disabled by default; profile persists. No further attempts made after the restriction.

## Slider motion and rejection diagnostics — 2026-10-02
53 tests passed. Added eased acceleration/deceleration, bounded vertical movement, variable timing and press/release pauses. No model dependencies. Added target-position verification, challenge verification HTTP status and page-state logs without URLs, cookies or response bodies.
One live test with the persisted profile (3e34a5d61f3e): initial HTTP403, slider present, target reached=true, verification response HTTP200, then Access is temporarily restricted and zero visible cards. HTTP200 is not successful clearance. Exact server rejection reason remains unknown; a missed target is ruled out in this run. Interactive attempts remain opt-in and disabled by default.

## Isolated fresh Docker profile — 2026-10-02
Run 1d7536c4f875 used /browser-data/experiments/fresh-1d7536c4f875 with zero initial cookies; original /browser-data/profile retained and app configuration unchanged. Same headed Chromium, French locale, Paris timezone, Elden Ring PS5 under EUR50 cheapest search. HTTP200, no challenge frame, 35 visible listing links, five resulting cookies. No slider attempt necessary. This is one successful search, not proof of continuous reliability or that old cookies alone caused previous blocks. Fresh profile retained separately for follow-up.

## Follow-up checks of fresh session — 2026-10-02
Reopened fresh-1d7536c4f875; five cookies loaded. Elden Ring PS5 EUR50 cheapest search returned HTTP200, no challenge frame and seven visible listing links at observation time. After a 10-second pause, newest search returned HTTP403, another challenge and zero listing links. Stopped the planned Dead Space third check after this block. No challenge attempted. Fresh-profile success was transient; this does not isolate sorting as the trigger.

## Fresh profile per search adapter — 2026-10-02
Implemented fresh and persistent modes; Compose defaults to fresh. Separate full Chromium user-data directories per search/sort, automatic close and cleanup, existing profiles preserved. 53 local tests passed (profile test module skipped locally because Playwright is container-only); two profile lifecycle tests passed in browser container including cleanup after simulated failure and preservation in persistent mode.
Three spaced live adapter calls: Elden Ring EUR50 (80a4b45658ba), Dead Space EUR20 (1d023007657e), Elden Ring EUR50 (7135de4e21b4). Each detected a challenge and returned blocked with zero accepted cards. Fresh initial cookie counts were zero. Listing links alongside challenge content are not accepted as successful clearance. No interactive attempts enabled.

## Ten-game fresh-profile batch — 2026-10-02
Requested budget99c; website upper bound rounded to EUR1. Two completed (Returnal2cards, Horizon Forbidden West3cards), seven blocked, one error (Demons Souls missing cards/empty-search evidence). Counts are unvalidated observations, not qualifying deals. Full report and JSON are adjacent to the deployment folder.

## Challenge classifier/dispatcher — 2026-10-02
54 local tests passed, profile lifecycle module skipped locally (container-only Playwright). Classification/routing coverage includes hidden frames, sliders, image sliders, image puzzles, audio, automatic browser checks, restrictions and unknown challenges. Live Returnal EUR0.99 test b9a8ed3ca846 returned HTTP200 but detected a visible image_slider; handler unsupported, zero accepted cards. No wrong slider handler or audio handler invoked. Fresh profile cleaned up. This validates the observed classification and unsupported route, not CAPTCHA clearance or exhaustive challenge recognition.

## Canvas image-slider solver — 2026-10-02
57 local tests passed; one container-only module skipped. Synthetic shaped-gap image correctly located; flat images and unsupported input sizes rejected. Live inspection found a French simple slider with zero-height canvases, revealing and correcting prior image_slider misclassification caused by unrelated images. No genuine live image puzzle solve verified. Live adapter probe encountered a page-inspection timeout; classifier now returns unknown conservatively when the page cannot be read, rather than an unhandled timeout. Solver remains optional, disabled by default.

## Local display viewer
Added view-only x11vnc and noVNC/websockify on host127.0.0.1:6080. Verified viewer HTTP200, WebSocket upgrade101, and RFB banner from the display. Existing browser profiles retained.

## Slider control discovery fix
58 tests passed, one container-only module skipped. Handler scans visible DataDome frames, recognises French/English instructions, waits four seconds for control readiness, logs unsupported reason. Regression test covers hidden first frame followed by visible controls. Live run620036bba7a3 found controls, dragged to target, received verification HTTP200, but challenge remained unknown/blocking. Control discovery validated; clearance unsuccessful.

## Three-speed drag
Updated shared slider motion to three random speeds (fast, medium, slow), random phase boundaries, bounded vertical variation and exact final target. 59 local tests passed, one skipped. Verified paths stay within the track, slow near the target, vary across seeds and finish exactly. Browser rebuilt; no live challenge acceptance claimed for this revision.

## Pre-drag pacing
Added randomized pauses before navigation (1.2-2.5s), page settling (8.5-11.5s), between searches (6-10s), before pointer approach (0.7-1.4s), and over the handle (0.6-1.2s). Approach steps are individually paced, with a brief hold after pressing. Shared three-speed drag remains. Adapter time budget raised to90s within its150s HTTP client timeout. 59 tests passed, one skipped; browser rebuilt. No live clearance claim for this revision.

## Manual CAPTCHA comparison
Run90c5b7e9a95f used a fresh Docker profile, homepage navigation and no automated solver. User manually completed the CAPTCHA in local interactive noVNC and reported Access temporarily restricted afterward. Automated pointer motion therefore is not necessary for the observed restriction. This does not isolate browser, network or server risk-scoring factors or prove manual challenge acceptance.

## Ordinary Chromium baseline — 2026-10-02
Run9b4851d8941e launched /usr/bin/chromium in the same Docker/Xvfb environment with a separate fresh profile, no Playwright, no debugging port and no solver. User reported homepage works without CAPTCHA; initial cookie-consent popup present. Docker/Xvfb alone is therefore not sufficient to produce a challenge in this run. Comparison implicates Playwright launch configuration, attachment or interaction as hypotheses, without isolating them or proving repeatability. Browser retained for manual follow-up.

## Normal launch then Playwright attachment — 2026-10-02
Run02ac88fc857a copied the successful manual ordinary Chromium profile into a separate attached test profile, preserving the reference. Chromium launched directly with an internal localhost debugging port and without Playwright launch flags; Playwright attached after15seconds. Homepage remained unchallenged. Exact Lyon SpiderMan2 search via Playwright returned HTTP200, no challenge after15seconds, and15visible listing links. No solver ran. This demonstrates that attachment need not immediately cause a block in this session; launch configuration and established working session are not yet isolated.

## Twenty consecutive searches
Runbf34e6c3b00f: normal Chromium direct launch, Playwright CDP attachment, copied working session reused;20PS5 game searches aroundLyon. All20HTTP200, no detected challenge, visible listings11-35perpage. No solver or added inter-search delay;10ssettling perpage. Successful configuration includes both normal launch and working session; causality not isolated. Full report and rawJSON adjacent to deployment folder.

## Deployed normal-launch adapter
Integrated ordinary Chromium launch plus private loopback CDP attachment into browser_profile; persistent app-profile is default. Local app profile copied from successful20-test session, with references preserved.63tests passed, including profile lifecycle and owned-process cleanup on attachment failure. Rebuilt web,worker,browser; all healthy. Actual app.sources.check_leboncoin performed cheapest/newest checks for Elden Ring EUR50 and Dead Space EUR20, parsed16listings and stored them through normal matching; live browser runbd279ad11f6e. No challenge detected. Source enabled, old failure count cleared, next check scheduled after minimum300s. Cookies remain private and are excluded from ZIP.

## Immediate manual checks — 2026-10-02
65 tests passed. Check now queues a worker pass with roughly one-second idle wakeup, checks all sources selected by active unexpired watches concurrently, and bypasses watch hours/start date, polling enablement and source cooldown for that pass. Repeated clicks coalesce; an existing check must finish before the queued pass starts. Manual qualifying events can deliver outside watch checking hours; global quiet hours, freshness and successful-notification deduplication remain. Manual passes do not evaluate old cached listings from failed sources. Docker live pass started all four source runs at the same timestamp and returned Dealabs29, Vinted96, EasyCash30 and Leboncoin19 listings. Rebuilt web and worker after final cache guard.

## Independent monitoring — 2026-10-02
Added monitor service, bounded seven-day samples, incident state with failure/recovery deduplication and retry, authenticated dashboard, source duration/rate statistics and Telegram delay tracking. Long concurrent source waits now refresh worker heartbeat every 15 seconds; stuck-run detection remains independent. 69 tests passed; final schedule/dedup guards passed six targeted monitoring/manual-check tests. Tests simulate health outage debounce, recovery, failed alert retry, zero-result success, quiet-hour timer reset, stuck checks, retention and dashboard authentication. Docker web/worker/monitor rebuilt; all four services healthy and live Monitoring page HTTP200 with rendered metrics. No production outage was induced and no claim of live outage-alert delivery is made.

Monitoring also exposed a stale scheduler lease after Docker redeployment. Worker startup now marks orphaned checks interrupted, releases scheduler/source leases, requeues affected sources and interrupted manual passes, and refreshes heartbeat. This assumes the supplied Compose topology with exactly one worker; do not scale worker replicas. Delivery leases remain intact. Full final suite:70passed. Redeployed web,worker,monitor with restart recovery.

## Leboncoin five-page pagination — 2026-10-02
Saved pre-expansion checkpoint c9d47ad and a separate SQLite snapshot at work/private-backups/watcher-2026-10-02-pre-pagination.sqlite3 (PRAGMA integrity_check: ok; database contains private settings and must stay local). Pagination is capped at five pages for each of cheapest and newest, per distinct active search; up to four searches means at most 40 pages. Pages stop early on empty/repeated fingerprints and IDs are canonicalized/deduplicated across sort orders. Later-page challenges or missing cards fail the whole source pass and return no partial items, preserving prior listings. Client/browser/source budgets are bounded for the larger pass, worker leases renew while active, monitoring uses the source-specific timeout, and the next watch interval is scheduled from completion to avoid catch-up loops.

Fifteen pagination/source/monitor tests passed before final worker schedule adjustment; seventeen pagination/source/monitor/manual-check tests passed after it. Docker build and Compose configuration succeeded. Direct live Leboncoin test for Elden Ring PS5, €50 budget: HTTP200, all 10 requested pages fetched, 35 cards on nine pages and 34 on newest page2, 230 unique cards, 138.7 seconds, no challenge detected. A separate live four-query app pass stopped on the first query's page2 because it had no readable cards and no confirmed empty state; it was correctly reported as error with zero new items. This confirms pagination works on the direct successful query while grouped searches can still fail on source markup variation. Current requirements are capped page depth and returned cards; no claim that every matching listing is captured.
