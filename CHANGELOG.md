# Changelog

## 2.0.0

A redesigned dashboard and a new options-scanning and order workflow.

### Dashboard and setup

- Dark-first interface with an optional light theme, larger type, and aligned numeric tables.
- Dashboard settings for Paper/Live accounts, TWS/IB Gateway, and connection testing; no manual JSON setup.
- Separate, collapsible browser watchlists for puts and covered calls; remembered put quantities per symbol.
- Portfolio expiration calendar and contract delta, loaded separately from positions.
- New documentation screenshots generated entirely from fictional data.

### Options and orders

- All watchlist symbols on one page, with bounded concurrent scans and results shown as symbols finish.
- Animated per-symbol loading indicators, strike-sorted results, IV, and best-match selection.
- Default expiration is the Friday after the upcoming Friday; absolute delta defaults to 0.05–0.10.
- Strike distance and put breakeven in scan results; assignment cost in sell-put order reviews.
- Local-only single, bulk, and rollover drafts, without confirmation dialogs or broker calls.
- Two-decimal draft prices; contract-specific tick checks before submission review.
- Bulk submission with confirmation and stop-on-failure behavior; atomic protection against duplicate submission.
- Broker acknowledgment and rejection handling; uncertain outcomes require manual verification.
- Fast local queue refresh with broker status reconciliation in the background.
- Covered-call quantity defaults follow holdings; coverage information does not block drafts.

### Upgrade notes

- The frontend has been replaced. Hard-refresh your browser after updating.
- Existing connection JSON files remain supported; saving dashboard settings creates an ignored local `settings.json`.
- SQLite schemas migrate automatically. Back up your local database and settings before upgrading.
- Browser watchlists are migrated where supported. Local data is not part of the release.
- Submitted orders must be canceled in TWS/IB Gateway. Removing a local record does not cancel a broker order.
- Rollover legs remain independent orders: confirm the closing fill before submitting the opening leg.

### Validation

Backend regressions use temporary databases and mocked broker connections. Browser
regressions and screenshot generation intercept APIs with fictional fixtures.
These checks do not certify live fills, broker permissions, or exchange availability.
