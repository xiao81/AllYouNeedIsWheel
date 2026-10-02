"""Offline regression tests. Broker connections and application logs are isolated."""

import asyncio
import json
import logging
import math
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

# Avoid import-time cleanup of the user's real logs.
logging_stub = types.ModuleType("core.logging_config")
logging_stub.get_logger = lambda *args: logging.getLogger("test")
sys.modules["core.logging_config"] = logging_stub
from db.database import OptionsDatabase
from api.services.order_validation import validate_order
from api.services.options_service import OptionsService
from core.option_scanner import (
    OptionScanner,
    coming_friday,
    choose_expiration,
    following_friday,
)
from core.connection import IBConnection
from config import Config

ORDER = {
    "ticker": "AAPL",
    "option_type": "PUT",
    "action": "SELL",
    "strike": 180,
    "expiration": "20990116",
    "quantity": 1,
    "limit_price": 0.27,
    "bid": 0.20,
    "ask": 0.40,
}


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = OptionsDatabase(str(Path(self.temp.name) / "orders.db"))

    def tearDown(self):
        self.temp.cleanup()

    def test_preserves_price_and_order_type(self):
        saved = self.db.get_order(self.db.save_order(validate_order(ORDER)))
        self.assertEqual(saved["limit_price"], 0.27)
        self.assertEqual(saved["order_type"], "LIMIT")

    def test_price_preparation_rolls_back_if_any_draft_was_submitted(self):
        ids = self.db.save_orders([ORDER, ORDER])
        originals = [self.db.get_order(i) for i in ids]
        self.db.claim_order(ids[1])
        with self.assertRaises(ValueError):
            self.db.update_draft_prices(
                originals,
                [{**o, "limit_price": 0.30, "premium": 0.30} for o in originals],
            )
        self.assertEqual(self.db.get_order(ids[0])["limit_price"], 0.27)
        self.assertEqual(self.db.get_order(ids[1])["status"], "submitting")

    def test_status_update_without_details(self):
        order_id = self.db.save_order(ORDER)
        self.assertTrue(self.db.update_order_status(order_id, "canceled", True))
        self.assertEqual(self.db.get_order(order_id)["status"], "canceled")

    def test_status_update_with_unmapped_details(self):
        order_id = self.db.save_order(ORDER)
        self.assertTrue(
            self.db.update_order_status(
                order_id, "canceled", True, {"last_updated": "today"}
            )
        )

    def test_claim_is_atomic_across_connections(self):
        order_id = self.db.save_order(ORDER)
        with ThreadPoolExecutor(max_workers=8) as executor:
            claims = list(
                executor.map(lambda _: self.db.claim_order(order_id), range(8))
            )
        self.assertEqual(sum(claims), 1)
        self.assertFalse(self.db.cancel_pending_order(order_id))
        self.assertFalse(self.db.update_order_quantity(order_id, 5))
        self.assertFalse(self.db.delete_order(order_id))

    def test_rollover_transaction_rolls_back_on_second_failure(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.save_orders([ORDER, {**ORDER, "ticker": None}])
        self.assertEqual(self.db.get_orders(), [])

    def test_migration_keeps_existing_order(self):
        order_id = self.db.save_order(ORDER)
        OptionsDatabase(str(self.db.db_path))
        self.assertEqual(self.db.get_order(order_id)["ticker"], "AAPL")


class OrderTests(unittest.TestCase):
    setUp = DatabaseTests.setUp
    tearDown = DatabaseTests.tearDown

    def service(self):
        service = OptionsService.__new__(OptionsService)
        service.db = self.db
        service.config = Config(
            default_config={"readonly": False}, config_file="/nonexistent"
        )
        service.connection = None
        return service

    def test_invalid_quantities_and_prices(self):
        for changes in (
            {"quantity": 1.5},
            {"quantity": True},
            {"quantity": 0},
            {"limit_price": float("nan")},
            {"limit_price": float("inf")},
            {"limit_price": 0},
            {"option_type": "invalid"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_order({**ORDER, **changes})

    def test_missing_quote_never_invents_a_price(self):
        with self.assertRaises(ValueError):
            validate_order({**ORDER, "limit_price": None})

    def test_submission_preserves_limit(self):
        service = self.service()
        connection = MagicMock()
        connection.validate_limit_price.return_value = None
        connection.client_id = 45
        connection.place_order.return_value = {
            "order_id": 12,
            "status": "Submitted",
            "perm_id": 500,
        }
        service._ensure_connection = lambda: connection
        order_id = self.db.save_order(validate_order(ORDER))
        response, status = service.execute_order(order_id, self.db)
        self.assertEqual(status, 200)
        self.assertTrue(response["success"])
        self.assertEqual(connection.create_order.call_args.args[-1], 0.27)
        self.assertEqual(self.db.get_order(order_id)["ib_client_id"], 45)
        service.execute_order(order_id, self.db)
        connection.place_order.assert_called_once()

    def test_invalid_increment_leaves_draft_unsent(self):
        service = self.service()
        connection = MagicMock()
        connection.validate_limit_price.return_value = "Invalid price increment"
        service._ensure_connection = lambda: connection
        order_id = self.db.save_order(ORDER)
        response, status = service.execute_order(order_id, self.db)
        self.assertEqual(status, 400)
        self.assertEqual(self.db.get_order(order_id)["status"], "pending")
        connection.place_order.assert_not_called()

    def test_broker_rejection_is_not_reported_as_success(self):
        service = self.service()
        connection = MagicMock(client_id=45)
        connection.validate_limit_price.return_value = None
        connection.place_order.return_value = {
            "order_id": 12,
            "status": "Cancelled",
            "rejection_reason": "Error 110: invalid price",
        }
        service._ensure_connection = lambda: connection
        order_id = self.db.save_order(ORDER)
        response, status = service.execute_order(order_id, self.db)
        self.assertEqual(status, 422)
        self.assertIn("Error 110", response["error"])
        self.assertEqual(self.db.get_order(order_id)["status"], "canceled")

    def test_readonly_blocks_submission(self):
        service = self.service()
        service.config.set("readonly", True)
        service._ensure_connection = MagicMock()
        response, status = service.execute_order(self.db.save_order(ORDER), self.db)
        self.assertEqual(status, 403)
        service._ensure_connection.assert_not_called()

    def test_uncertain_submission_is_not_retryable(self):
        service = self.service()
        connection = MagicMock(client_id=45)
        connection.validate_limit_price.return_value = None
        connection.create_order.return_value.orderId = 12
        connection.place_order.return_value = None
        service._ensure_connection = lambda: connection
        order_id = self.db.save_order(ORDER)
        response, status = service.execute_order(order_id, self.db)
        self.assertEqual(status, 502)
        self.assertEqual(self.db.get_order(order_id)["status"], "submission_unknown")
        self.assertFalse(self.db.claim_order(order_id))

    def test_failed_broker_cancellation_preserves_working_order(self):
        service = self.service()
        order_id = self.db.save_order(ORDER)
        self.db.update_order_status(
            order_id, "processing", True, {"ib_order_id": 12, "ib_client_id": 45}
        )
        with patch("api.services.options_service.IBConnection") as connection:
            connection.return_value.connect.return_value = True
            connection.return_value.cancel_order.return_value = {
                "success": False,
                "error": "Broker unavailable",
            }
            response, status = service.cancel_order(order_id)
        self.assertEqual(status, 502)
        self.assertFalse(response["success"])
        self.assertEqual(self.db.get_order(order_id)["status"], "processing")

    def test_successful_cancel_waits_for_confirmation(self):
        service = self.service()
        order_id = self.db.save_order(ORDER)
        self.db.update_order_status(
            order_id, "processing", True, {"ib_order_id": 12, "ib_client_id": 45}
        )
        with patch("api.services.options_service.IBConnection") as connection:
            connection.return_value.connect.return_value = True
            connection.return_value.cancel_order.return_value = {"success": True}
            response, status = service.cancel_order(order_id)
        self.assertEqual(status, 200)
        self.assertEqual(self.db.get_order(order_id)["status"], "canceling")

    def test_order_status_uses_trade_and_correct_client(self):
        from ib_async import Trade, Order, OrderStatus

        connection = IBConnection.__new__(IBConnection)
        connection.is_connected = lambda: True
        trade = Trade(
            order=Order(orderId=1, clientId=50, permId=99),
            orderStatus=OrderStatus(status="Filled", filled=1, avgFillPrice=0.25),
        )
        self.assertEqual(
            connection.check_order_status(1, client_id=51, trades=[trade])["status"],
            "NotFound",
        )
        self.assertEqual(
            connection.check_order_status(1, client_id=50, trades=[trade])["status"],
            "Filled",
        )
        self.assertEqual(
            connection.check_order_status(9, perm_id=99, trades=[trade])["commission"],
            0,
        )


class BrokerAcknowledgmentTests(unittest.TestCase):
    def connection(self):
        connection = IBConnection.__new__(IBConnection)
        connection.is_connected = lambda: True
        connection.ib = MagicMock()
        return connection

    def test_local_order_id_does_not_count_as_acknowledgment(self):
        from ib_async import Trade, Order, OrderStatus

        connection = self.connection()
        trade = Trade(
            order=Order(orderId=42),
            orderStatus=OrderStatus(orderId=42, status="PendingSubmit"),
        )
        connection.ib.placeOrder.return_value = trade

        def acknowledge(**kwargs):
            trade.orderStatus.status = "Submitted"
            trade.orderStatus.permId = 789

        connection.ib.waitOnUpdate.side_effect = acknowledge
        result = connection.place_order(trade.contract, trade.order)
        connection.ib.waitOnUpdate.assert_called_once()
        self.assertEqual(result["perm_id"], 789)
        self.assertNotIn("error", result)

    def test_unacknowledged_order_times_out_without_retry(self):
        from ib_async import Trade, Order, OrderStatus

        connection = self.connection()
        trade = Trade(
            order=Order(orderId=42),
            orderStatus=OrderStatus(orderId=42, status="PendingSubmit"),
        )
        connection.ib.placeOrder.return_value = trade
        with patch("core.connection.time.monotonic", side_effect=[0, 11]):
            result = connection.place_order(trade.contract, trade.order)
        self.assertIn("error", result)
        self.assertEqual(result["order_id"], 42)
        connection.ib.placeOrder.assert_called_once()

    def test_rejection_includes_broker_message(self):
        from ib_async import Trade, OrderStatus

        connection = self.connection()
        trade = Trade(orderStatus=OrderStatus(orderId=42, status="Cancelled"))
        trade.log = [
            types.SimpleNamespace(errorCode=110, message="Invalid price increment")
        ]
        connection.ib.placeOrder.return_value = trade
        result = connection.place_order(trade.contract, trade.order)
        self.assertEqual(result["rejection_reason"], "Invalid price increment")

    def test_price_rules_reject_half_cents_and_respect_tiers(self):
        from ib_async import Option

        connection = self.connection()
        connection.ib.reqContractDetails.return_value = [
            types.SimpleNamespace(
                validExchanges="SMART", marketRuleIds="32", minTick=0.01
            )
        ]
        connection.ib.reqMarketRule.return_value = [
            types.SimpleNamespace(lowEdge=0, increment=0.01),
            types.SimpleNamespace(lowEdge=3, increment=0.05),
        ]
        contract = Option("ALFA", "20990116", 100, "C", "SMART")
        self.assertIn("$0.325", connection.validate_limit_price(contract, 0.325))
        self.assertIsNone(
            connection.validate_limit_price(contract, 0.33000000000000007)
        )
        self.assertIn("$0.05", connection.validate_limit_price(contract, 3.03))
        self.assertIsNone(connection.validate_limit_price(contract, 3.05))


class PricePrecisionTests(unittest.TestCase):
    def test_direction_ticks_and_binary_noise(self):
        from core.pricing import tick_price, cents

        self.assertEqual(tick_price(0.435, 0.01, "SELL"), 0.44)
        self.assertEqual(tick_price(0.435, 0.01, "BUY"), 0.43)
        self.assertEqual(tick_price(0.41000000000000003, 0.01, "SELL"), 0.41)
        self.assertEqual(tick_price(1.025, 0.05, "SELL"), 1.05)
        self.assertEqual(tick_price(1.025, 0.05, "BUY"), 1.00)
        self.assertEqual(cents(0.435), 0.44)
        self.assertEqual(cents((0.15 + 0.18) / 2), 0.17)
        with self.assertRaises(ValueError):
            tick_price(0.001, 0.01, "BUY")


class PositionDeltaTests(unittest.IsolatedAsyncioTestCase):
    async def test_signed_delta_missing_quotes_and_cleanup(self):
        from ib_async import Option, Ticker
        from core.position_greeks import position_deltas

        connection = MagicMock()
        call, put, missing = Ticker(), Ticker(), Ticker()
        call.modelGreeks = types.SimpleNamespace(delta=0.125)
        put.modelGreeks = types.SimpleNamespace(delta=-0.075)
        missing.modelGreeks = types.SimpleNamespace(delta=float("nan"))
        connection.ib.reqMktData.side_effect = [call, put, missing]
        contracts = [
            Option("AAPL", "20990116", 200, right, conId=i)
            for i, right in enumerate(["C", "P", "C"], 1)
        ]
        result = await position_deltas(connection, contracts, timeout=0.001)
        self.assertEqual([row["delta"] for row in result], [0.125, -0.075, None])
        self.assertEqual(connection.ib.cancelMktData.call_count, 3)
        self.assertEqual(len(missing.updateEvent), 0)
        self.assertEqual(contracts[0].exchange, "")
        connection.ib.placeOrder.assert_not_called()

    async def test_one_failed_subscription_does_not_hide_other_deltas(self):
        from ib_async import Option, Ticker
        from core.position_greeks import position_deltas

        connection = MagicMock()
        ticker = Ticker()
        ticker.modelGreeks = types.SimpleNamespace(delta=0.0)
        connection.ib.reqMktData.side_effect = [RuntimeError("No quote"), ticker]
        result = await position_deltas(
            connection, [Option(conId=1), Option(conId=2)], timeout=0.001
        )
        self.assertEqual(
            result, [{"con_id": 1, "delta": None}, {"con_id": 2, "delta": 0.0}]
        )
        self.assertEqual(connection.ib.cancelMktData.call_count, 1)


class CalendarTests(unittest.TestCase):
    def at(self, value):
        return datetime.fromisoformat(value).replace(
            tzinfo=ZoneInfo("America/New_York")
        )

    def test_friday_before_and_after_close(self):
        self.assertEqual(coming_friday(self.at("2026-09-11T15:59")), "20260911")
        self.assertEqual(coming_friday(self.at("2026-09-11T16:00")), "20260918")
        self.assertEqual(coming_friday(self.at("2026-09-12T10:00")), "20260918")

    def test_following_friday_default(self):
        self.assertEqual(following_friday(self.at("2026-09-07T10:00")), "20260918")
        self.assertEqual(following_friday(self.at("2026-09-11T15:59")), "20260918")
        self.assertEqual(following_friday(self.at("2026-09-11T16:00")), "20260925")

    def test_holiday_adjusted_expiry(self):
        self.assertEqual(
            choose_expiration(["20260402", "20260410"], self.at("2026-03-23T10:00")),
            ("20260402", "20260403"),
        )

    def test_next_available_when_no_weekly_listing(self):
        self.assertEqual(
            choose_expiration(["20260918"], self.at("2026-09-07T10:00")),
            ("20260918", "20260918"),
        )


class ScannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_wait_returns_immediately_when_fields_ready(self):
        from ib_async import Ticker

        scanner = OptionScanner(MagicMock(), quote_timeout=0.01)
        ticker = Ticker()
        ticker.bid = 1
        ticker.ask = 2
        await scanner.wait_ready(ticker, lambda t: t.bid == 1)
        self.assertEqual(len(ticker.updateEvent), 0)

    async def test_batching_delta_filter_cache_and_subscription_cleanup(self):
        from ib_async import Stock, Ticker

        connection = MagicMock()
        underlying = Ticker()
        underlying.last = underlying.close = 100
        connection.ib.reqMktData.return_value = underlying
        scanner = OptionScanner(connection, concurrency=4, quote_timeout=0.01)
        chain = types.SimpleNamespace(
            strikes=list(range(30, 171)), expirations={"20990116"}, tradingClass="AAPL"
        )

        async def metadata(symbol):
            return Stock(symbol, "SMART", "USD"), chain

        scanner.metadata = metadata
        active = peak = calls = 0

        async def quote(symbol, expiry, right, strike, chain, semaphore):
            nonlocal active, peak, calls
            async with semaphore:
                active += 1
                calls += 1
                peak = max(peak, active)
                await asyncio.sleep(0.001)
                active -= 1
                delta = (
                    0.5
                    * math.exp(-abs(strike - 100) / 10)
                    * (1 if right == "C" else -1)
                )
                return {
                    "strike": strike,
                    "delta": delta,
                    "mid": 0.30,
                    "option_type": "PUT",
                }

        scanner.quote = quote
        result = await scanner.scan("AAPL", "PUT", "20990116")
        self.assertTrue(result["options"])
        self.assertTrue(all(0.05 <= abs(o["delta"]) <= 0.10 for o in result["options"]))
        self.assertLessEqual(result["scanned"], 36)
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 4)
        previous = calls
        second = await scanner.scan("AAPL", "PUT", "20990116")
        self.assertTrue(second["cached"])
        self.assertEqual(calls, previous)
        connection.ib.cancelMktData.assert_called_once()

    async def test_multi_symbol_scan_shares_quote_budget(self):
        from ib_async import Stock, Ticker

        connection = MagicMock()
        underlying = Ticker()
        underlying.last = underlying.close = 100
        connection.ib.reqMktData.return_value = underlying
        scanner = OptionScanner(connection, concurrency=4, quote_timeout=0.001)
        chain = types.SimpleNamespace(
            strikes=[70, 80, 90], expirations={"20990116"}, tradingClass="TEST"
        )

        async def metadata(symbol):
            if symbol == "BAD":
                raise ValueError("No chain")
            return Stock(symbol, "SMART", "USD"), chain

        scanner.metadata = metadata
        active = peak = 0

        async def quote(symbol, expiry, right, strike, chain, semaphore):
            nonlocal active, peak
            async with semaphore:
                active += 1
                peak = max(active, peak)
                await asyncio.sleep(0.001)
                active -= 1
                return {
                    "strike": strike,
                    "delta": -0.075,
                    "mid": 1,
                    "bid": 0.9,
                    "ask": 1.1,
                }

        scanner.quote = quote
        result = await scanner.scan_many(
            ["AAPL", "BAD", "MSFT", "NVDA"], expiration="20990116"
        )
        self.assertEqual(
            [r["symbol"] for r in result["results"]], ["AAPL", "BAD", "MSFT", "NVDA"]
        )
        self.assertEqual(result["results"][1]["error"], "No chain")
        self.assertIsNotNone(result["results"][0]["candidate"])
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 4)
        self.assertEqual(connection.ib.cancelMktData.call_count, 3)

    async def test_batch_timeout_cancels_pending_work(self):
        scanner = OptionScanner(MagicMock())
        cleaned = []

        async def scan(symbol, *args):
            try:
                await asyncio.sleep(10)
            finally:
                cleaned.append(symbol)

        scanner.scan = scan
        result = await scanner.scan_many(["AAPL", "MSFT"], timeout=0.01)
        self.assertEqual(set(cleaned), {"AAPL", "MSFT"})
        self.assertTrue(all("timed out" in row["error"] for row in result["results"]))

    async def test_ranking_prefers_delta_then_relative_spread_then_bid(self):
        base = {"strike": 100, "delta": -0.075, "bid": 0.9, "ask": 1.1, "mid": 1}
        narrow = {**base, "bid": 0.95, "ask": 1.05}
        farther = {**base, "delta": -0.08, "bid": 4.9, "ask": 5.1, "mid": 5}
        missing = {**base, "mid": None}
        ranked = sorted(
            [missing, farther, base, narrow],
            key=lambda q: OptionScanner.candidate_rank(q, 0.075),
        )
        self.assertEqual(ranked, [narrow, base, farther, missing])

    async def test_missing_greeks_not_replaced_with_zero(self):
        from ib_async import Ticker

        scanner = OptionScanner(MagicMock())
        self.assertIsNone(scanner.greeks(Ticker()))


class SettingsAndRouteTests(unittest.TestCase):
    def setUp(self):
        self.cwd = Path.cwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        from core.settings import read_profiles

        profiles = read_profiles()
        profiles["paper"]["db_path"] = str(Path(self.temp.name) / "paper.db")
        Path("settings.json").write_text(json.dumps(profiles))
        import app

        self.app = app.app
        self.app.config["database"] = OptionsDatabase(profiles["paper"]["db_path"])
        self.client = self.app.test_client()
        from core.settings import public_profiles

        self.client.environ_base["HTTP_X_WHEEL_PROFILE"] = public_profiles(
            read_profiles()
        )["revision"]
        self.no_network = patch.object(
            IBConnection,
            "connect",
            side_effect=AssertionError("Real broker access forbidden in tests"),
        )
        self.no_network.start()
        # Draft preparation may read contract rules, but cannot place orders.
        from core.pricing import tick_price

        self.price_connection = MagicMock()
        self.price_connection.normalize_limit_price.side_effect = (
            lambda contract, price, action: tick_price(price, 0.01, action)
        )
        self.draft_connection = patch.object(
            OptionsService, "_ensure_connection", return_value=self.price_connection
        )
        self.draft_connection.start()

    def tearDown(self):
        self.draft_connection.stop()
        self.no_network.stop()
        os.chdir(self.cwd)
        self.temp.cleanup()

    def test_pages_render_without_bootstrap_or_remote_assets(self):
        for route in ("/", "/portfolio", "/rollover", "/settings"):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b"cdn.jsdelivr", response.data)

    def test_first_run_settings_work_without_json_files(self):
        Path("settings.json").unlink()
        self.assertFalse(Path("connection.json").exists())
        self.assertFalse(Path("connection_real.json").exists())
        response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(data["mode"], "paper")
        self.assertTrue(data["paper"]["readonly"])
        self.client.environ_base["HTTP_X_WHEEL_PROFILE"] = data["revision"]
        data["paper"]["platform"] = "gateway"
        data["paper"]["port"] = 4002
        self.assertEqual(self.client.put("/api/settings", json=data).status_code, 200)
        self.assertEqual(Config().get("port"), 4002)
        self.assertTrue(Path("settings.json").exists())

    def test_profile_save_and_config_reload(self):
        data = self.client.get("/api/settings").json
        data["mode"] = "live"
        data["live"]["platform"] = "gateway"
        data["live"]["port"] = 4001
        response = self.client.put("/api/settings", json=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Config().get("port"), 4001)
        self.assertEqual(Config().get("mode"), "live")

    def test_bad_settings_do_not_overwrite_saved_settings(self):
        before = Path("settings.json").read_text()
        data = self.client.get("/api/settings").json
        data["paper"]["port"] = 0
        self.assertEqual(self.client.put("/api/settings", json=data).status_code, 400)
        self.assertEqual(Path("settings.json").read_text(), before)

    def test_cancel_draft_and_refresh_while_broker_thread_is_busy(self):
        from threading import Event

        order_id = self.client.post("/api/options/order", json=ORDER).json["order_id"]
        release, started = Event(), Event()

        def hold_broker():
            started.set()
            release.wait(5)

        future = self.app.extensions["broker_executor"].submit(hold_broker)
        started.wait(1)
        path = f"/api/options/order/{order_id}/draft"
        try:
            self.assertEqual(
                self.client.delete(
                    path, headers={"X-Wheel-Profile": "stale"}
                ).status_code,
                409,
            )
            self.assertEqual(self.client.delete(path).status_code, 200)
            self.assertEqual(
                self.client.get("/api/options/pending-orders").json["orders"], []
            )
            self.assertFalse(
                future.done(), "Local cancellation must not wait for broker work"
            )
            self.assertEqual(self.client.delete(path).status_code, 200)
            self.assertEqual(
                self.client.post("/api/options/order", json=ORDER).status_code, 201
            )
            self.assertEqual(
                self.client.post(
                    "/api/options/orders/batch", json={"orders": [ORDER]}
                ).status_code,
                201,
            )
            self.assertFalse(
                future.done(), "Saving drafts must not wait for broker work"
            )
            self.price_connection.normalize_limit_price.assert_not_called()
        finally:
            release.set()
            future.result(timeout=1)

    def test_dashboard_cannot_cancel_submitted_orders_in_ibkr(self):
        from api.routes.options import options_service

        order_id = self.client.post("/api/options/order", json=ORDER).json["order_id"]
        db = self.app.config["database"]
        with patch.object(options_service, "cancel_order") as broker_cancel:
            for status in (
                "submitting",
                "processing",
                "canceling",
                "submission_unknown",
            ):
                db.update_order_status(order_id, status, False)
                for method, path in (
                    ("POST", f"/api/options/cancel/{order_id}"),
                    ("DELETE", f"/api/options/order/{order_id}/draft"),
                ):
                    response = self.client.open(path, method=method)
                    self.assertEqual(response.status_code, 409)
                    self.assertIn("IBKR", response.json["error"])
                    self.assertEqual(db.get_order(order_id)["status"], status)
            broker_cancel.assert_not_called()

    def test_draft_cancel_cannot_cancel_submitted_order(self):
        order_id = self.client.post("/api/options/order", json=ORDER).json["order_id"]
        db = self.app.config["database"]
        self.assertTrue(db.claim_order(order_id))
        response = self.client.delete(f"/api/options/order/{order_id}/draft")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(db.get_order(order_id)["status"], "submitting")

    def test_bulk_submit_rejects_changed_review_and_rollovers(self):
        from api.routes.options import options_service as service

        response = self.client.post("/api/options/order", json=ORDER)
        order_id = response.json["order_id"]
        with patch.object(
            service, "execute_order", return_value=({"success": True}, 200)
        ) as execute:
            changed = {**ORDER, "quantity": ORDER["quantity"] + 1}
            response = self.client.post(
                f"/api/options/execute/{order_id}",
                json={"expected_order": changed, "bulk": True},
            )
            self.assertEqual(response.status_code, 409)
            execute.assert_not_called()
            response = self.client.post(
                f"/api/options/execute/{order_id}",
                json={"expected_order": ORDER, "bulk": True},
            )
            self.assertEqual(response.status_code, 200)
            execute.assert_called_once()
        rollover = self.client.post(
            "/api/options/order", json={**ORDER, "isRollover": True}
        ).json["order_id"]
        with patch.object(service, "execute_order") as execute:
            response = self.client.post(
                f"/api/options/execute/{rollover}", json={"bulk": True}
            )
            self.assertEqual(response.status_code, 409)
            execute.assert_not_called()

    def test_all_draft_paths_store_two_decimal_prices(self):
        response = self.client.post(
            "/api/options/order", json={**ORDER, "limit_price": 0.435}
        )
        self.assertEqual(response.status_code, 201)
        row = self.app.config["database"].get_order(response.json["order_id"])
        self.assertEqual(row["limit_price"], 0.44)
        self.assertEqual(row["premium"], 0.44)
        response = self.client.post(
            "/api/options/orders/batch",
            json={
                "orders": [
                    {**ORDER, "limit_price": 0.325},
                    {**ORDER, "limit_price": 0.025},
                ]
            },
        )
        self.assertEqual(response.status_code, 201)
        prices = [
            self.app.config["database"].get_order(i)["limit_price"]
            for i in response.json["order_ids"]
        ]
        self.assertEqual(prices, [0.33, 0.03])
        self.price_connection.place_order.assert_not_called()

    def test_rollover_normalizes_both_draft_prices(self):
        response = self.client.post(
            "/api/options/rollover",
            json={
                "ticker": "AAPL",
                "current_option_type": "CALL",
                "current_strike": 180,
                "current_expiration": "20990116",
                "new_strike": 190,
                "new_expiration": "20990123",
                "quantity": 1,
                "current_order_type": "LIMIT",
                "new_order_type": "LIMIT",
                "current_limit_price": 0.435,
                "new_limit_price": 0.435,
            },
        )
        self.assertEqual(response.status_code, 201)
        db = self.app.config["database"]
        self.assertEqual(
            db.get_order(response.json["buy_order_id"])["limit_price"], 0.43
        )
        self.assertEqual(
            db.get_order(response.json["sell_order_id"])["limit_price"], 0.44
        )
        self.price_connection.place_order.assert_not_called()

    def test_submission_preparation_checks_ticks_without_sending(self):
        from core.pricing import tick_price

        self.price_connection.normalize_limit_price.side_effect = (
            lambda contract, price, action: tick_price(price, 0.05, action)
        )
        order_id = self.client.post("/api/options/order", json=ORDER).json["order_id"]
        self.price_connection.normalize_limit_price.assert_not_called()
        response = self.client.post(
            "/api/options/orders/prepare-submission", json={"order_ids": [order_id]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["orders"][0]["limit_price"], 0.30)
        self.assertEqual(
            self.app.config["database"].get_order(order_id)["limit_price"], 0.30
        )
        self.price_connection.place_order.assert_not_called()

    def test_order_quantity_rejects_fraction(self):
        response = self.client.post("/api/options/order", json=ORDER)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            self.client.put(
                f"/api/options/order/{response.json['order_id']}/quantity",
                json={"quantity": 1.5},
            ).status_code,
            400,
        )

    def test_scan_rejects_invalid_range_without_broker(self):
        for query in ("delta_min=nan", "delta_min=.2&delta_max=.1", "type=BAD"):
            self.assertEqual(
                self.client.get("/api/options/scan?ticker=AAPL&" + query).status_code,
                400,
            )

    def test_batch_drafts_are_validated_and_saved_atomically(self):
        invalid = self.client.post(
            "/api/options/orders/batch",
            json={"orders": [ORDER, {**ORDER, "quantity": 0}]},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            self.client.get("/api/options/pending-orders").json["orders"], []
        )
        saved = self.client.post(
            "/api/options/orders/batch",
            json={"orders": [ORDER, {**ORDER, "ticker": "MSFT", "quantity": 2}]},
        )
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(len(saved.json["order_ids"]), 2)
        rows = self.client.get("/api/options/pending-orders").json["orders"]
        self.assertTrue(
            all(
                row["status"] == "pending" and row["limit_price"] == 0.27
                for row in rows
            )
        )

    def test_batch_scan_validation_precedes_broker_access(self):
        for query in (
            "",
            "tickers=AAPL&delta_min=nan",
            "tickers=AAPL&expiration=bad",
            "tickers=AAPL,$BAD",
            "tickers=" + ",".join(f"S{i}" for i in range(21)),
        ):
            self.assertEqual(
                self.client.get("/api/options/scan-batch?" + query).status_code, 400
            )

    def test_remove_stale_record_never_contacts_broker(self):
        order_id = self.client.post("/api/options/order", json=ORDER).json["order_id"]
        db = self.app.config["database"]
        path = f"/api/options/order/{order_id}/local"
        self.assertEqual(
            self.client.delete(path, json={"confirm_local_only": True}).status_code, 409
        )
        db.update_order_status(order_id, "processing", False)
        self.assertEqual(self.client.delete(path, json={}).status_code, 400)
        self.assertIsNotNone(db.get_order(order_id))
        self.assertEqual(
            self.client.delete(
                path,
                json={"confirm_local_only": True},
                headers={"X-Wheel-Profile": "stale"},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.delete(path, json={"confirm_local_only": True}).status_code, 200
        )
        self.assertIsNone(db.get_order(order_id))

    def test_stream_sends_completed_symbol_before_scan_finishes(self):
        import threading
        from api.routes.options import options_service

        release = threading.Event()
        scanner = MagicMock()
        scanner.ib._run.side_effect = lambda coro: (
            asyncio.get_event_loop().run_until_complete(coro)
        )

        async def scan(*args, on_result=None, cancelled=None):
            row = {"symbol": "AAPL", "options": []}
            on_result(row)
            while not release.is_set() and not cancelled():
                await asyncio.sleep(0.01)
            return {"results": [row]}

        scanner.scan_many = scan
        with patch.object(options_service, "get_scanner", return_value=scanner):
            response = self.client.get(
                "/api/options/scan-batch?tickers=AAPL,MSFT&stream=true", buffered=False
            )
            try:
                events = iter(response.response)
                self.assertEqual(json.loads(next(events))["type"], "started")
                self.assertEqual(json.loads(next(events))["result"]["symbol"], "AAPL")
                self.assertFalse(release.is_set())
                release.set()
                self.assertEqual(json.loads(next(events))["type"], "complete")
            finally:
                release.set()
                response.close()

    def test_cross_origin_mutations_are_rejected(self):
        response = self.client.post(
            "/api/options/cancel/1", headers={"Origin": "https://unrelated.example"}
        )
        self.assertEqual(response.status_code, 403)

    def test_stale_profile_blocks_order_mutation(self):
        response = self.client.post(
            "/api/options/order", json=ORDER, headers={"X-Wheel-Profile": "old-profile"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self.client.get("/api/options/pending-orders").json["orders"], []
        )

    def test_nonfinite_json_becomes_null(self):
        self.assertEqual(
            json.loads(
                self.app.json.dumps({"price": float("nan"), "items": [float("inf")]})
            ),
            {"price": None, "items": [None]},
        )

    def test_invalid_rollover_does_not_save_either_leg(self):
        data = {
            "ticker": "AAPL",
            "current_option_type": "PUT",
            "current_strike": 180,
            "current_expiration": "20990116",
            "new_strike": 175,
            "new_expiration": "20990123",
            "quantity": 1,
            "current_order_type": "LIMIT",
            "current_limit_price": 0.80,
            "new_limit_price": 0,
        }
        self.assertEqual(
            self.client.post("/api/options/rollover", json=data).status_code, 400
        )
        self.assertEqual(
            self.client.get("/api/options/pending-orders").json["orders"], []
        )

    def test_rollover_prices_use_same_unit(self):
        data = {
            "ticker": "AAPL",
            "current_option_type": "PUT",
            "current_strike": 180,
            "current_expiration": "20990116",
            "new_strike": 175,
            "new_expiration": "20990123",
            "quantity": 1,
            "current_order_type": "LIMIT",
            "current_limit_price": 0.80,
            "new_limit_price": 0.95,
        }
        response = self.client.post("/api/options/rollover", json=data)
        self.assertEqual(response.status_code, 201)
        orders = self.client.get("/api/options/pending-orders").json["orders"]
        self.assertEqual(sorted(o["limit_price"] for o in orders), [0.80, 0.95])


if __name__ == "__main__":
    unittest.main()
