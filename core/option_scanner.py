"""Bounded, asynchronous option discovery using IB market-data events.

This module is an independent implementation. See docs/architecture.md for the
ThetaGang patterns used as a reference. Broker prices are always per share.
"""

import asyncio
import math
import time
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from ib_async import Stock, Option
from core.pricing import cents


def finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def coming_friday(now=None):
    now = now or datetime.now(ZoneInfo("America/New_York"))
    days = (4 - now.weekday()) % 7
    if days == 0 and now.hour >= 16:
        days = 7
    return (now.date() + timedelta(days=days)).strftime("%Y%m%d")


def following_friday(now=None):
    return (
        datetime.strptime(coming_friday(now), "%Y%m%d") + timedelta(days=7)
    ).strftime("%Y%m%d")


def choose_expiration(expirations, now=None):
    now = now or datetime.now(ZoneInfo("America/New_York"))
    target = following_friday(now)
    today = now.strftime("%Y%m%d")
    valid = sorted(
        exp
        for exp in expirations
        if exp >= today and not (exp == today and now.hour >= 16)
    )
    if target in valid:
        return target, target
    # Prefer the holiday-adjusted expiration earlier in the target week.
    monday = (datetime.strptime(target, "%Y%m%d") - timedelta(days=4)).strftime(
        "%Y%m%d"
    )
    earlier = [exp for exp in valid if monday <= exp <= target]
    later = [exp for exp in valid if exp >= target]
    return (earlier[-1] if earlier else (later[0] if later else None)), target


