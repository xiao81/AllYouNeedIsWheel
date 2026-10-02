# Wheel user guide

Start with the [quick setup](../README.md). All connection settings are managed in the dashboard.

## Connection details

The broker app must already be logged into the matching account/session. Selecting
Paper in Wheel chooses a connection profile; it does not convert a live broker
session into a paper session. No brokerage username or password is stored here.

| Application | Paper default port | Live default port |
| --- | --- | --- |
| Trader Workstation | 7497 | 7496 |
| IB Gateway | 4002 | 4001 |

Ports are configurable in IBKR. Read-only mode is enabled for a new setup. It allows research and local drafts,
but blocks broker submissions. Cancel submitted orders directly in TWS or IB Gateway.
The client ID field is used by the connection test. Data/order connections use
separate IDs, saved with submitted orders for status reconciliation.

Settings are stored in `settings.json`, excluded from Git. Existing
`connection.json` / `connection_real.json` profiles are imported on first save,
including their database paths. Existing files are not overwritten. New setups use
separate paper/live SQLite databases. Saved Settings take precedence over legacy
connection files. A custom `CONNECTION_CONFIG` path remains supported until
Settings have been saved. `--realmoney` selects and persists the Live profile.

## Research and orders

- **Overview:** account metrics, saved symbols, option discovery, and order queue.
- **Watchlist scanner:** uses independent **Sell-put** and **Covered-call** watchlists
  saved in this browser (up to 20 symbols per scan). Add several tickers with
  commas or spaces, remove them with **Remove**, or use **Replace with holdings** to replace
  the active list. The original `customTickers` put cache is migrated automatically;
  the redesign's `wheel.watchlist` is used if that cache is absent. Covered calls
  start from your holdings, then remain independently editable. Removed symbols
  stay removed; inspecting a single symbol does not modify either list. Three symbols scan concurrently with a shared cap
  of eight option requests. Select an expiration and delta range once; each group
  lists all matches found for that symbol, with the best quoted candidate marked. An explicitly selected date
  is never substituted. Completed symbols appear immediately with a progress
  counter while the rest load; edited selections and quantities are preserved.
  Errors and unavailable contracts appear per symbol. Contracts are displayed in
  ascending strike order while the best-match label follows the delta ranking.
- **Strike distance:** each row shows how far its strike is above or below the
  displayed stock quote. Short puts also show breakeven at expiry (strike minus
  quoted midpoint), before fees. Distance to the put strike is not maximum loss.
  Contracts without valid bid/ask quotes are hidden and counted per symbol.
- **Candidate ranking:** usable two-sided quotes closest to the midpoint of the
  selected absolute-delta range come first. Ties prefer a smaller relative
  bid–ask spread, then a higher bid. This is the best match among contracts
  checked by the bounded scanner, not an exhaustive-chain or return guarantee.
- **Bulk drafts:** each symbol’s best quoted candidate is preselected. Put drafts remember the last quantity per symbol in this browser, initially
  1 contract. Call drafts default to one contract per 100 shares held, without
  subtracting existing short calls (minimum default 1; quantities remain editable). All
  matches are visible on the same page. Select any contracts, edit quantities, or deselect rows, then use **Add selected to queue** to save the whole selection atomically. This does not send broker
  orders. Share coverage is informational and never blocks saving drafts.
  Each contract also has **Add to queue** for an individual draft.
  **Single symbol** mode remains available for inspecting the full match list.
- **Default discovery:** the Friday after the upcoming Friday in New York time, with absolute delta
  **0.05–0.10**, ranked around **0.075**. The upcoming Friday rolls forward at
  4 p.m. New York time; the default is one week after that date. A stock already in the portfolio
  or saved symbols are scanned automatically on initial load.
- **Expiration fallback:** if the target Friday is not listed, prefer a listed
  expiration earlier in that target week (such as a holiday Thursday), otherwise
  the next available expiration. The UI identifies the adjustment.
- **No matching data:** contracts without a usable broker delta are excluded.
  The scanner does not substitute estimated Greeks or show an out-of-range
  contract as a match. A bounded search can miss matches on irregular chains;
  widen the range or choose another expiration if necessary.
- **Quotes:** option prices and saved limits are per share; gross contract premium
  is price × 100 × quantity. A midpoint is not a guaranteed fill.
- **Order queue:** Add saves a local draft immediately, with no broker call or confirmation.
  Quantities and prices are stored locally; prices use two decimals. Submit checks
  IBKR's contract-specific tick sizes before showing the final review. Sell limits
  round up and buy limits round down when needed. No order is sent before confirmation.
  Queue reads display immediately; broker reconciliation runs in the background.
  Requests are not automatically retried. Sell-put assignment cost is strike × 100 × contracts,
  before subtracting premium received.
