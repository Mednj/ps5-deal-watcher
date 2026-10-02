# Suggested next improvements

These are proposals, not changes to the current game-name/price qualification rules.

1. **Verify shortlisted offers before notification.** Fetch only promising listing detail pages, with bounded requests and caching. Check availability, actual sale price, platform, edition and delivery costs. Keep unknown costs explicit. This reduces stale catalogue offers and misleading “from” prices, but adds latency and source traffic.
2. **Add optional exclusions to name/price mode.** Let each watch exclude “empty box”, exchange, account, DLC and unwanted editions, independently of strict mode. Preserve current defaults. Show the exact reason for exclusions; avoid silently changing what qualifies.
3. **Expand search coverage with limits.** Keep newest plus cheapest searches, add bounded pagination with overlap and deduplicate IDs. Track pages scanned and coverage limits in the dashboard. Dealabs RSS covers recent entries; a separate supported targeted-search adapter would need investigation and live validation.
4. **Separate notification delivery from collection.** A dedicated delivery process would keep retrying Telegram while a slow marketplace check is still running. Retain transactional claiming and the outbox. Telegram cannot guarantee exactly-once delivery after an uncertain network response.
5. **Back up and test restoration.** Use SQLite's online backup API, retain rotating backups outside the data volume, and test restoring watches, settings and deduplication history. Protect the credentials in backups. Add a disk-space alarm.
6. **Record safe diagnostics for parser regressions.** Keep bounded, redacted fixtures for unexpected page formats; test each adapter against these. Distinguish a legitimate empty search from unreadable response markup. Never store Telegram tokens, browser cookies or full sensitive response headers.
7. **Maintain historical listing availability.** Show last observation time, mark stale listings visibly and periodically revalidate shortlisted items. Missing from one search page alone does not mean sold.
8. **Add external uptime monitoring.** A second machine can detect Docker-host/network outages. Local Telegram monitoring cannot report the host's total failure or independently verify a Telegram outage.

Recommended order: shortlist verification and optional exclusions for accuracy; separate delivery and tested backups for resilience; then broader coverage and external uptime monitoring.
