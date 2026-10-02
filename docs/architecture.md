# Architecture and reference notes

## ThetaGang reference

Reviewed `brndnmtthws/thetagang` at commit `60e84d7`:

- [IBKR integration](https://github.com/brndnmtthws/thetagang/blob/60e84d7/thetagang/ibkr.py):
  concurrent contract qualification, required/optional ticker fields, bounded
  market-data concurrency, event-based field waits, and subscription cleanup.
- [Project documentation](https://github.com/brndnmtthws/thetagang): broader CLI
  portfolio automation and wheel workflows.
- [IBKR's TWS/Gateway comparison](https://www.interactivebrokers.com/campus/trading-lessons/installing-configuring-tws-for-the-api/):
  API compatibility and the resource advantages of Gateway.

These informed the design; ThetaGang source was not copied or vendored. Wheel's
scanner is an independent implementation tailored to an interactive Flask app.

## Scanner

`core/option_scanner.py` owns metadata, qualification, quote caching, and selection.
A scan requests one stock stream, discovers standard SMART option-chain metadata,
and keeps that underlying stream alive while collecting option Greeks.

Up to 12 initial OTM strike probes cover the chain with denser sampling near ATM.
Up to three rounds refine intervals that overlap the requested delta band, with a
hard total budget of 36 contracts. An eight-slot semaphore covers qualification
and quote subscriptions. Quotes wait for finite Greeks and a valid bid/ask via
update events, with a three-second per-quote deadline. Qualification and metadata
also have deadlines. All owned streams are canceled in `finally` blocks.

Contracts with missing or wrong-sign deltas are not matches. Matches with missing
two-sided prices are hidden and counted. Quotes cache for ten
seconds; metadata caches for an hour; qualification keys include trading class.
Caches are bounded to avoid unbounded growth when many symbols are searched.
This is a bounded heuristic, not an exhaustive proof that no matching strike exists.
Exchange-listed expirations determine Friday fallback. The market-hours helper
currently distinguishes weekends and regular New York session hours; it does not
have a full exchange holiday/early-close calendar.

## Connection ownership and HTTP concurrency

Flask views run broker work on one dedicated executor thread per process with a
stable asyncio loop. HTTP threads do not call an IB instance concurrently from
different event loops. Chain requests are asynchronous within that broker loop;
requests for different scans are serialized. The one-process default maximizes
cache reuse. A separate portfolio service shares short-lived snapshots between
summary, positions, and weekly-premium requests.

Settings are checked inside the executor immediately before each API action.
Changes disconnect old service connections, replace the configuration, and select
the appropriate database. A profile revision accompanies frontend mutations and
is revalidated after queueing. Stale tabs cannot accidentally submit matching local
order IDs in a newly selected database. This revision is a consistency check, not
an authentication token. Wheel is a local app.

## Order lifecycle

Saved orders carry explicit `order_type` and per-share `limit_price`. Legacy
limits may use their stored premium, but missing prices fail validation; neither
the UI nor the submission service invents a limit from the strike price.

An atomic SQLite update claims `pending → submitting` before broker submission.
A second HTTP request cannot claim the same draft. Pre-submission validation does
not change the state. Ambiguous outcomes are held for manual verification, never
automatically retried. Broker client ID and permanent ID are stored for identity.
Status reconciliation fetches open/completed trades once per batch and reads
commissions from fill reports, not nonexistent OrderStatus attributes.

Draft create/read/update/remove endpoints bypass the broker executor and use a
request-scoped profile/database snapshot. Drafts normalize prices to two decimals
locally. Submission preparation verifies exchange tick rules before the final
review; it updates still-pending draft prices atomically. Execute checks the reviewed
snapshot and broker tick rules again without silently changing the confirmed limit.
The submit path waits for broker status, not merely a locally assigned order ID.

Dashboard cancellation removes drafts only; working orders are managed in IBKR.
Absence from a broker snapshot is not proof of a fill or cancellation. Broker history
may be limited after restarts; records with incomplete identity require TWS checks.
A crash after claiming an order may leave it in `submitting`, requiring manual
broker verification. Broker submission and SQLite persistence are not a distributed
transaction; the UI explicitly treats ambiguous outcomes as unresolved.

Rollover legs are saved in a single SQLite transaction, but are submitted
independently. No atomic combo execution or automatic leg sequencing is implied.

## Verification

The regression suite covers atomic order claiming, rollover rollback, per-share
price persistence, stale-profile rejection, cancellation failure, read-only
submission blocking, uncertain outcomes, delta filtering, bounded concurrency,
cache reuse, subscription cleanup, and Friday date selection. Browser tests use
intercepted API fixtures to exercise the actual templates and modules, including
error states and mobile layouts. No tests connect to the user's broker.