class OptionScanner:
    def __init__(self, connection, concurrency=8, quote_timeout=3.0):
        self.connection = connection
        self.ib = connection.ib
        self.concurrency = concurrency
        self.quote_timeout = quote_timeout
        self.metadata_cache = {}
        self.contract_cache = {}
        self.quote_cache = {}
        self.quote_slots = asyncio.Semaphore(concurrency)

    async def metadata(self, symbol):
        cached = self.metadata_cache.get(symbol)
        if cached and time.monotonic() - cached[0] < 3600:
            return cached[1]
        stock = Stock(symbol, "SMART", "USD")
        qualified = await asyncio.wait_for(self.ib.qualifyContractsAsync(stock), 10)
        if not qualified:
            raise ValueError(f"Cannot find stock contract for {symbol}")
        stock = qualified[0]
        chains = await asyncio.wait_for(
            self.ib.reqSecDefOptParamsAsync(
                stock.symbol, "", stock.secType, stock.conId
            ),
            10,
        )
        chains = [
            chain
            for chain in chains
            if chain.exchange == "SMART" and str(chain.multiplier) == "100"
        ]
        if not chains:
            raise ValueError(f"No standard SMART option chain for {symbol}")
        preferred = [chain for chain in chains if chain.tradingClass == symbol]
        chain = max(preferred or chains, key=lambda item: len(item.expirations))
        result = stock, chain
        if len(self.metadata_cache) >= 256:
            self.metadata_cache.pop(next(iter(self.metadata_cache)))
        self.metadata_cache[symbol] = time.monotonic(), result
        return result

    async def wait_ready(self, ticker, predicate):
        event = asyncio.Event()

        def update(*args):
            if predicate(ticker):
                event.set()

        ticker.updateEvent += update
        try:
            update()
            await asyncio.wait_for(event.wait(), self.quote_timeout)
        except asyncio.TimeoutError:
            pass  # Missing fields remain null, never fabricated.
        finally:
            ticker.updateEvent -= update

    @staticmethod
    def greeks(ticker):
        for name in ("modelGreeks", "bidGreeks", "askGreeks", "lastGreeks"):
            greeks = getattr(ticker, name, None)
            if greeks and finite(greeks.delta) and 0 <= abs(greeks.delta) <= 1:
                return greeks
        return None

    async def quote(self, symbol, expiry, right, strike, chain, semaphore):
        key = (symbol, expiry, right, strike, chain.tradingClass)
        async with semaphore:
            contract = self.contract_cache.get(key)
            if contract is None:
                contract = Option(
                    symbol,
                    expiry,
                    strike,
                    right,
                    "SMART",
                    multiplier="100",
                    currency="USD",
                    tradingClass=chain.tradingClass,
                )
                qualified = await asyncio.wait_for(
                    self.ib.qualifyContractsAsync(contract), 8
                )
                if not qualified:
                    return None
                contract = qualified[0]
                if len(self.contract_cache) >= 2048:
                    self.contract_cache.pop(next(iter(self.contract_cache)))
                self.contract_cache[key] = contract
            ticker = self.ib.reqMktData(contract, "", False, False)
            try:
                await self.wait_ready(
                    ticker,
                    lambda t: (
                        self.greeks(t) is not None
                        and finite(t.bid)
                        and t.bid >= 0
                        and finite(t.ask)
                        and t.ask > 0
                    ),
                )
                greeks = self.greeks(ticker)
                bid = ticker.bid if finite(ticker.bid) and ticker.bid >= 0 else None
                ask = ticker.ask if finite(ticker.ask) and ticker.ask > 0 else None
                mid = (
                    cents((bid + ask) / 2)
                    if bid is not None and ask is not None and ask >= bid
                    else None
                )

                def greek(name):
                    value = getattr(greeks, name, None)
                    return value if finite(value) else None

                return {
                    "symbol": symbol,
                    "strike": strike,
                    "expiration": expiry,
                    "option_type": "CALL" if right == "C" else "PUT",
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "delta": greek("delta"),
                    "gamma": greek("gamma"),
                    "theta": greek("theta"),
                    "vega": greek("vega"),
                    "implied_volatility": greek("impliedVol"),
                    "con_id": contract.conId,
                    "quoted_at": datetime.now(ZoneInfo("UTC")).isoformat(),
                }
            finally:
                self.ib.cancelMktData(contract)

    async def scan(
        self,
        symbol,
        option_type="PUT",
        expiration=None,
        delta_min=0.05,
        delta_max=0.10,
        refresh=False,
    ):
        key = (
            symbol,
            option_type,
            expiration or following_friday(),
            delta_min,
            delta_max,
        )
        cached = self.quote_cache.get(key)
        if not refresh and cached and time.monotonic() - cached[0] < 10:
            return {**deepcopy(cached[1]), "cached": True}
        started = time.monotonic()
        stock, chain = await self.metadata(symbol)
        default_expiry, target = choose_expiration(chain.expirations)
        expiry = expiration or default_expiry
        if expiry is None or expiry not in chain.expirations:
            raise ValueError("No listed contracts for the selected expiration")
        now = datetime.now(ZoneInfo("America/New_York"))
        if expiry < now.strftime("%Y%m%d") or (
            expiry == now.strftime("%Y%m%d") and now.hour >= 16
        ):
            raise ValueError("Selected expiration has already closed")
        self.connection.set_market_data_type(1 if self._market_open() else 2)
        underlying = self.ib.reqMktData(stock, "", False, False)
        try:
            await self.wait_ready(
                underlying, lambda t: finite(t.marketPrice()) and t.marketPrice() > 0
            )
            price = next(
                (
                    value
                    for value in (
                        underlying.marketPrice(),
                        underlying.last,
                        underlying.close,
                    )
                    if finite(value) and value > 0
                ),
                None,
            )
            if price is None:
                raise ValueError(
                    f"No underlying quote for {symbol}; check market-data permissions"
                )
            right = "C" if option_type == "CALL" else "P"
            # Probe across the entire OTM chain, then refine around the target delta.
            strikes = sorted(
                [
                    s
                    for s in chain.strikes
                    if s > 0
                    and ((right == "C" and s >= price) or (right == "P" and s <= price))
                ],
                reverse=right == "P",
            )
            if not strikes:
                raise ValueError("No out-of-the-money strikes available")
            count = len(strikes)
            # Quadratic spacing puts more probes near ATM without omitting the tail.
            indices = sorted({round((i / 11) ** 2 * (count - 1)) for i in range(12)})
            semaphore = self.quote_slots
            quotes = {}
            failed = 0

            async def batch(indices):
                nonlocal failed
                results = await asyncio.gather(
                    *(
                        self.quote(symbol, expiry, right, strikes[i], chain, semaphore)
                        for i in indices
                    ),
                    return_exceptions=True,
                )
                for i, result in zip(indices, results):
                    if isinstance(result, Exception) or result is None:
                        failed += 1
                    else:
                        quotes[i] = result

            await batch(indices)
            checked = set(indices)
            target_delta = (delta_min + delta_max) / 2
            # Up to 3 refinement rounds, never more than 36 requested contracts.
            for _ in range(3):
                valid = sorted(
                    (i, abs(q["delta"]))
                    for i, q in quotes.items()
                    if q["delta"] is not None
                )
                if not valid or len(checked) >= 36:
                    break
                intervals = [
                    (a, b)
                    for (a, da), (b, db) in zip(valid, valid[1:])
                    if max(da, db) >= delta_min and min(da, db) <= delta_max
                ]
                candidates = set()
                for a, b in intervals:
                    if b - a <= 8:
                        candidates.update(range(a + 1, b))
                    else:
                        candidates.update((a + (b - a) // 3, a + 2 * (b - a) // 3))
                best = min(valid, key=lambda item: abs(item[1] - target_delta))[0]
                candidates.update(range(max(0, best - 2), min(count, best + 3)))
                todo = sorted(candidates - checked, key=lambda i: abs(i - best))[
                    : 36 - len(checked)
                ]
                if not todo:
                    break
                checked.update(todo)
                await batch(todo)
            matches = [
                q
                for q in quotes.values()
                if q["delta"] is not None
                and delta_min <= abs(q["delta"]) <= delta_max
                and (
                    (right == "C" and q["delta"] >= 0)
                    or (right == "P" and q["delta"] <= 0)
                )
            ]
            matches.sort(key=lambda q: self.candidate_rank(q, target_delta))
            result = {
                "symbol": symbol,
                "option_type": option_type,
                "stock_price": price,
                "expiration": expiry,
                "target_friday": target,
                "expiration_adjusted": not expiration and expiry != target,
                "delta_min": delta_min,
                "delta_max": delta_max,
                "options": matches,
                "scanned": len(checked),
                "missing_greeks": sum(q["delta"] is None for q in quotes.values()),
                "failed_contracts": failed,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "is_frozen": not self._market_open(),
                "cached": False,
                "quoted_at": datetime.now(ZoneInfo("UTC")).isoformat(),
            }
            if len(self.quote_cache) >= 128:
                self.quote_cache.pop(next(iter(self.quote_cache)))
            self.quote_cache[key] = time.monotonic(), deepcopy(result)
            return result
        finally:
            # Keep the underlying stream alive while waiting for option Greeks.
            self.ib.cancelMktData(stock)

    @staticmethod
    def candidate_rank(quote, target_delta):
        mid, bid, ask = (quote.get(key) for key in ("mid", "bid", "ask"))
        usable = (
            finite(mid)
            and mid > 0
            and finite(bid)
            and bid >= 0
            and finite(ask)
            and ask > 0
            and ask >= bid
        )
        return (
            not usable,
            round(abs(abs(quote["delta"]) - target_delta), 12),
            (ask - bid) / mid if usable else math.inf,
            -bid if usable else 0,
            quote["strike"],
        )

    async def scan_many(
        self,
        symbols,
        option_type="PUT",
        expiration=None,
        delta_min=0.05,
        delta_max=0.10,
        refresh=False,
        timeout=85,
        on_result=None,
        cancelled=None,
    ):
        """Scan three symbols at once with one shared option-subscription cap."""
        symbols = list(dict.fromkeys(symbols))
        slots = asyncio.Semaphore(3)

        async def one(symbol):
            async with slots:
                try:
                    result = await self.scan(
                        symbol, option_type, expiration, delta_min, delta_max, refresh
                    )
                    result["candidate"] = next(
                        (
                            q
                            for q in result["options"]
                            if not self.candidate_rank(q, (delta_min + delta_max) / 2)[
                                0
                            ]
                        ),
                        None,
                    )
                except Exception as error:
                    result = {
                        "symbol": symbol,
                        "error": str(error) or "Broker request timed out",
                    }
                if on_result:
                    on_result(result)
                return result

        tasks = [asyncio.create_task(one(symbol)) for symbol in symbols]
        try:
            deadline = time.monotonic() + timeout
            pending = set(tasks)
            while (
                pending
                and time.monotonic() < deadline
                and not (cancelled and cancelled())
            ):
                _, pending = await asyncio.wait(
                    pending, timeout=min(0.25, max(0, deadline - time.monotonic()))
                )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        results = [
            {"symbol": symbol, "error": "Scan timed out. Retry this symbol."}
            if isinstance(outcome, BaseException)
            else outcome
            for symbol, outcome in zip(symbols, outcomes)
        ]
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        expirations = sorted(
            {
                exp
                for symbol in symbols
                if symbol in self.metadata_cache
                for exp in self.metadata_cache[symbol][1][1].expirations
                if exp >= today
            }
        )
        return {
            "results": results,
            "expirations": expirations,
            "target_delta": (delta_min + delta_max) / 2,
            "target_friday": following_friday(),
        }

    @staticmethod
    def _market_open():
        from core.utils import is_market_hours

        return is_market_hours()
