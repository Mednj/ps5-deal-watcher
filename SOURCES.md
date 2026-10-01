# Source feasibility

Last verified: **2026-10-01**, Windows PC in France and local Docker Linux/amd64. Re-verify from the eventual server; local availability is not server proof. Probes used an explicit personal-reader user agent, no source login and no bypass.

## Dealabs — verified working (public RSS)

- Method: HTTP GET of [PS5 RSS](https://www.dealabs.com/rss/groupe/jeux-playstation-5), XML item fields, Pepper merchant-price extension, original Dealabs links. Local genuine feed returned HTTP 200 and 29 priced entries in the initial snapshot.
- [robots.txt](https://www.dealabs.com/robots.txt) fetched HTTP 200: general readers may access the feed; search/private API routes are restricted. The app checks robots before each bounded fetch. No search or merchant clickout endpoint is used.
- The [public PS5 group](https://www.dealabs.com/groupe/jeux-playstation-5) returned HTTP 200 during feasibility inspection. The production adapter uses RSS only.
- Authentication: none. No documented public listing API integration was found/used.
- Coverage: current feed window, capped at 100 parsed entries. No pagination or exhaustive historical lookup; no merchant stock revalidation. Terms/help documentation was inspected through the supplied group and [official help](https://help.dealabs.com/help/comment-fonctionne-dealabs); attempts at generic terms URLs were unsuccessful. No broader scraping permission is inferred from robots or feed access.
- Costs: merchant price parsed in integer cents. Explicit free delivery or shipping amount is recorded; fees remain unknown unless explicitly stated. Disc format, condition and availability often remain unknown. Such entries are candidates, not confident alerts.
- Rate limits: no published quota confirmed. App minimum is 60 minutes plus jitter; respects 429/Retry-After, timeout and circuit backoff.
- Fallback: native Dealabs alerts and manual listing entry.

## Leboncoin — blocked for direct monitoring

- [robots.txt](https://www.leboncoin.fr/robots.txt) returned HTTP 200 with an explicit restriction on automatic collection. The app does not crawl the supplied search route.
- [Current terms](https://www.leboncoin.fr/dc/cgu), article 10.2, restrict robot-based collection without prior permission. This was readable through the web research tool; a local GET returned HTTP 403. No access denial was bypassed.
- Method: no automated adapter. UI links to the supplied public category for the user to configure native searches. Manual recording of an offer does not fetch its URL.
- Authentication: the user's own account may be needed for native saved searches; the app never asks for Leboncoin credentials.
- Coverage/rate limits: no direct polling, therefore no automated coverage or quota claim. No authorized public API integration identified.
- Fallback: native saved-search alerts; manually add a listing with prices, format and delivery/pickup evidence. Email alert ingestion is not implemented.

## Vinted — blocked for direct monitoring

- [robots.txt](https://www.vinted.fr/robots.txt) returned HTTP 200 and permits some public discovery, but robots is not the sole condition.
- [Current terms](https://www.vinted.fr/terms-and-conditions) returned HTTP 200 and contain restrictions on external scraping/crawling tools and data collection. The older [terms URL](https://www.vinted.fr/terms_and_conditions) was a generic shell during inspection; the current route was checked separately.
- A single feasibility GET of [the supplied catalogue](https://www.vinted.fr/catalog/3026) loaded public item cards. This does **not** make monitoring authorized or PS5-specific; observed cards included PS1/DS and other platforms. No ongoing adapter was enabled.
- Authentication: native saved searches may need the user's account; the app stores no Vinted cookies/login credentials.
- Coverage/rate limits: no direct polling. No authorized public feed/API integration identified.
- Fallback: native alerts and manual listing entry. Shipping and mandatory fees are not guessed from advertised item prices.

## Easy Cash — experimental catalogue candidates

- Method: HTTP GET of the [supplied PS5 catalogue](https://bons-plans.easycash.fr/jeux-video/sony/ps5); 200, 30 priced product cards in the initial real snapshot. Each card uses its own `.infos-price-number`, not the category's aggregate offer or the first price on the page.
- [robots.txt](https://bons-plans.easycash.fr/robots.txt) returned 200. Supplied public category path is allowed for general readers; `/api/`, `/catalog/`, search, buybox and several query routes are restricted and not used.
- [Legal information](https://www.easycash.fr/mentions-et-conditions/mentions-legales) returned 200 locally. [Sale/repurchase terms](https://www.easycash.fr/mentions-et-conditions/conditions-generales-de-vente-et-de-rachat) are linked for the user's review. No documented feed/API or explicit permission for broader automated offer collection was established. This adapter remains experimental and disabled by default.
- One public product page was inspected and returned 200; its shop-specific offer/buybox flow was not traversed. The catalogue's JSON-LD includes an aggregate category low price and must not be treated as an individual game price.
- Coverage: first page only; reference/product IDs across multiple shop offers, not stable individual shop inventory. “À partir de” stays `price_kind=from`; physical format, shipping, fees, pickup and actual availability are unconfirmed. **Never alerts from catalogue prices.**
- Authentication: none for the bounded public page. No shop/customer/private endpoints are used.
- Rate limits: no published quota confirmed; app minimum 4 hours, jitter, Retry-After and error backoff. No dynamic sort/search/pagination requests.
- Fallback: open the product page, select a genuine offer yourself, then manually record its full details.

## Common behavior

Supported outbound hosts are fixed by source. Redirects outside the source allowlist, non-HTTPS destinations and source credentials in URLs are refused. Responses have size/time limits. RSS parse failure, challenge page, 403 and 429 have explicit failure statuses; they are never successful empty results. After repeated failures the circuit waits at least 24 hours. Shared fetches avoid multiplying requests by watch count. No search-engine snippets are substituted for listings.

Manual entries are labelled `manual entry` and `availability=unverified`. They are not proof of automatic source support. Native alerts are configured by the user at each source and are not ingested in version 0.1.0.
