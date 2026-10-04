# Suggested next improvements

These improvements do not change the current game-name/price qualification rules. Items marked implemented are now part of the app.

1. **Verify shortlisted offers before notification.** Fetch only promising listing detail pages, with bounded requests and caching. Check availability, actual sale price, platform, edition and delivery costs. Keep unknown costs explicit. This reduces stale catalogue offers and misleading “from” prices, but adds latency and source traffic.
2. **Add optional exclusions to name/price mode.** Let each watch exclude “empty box”, exchange, account, DLC and unwanted editions, independently of strict mode. Preserve current defaults. Show the exact reason for exclusions; avoid silently changing what qualifies.
3. **Expand search coverage with limits.** Keep newest plus cheapest searches, add bounded pagination with overlap and deduplicate IDs. Track pages scanned and coverage limits in the dashboard. Dealabs RSS covers recent entries; a separate supported targeted-search adapter would need investigation and live validation.
4. **Separate notification delivery from collection.** A dedicated delivery process would keep retrying Telegram while a slow marketplace check is still running. Retain transactional claiming and the outbox. Telegram cannot guarantee exactly-once delivery after an uncertain network response.
5. **Backup restore drill (implemented).** New snapshots are restored into a disposable database and checked before being marked healthy. Remaining work: copy rotating backups off-host, test restoring off-host copies, protect credentials, and add a disk-space alarm.
6. **Record safe diagnostics for parser regressions (implemented).** Synthetic, redacted contract fixtures cover each adapter, explicit empty responses, challenges, and unrecognized formats. `challenge` and `format-change` are recorded separately in source health and Activity; neither ingests listings. A valid parsed empty response remains a successful check. No raw response body, cookies, or tokens are saved.
7. **Maintain historical listing availability.** Show last observation time, mark stale listings visibly and periodically revalidate shortlisted items. Missing from one search page alone does not mean sold.
8. **External uptime probe (implemented).** A scheduled GitHub-hosted check probes the public app every 15 minutes, independently of the Docker host. Local Telegram monitoring still cannot independently verify a Telegram outage; scheduled Actions may be delayed under load.

Recommended remaining order: shortlist verification and optional exclusions for accuracy; separate delivery for resilience; then broader search coverage. Copying verified backups off-host remains a resilience priority.
