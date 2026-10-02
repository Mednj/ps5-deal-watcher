# Source feasibility

Last verified: **2026-10-01**, Windows PC in France and local Docker Linux/amd64. Re-verify from the eventual server; local availability is not server proof. Probes used an explicit personal-reader user agent, no source login and no bypass.

## Dealabs — verified working (public RSS)

- Method: HTTP GET of [PS5 RSS](https://www.dealabs.com/rss/groupe/jeux-playstation-5), XML item fields, Pepper merchant-price extension, original Dealabs links. Local genuine feed returned HTTP 200 and 29 priced entries in the initial snapshot.
- [robots.txt](https://www.dealabs.com/robots.txt) fetched HTTP 200: general readers may access the feed; search/private API routes are restricted. The app checks robots before each bounded fetch. No search or merchant clickout endpoint is used.
- The [public PS5 group](https://www.dealabs.com/groupe/jeux-playstation-5) returned HTTP 200 during feasibility inspection. The production adapter uses RSS only.
- Authentication: none. No documented public listing API integration was found/used.
- Coverage: current feed window, capped at 100 parsed entries. No pagination or exhaustive historical lookup; no merchant stock revalidation. Terms/help documentation was inspected through the supplied group and [official help](https://help.dealabs.com/help/comment-fonctionne-dealabs); attempts at generic terms URLs were unsuccessful. No broader scraping permission is inferred from robots or feed access.
- Costs: merchant price parsed in integer cents. Explicit free delivery or shipping amount is recorded; fees remain unknown unless explicitly stated. Disc format, condition and availability often remain unknown. Such entries are candidates, not confident alerts.
- Rate limits: no published quota confirmed. App minimum is 5 minutes plus jitter; respects 429/Retry-After, timeout and circuit backoff.
- Fallback: native Dealabs alerts and manual listing entry.

## Leboncoin — experimental headed Docker browser

- Dedicated internal browser service runs normal headed Chromium with Xvfb. No source credentials, proxy rotation, stealth patches or CAPTCHA solving. The browser's sandbox remains enabled; no public port or data volume is exposed.
- Active game/alias searches append PS5, use advertised-item budgets, and fetch first-page cheapest and newest listings (up to 35 cards each), deduplicated by listing ID. Maximum 4 distinct searches per check; 5-minute source minimum.
- Parses displayed card title, advertised item price and URL. Fees/disc remain unknown; source-reported purchase-in-progress listings are unavailable. Name + price mode can still match exchanges, empty cases or related games; inspect alerts.
- HTTP 403 stops the check, 429 backs off; unrecognized pages are errors rather than empty successful results. No exhaustive coverage or ongoing availability guarantee.
- Anonymous Docker headed access was proven in short live tests, but extended reliability and access from the eventual server remain unproven. Previously inspected marketplace terms restrict external collection; technical success does not establish platform permission.
- Disabled by default in fresh deployments; enabled locally at the user's request for evaluation. Toggle it from Sources.

## Vinted — experimental anonymous catalogue

- Method: anonymous session on vinted.fr, followed by fixed api.vinted.fr/svc-catalogue/items requests. Independently implemented after inspecting VintedScanner; no third-party scanner code or dependencies included.
- Searches: active configured game titles and explicit aliases with PS5 appended; cheapest and newest ordering, EUR item-price budget, first 24 results in each ordering, deduplicated, maximum 8 distinct queries per check. Search is fuzzy; local matching remains authoritative. No exhaustive coverage claim.
- No login, personal cookies, proxy rotation, challenge solving or access-denial bypass. Anonymous cookies exist only during each bounded check. HTTP 403 stops access; 429 respects Retry-After. Minimum 5 minutes with scheduler backoff.
- Catalogue does not confirm physical disc, shipping, delivery, pickup or checkout fees. These remain unknown. Name + price mode permits alerts at advertised item prices; detailed mode retains review candidates. Advertised total_item_price is not assumed to be a delivered total.
- Independent, undocumented integration. Vinted does not endorse it; endpoints can change. The previously inspected terms restrict external collection; this experimental implementation does not establish platform permission.
- Disabled by default in fresh deployments; enabled locally for evaluation at the user's request. Source controls allow disabling it.

## Easy Cash — experimental catalogue candidates

- Method: HTTP GET of the [supplied PS5 catalogue](https://bons-plans.easycash.fr/jeux-video/sony/ps5); 200, 30 priced product cards in the initial real snapshot. Each card uses its own `.infos-price-number`, not the category's aggregate offer or the first price on the page.
- [robots.txt](https://bons-plans.easycash.fr/robots.txt) returned 200. Supplied public category path is allowed for general readers; `/api/`, `/catalog/`, search, buybox and several query routes are restricted and not used.
- [Legal information](https://www.easycash.fr/mentions-et-conditions/mentions-legales) returned 200 locally. [Sale/repurchase terms](https://www.easycash.fr/mentions-et-conditions/conditions-generales-de-vente-et-de-rachat) are linked for the user's review. No documented feed/API or explicit permission for broader automated offer collection was established. This adapter remains experimental and disabled by default.
- One public product page was inspected and returned 200; its shop-specific offer/buybox flow was not traversed. The catalogue's JSON-LD includes an aggregate category low price and must not be treated as an individual game price.
- Coverage: first page only; reference/product IDs across multiple shop offers, not stable individual shop inventory. “À partir de” stays `price_kind=from`; physical format, shipping, fees, pickup and actual availability are unconfirmed. Detailed mode retains review candidates; name + price mode may alert on advertised catalogue prices.
- Authentication: none for the bounded public page. No shop/customer/private endpoints are used.
- Rate limits: no published quota confirmed; app minimum 4 hours, jitter, Retry-After and error backoff. No dynamic sort/search/pagination requests.
- Fallback: open the product page, select a genuine offer yourself, then manually record its full details.

## Common behavior

Supported outbound hosts are fixed by source. Redirects outside the source allowlist, non-HTTPS destinations and source credentials in URLs are refused. Responses have size/time limits. RSS parse failure, challenge page, 403 and 429 have explicit failure statuses; they are never successful empty results. After repeated failures the circuit waits at least 24 hours. Shared fetches avoid multiplying requests by watch count. No search-engine snippets are substituted for listings.

Manual entries are labelled `manual entry` and `availability=unverified`. They are not proof of automatic source support. Native alerts are configured by the user at each source and are not ingested in version 0.1.0.