- **Portfolio:** Option positions have an expiration calendar and signed contract delta
  (not quantity-adjusted portfolio delta). All expirations are shown initially.
  Date filtering is local. Delta loads separately; unavailable broker Greeks display a dash.
- **Rollover:** creates two drafts atomically in SQLite, both using per-share
  limits. They are independent broker orders, not a combo spread. Close the
  existing position and confirm the fill before submitting the opening leg.
- **Weekly entry premium:** the total entry premium of currently held short options
  expiring through the coming Friday; it is not realized profit or a forecast.

**Cancel all** removes only unsubmitted local drafts. Cancel broker orders in TWS
or IB Gateway. **Remove local record** deletes a stale record after confirmation;
it does not contact IBKR or cancel an order. An uncertain submission remains
visible for manual verification and cannot be submitted again as a draft.

## Troubleshooting

- **Cannot connect:** keep TWS/Gateway logged in; match the port and Paper/Live
  profile; enable socket clients in the broker's API settings.
- **Port 8000 in use:** stop an earlier Wheel process, or use
  `PORT=8080 python run_api.py` on macOS/Linux and open port 8080 in the browser.
- **Missing quotes/delta:** check market-data subscriptions and broker availability.
  Wheel displays unavailable data as a dash, not an estimated value.
- **A submitted order is missing:** inspect TWS before retrying. A local order ID
  alone is not proof that the broker accepted the order.

## Performance and implementation

The frontend uses native JavaScript modules and local CSS, with no build step,
Bootstrap, external fonts, or chart-library downloads. It deduplicates concurrent
reads and polls broker status only while there are working/canceling orders.

The scanner qualifies and quotes contracts concurrently with a cap of **8 active
option requests**, shared across simultaneous symbol scans. It probes the OTM chain and refines around the delta band, with
at most **36 contracts per scan**. Metadata is cached for an hour, qualified
contracts are reused, and identical scan results are cached for 10 seconds. Find
options explicitly refreshes quotes. Portfolio reads share a three-second snapshot.

Each server process runs broker work on one dedicated thread/event loop. The
server defaults to one process and four HTTP threads to share caches and avoid
using IB objects from different request threads. `PORT=8080 python run_api.py`
changes the HTTP port. The server binds to localhost; remote hosting would need
its own authentication and access controls.

See [architecture and reference notes](architecture.md) for the ThetaGang
reference, scanner limits, concurrency, and order-state decisions.

## Tests

Backend tests use temporary databases and prohibit real broker connections:

```sh
python -m unittest discover -s tests -v
```

Browser regression tests need Node.js, Playwright, and a browser. In one terminal:

```sh
python tests/preview.py
```

In another, point `WHEEL_NODE_MODULES` at the directory containing the installed
`playwright` package, then run:

```sh
WHEEL_NODE_MODULES=/path/to/node_modules node tests/ui.cjs
# Set WHEEL_BROWSER_CHANNEL=chrome to use installed Google Chrome.
```

The preview uses an isolated temporary configuration and blocks broker connections.
Browser tests intercept all API requests with fixtures, test desktop/mobile layouts,
and write screenshots to `/tmp/wheel-ui`. They never modify actual account settings
or send orders. Live broker latency, subscriptions, and fills require separate
verification; offline tests do not demonstrate live trading performance.

## API

- `GET /api/settings`, `PUT /api/settings`, `POST /api/settings/test`
- `GET /api/portfolio/`, `/api/portfolio/positions`, `/api/portfolio/position-deltas`, `/api/portfolio/weekly-income`
- `GET /api/options/scan?ticker=AAPL&type=PUT&delta_min=0.05&delta_max=0.10`
- `GET /api/options/scan-batch?tickers=AAPL,MSFT&type=PUT&stream=true`
- `GET /api/options/expirations?ticker=AAPL`
- `GET /api/options/pending-orders`
- `POST /api/options/order`, `/api/options/execute/<id>`, `/api/options/cancel/<id>`
- `POST /api/options/orders/batch`, `/api/options/orders/prepare-submission`
- `DELETE /api/options/order/<id>/draft`
- `DELETE /api/options/order/<id>/local` (requires `confirm_local_only: true`)
- `PUT /api/options/order/<id>/quantity`
- `POST /api/options/rollover`, `/api/options/check-orders`

Order mutations require the `X-Wheel-Profile` header matching `revision` from
`GET /api/settings`. This prevents an old tab from acting on an order ID in a
newly selected account/database. Cross-origin mutations are rejected. Legacy OTM
and stock-price endpoints remain available, the scanner uses `/scan` for individual symbols and `/scan-batch` for watchlists.


## Documentation screenshots

Start the isolated preview described above, then run `node tests/screenshots.cjs`
with the same Playwright environment variables. It uses a fresh browser and
invented instruments, balances, positions, and orders. All API requests are mocked;
external requests and mutations are blocked. Images are written to `docs/images`.
Never generate documentation screenshots from a live-account browser session.
