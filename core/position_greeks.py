"""Bounded quote requests for existing option contracts; no order operations."""

import asyncio
from copy import copy
from core.option_scanner import OptionScanner


async def position_deltas(connection, contracts, timeout=3.0, concurrency=8):
    scanner = OptionScanner(connection, quote_timeout=timeout)
    slots = asyncio.Semaphore(concurrency)
    results = {contract.conId: None for contract in contracts}

    async def quote(original):
        async with slots:
            contract = copy(original)
            contract.exchange = contract.exchange or "SMART"
            subscribed = False
            try:
                ticker = connection.ib.reqMktData(contract, "", False, False)
                subscribed = True
                await scanner.wait_ready(
                    ticker, lambda value: scanner.greeks(value) is not None
                )
                greeks = scanner.greeks(ticker)
                if greeks is not None:
                    results[contract.conId] = greeks.delta
            except Exception:
                pass  # Missing entitlements or quotes leave delta unavailable.
            finally:
                if subscribed:
                    connection.ib.cancelMktData(contract)

    tasks = [asyncio.create_task(quote(contract)) for contract in contracts]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=12)
    except asyncio.TimeoutError:
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return [{"con_id": con_id, "delta": delta} for con_id, delta in results.items()]
