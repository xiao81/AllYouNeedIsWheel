"""Portfolio snapshots shared briefly across the dashboard's read requests."""

import logging
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from core.connection import IBConnection
from config import Config

logger = logging.getLogger("api.services.portfolio")


class PortfolioService:
    def __init__(self):
        self.config = Config()
        self.connection = None
        self._portfolio_cache = None

    def _ensure_connection(self):
        if self.connection is None:
            self.connection = IBConnection(
                host=self.config.get("host", "127.0.0.1"),
                port=self.config.get("port", 7497),
                client_id=random.randint(10000, 2000000000),
                readonly=self.config.get("readonly", True),
                timeout=self.config.get("timeout", 10),
                account_id=self.config.get("account_id"),
            )
        if not self.connection.is_connected() and not self.connection.connect():
            raise ConnectionError(
                "Cannot connect to the broker. Check Settings and your broker session."
            )
        return self.connection

    def _portfolio(self):
        if self._portfolio_cache and time.monotonic() - self._portfolio_cache[0] < 3:
            return self._portfolio_cache[1]
        result = self._ensure_connection().get_portfolio()
        if not result:
            raise ConnectionError("No portfolio data available from broker")
        self._portfolio_cache = time.monotonic(), result
        return result

    def get_portfolio_summary(self):
        portfolio = self._portfolio()
        return {
            "account_id": portfolio.get("account_id", ""),
            "cash_balance": portfolio.get("available_cash", 0),
            "account_value": portfolio.get("account_value", 0),
            "excess_liquidity": portfolio.get("excess_liquidity", 0),
            "initial_margin": portfolio.get("initial_margin", 0),
            "leverage_percentage": portfolio.get("leverage_percentage", 0),
            "is_frozen": portfolio.get("is_frozen", False),
        }

    def get_positions(self, security_type=None):
        result = []
        for position in self._portfolio().get("positions", {}).values():
            contract = position.get("contract")
            kind = position.get("security_type")
            if not contract or (security_type and kind != security_type):
                continue
            item = {
                "symbol": contract.symbol,
                "position": position.get("shares", 0),
                "market_price": position.get("market_price"),
                "market_value": position.get("market_value"),
                "avg_cost": position.get("avg_cost"),
                "unrealized_pnl": position.get("unrealized_pnl"),
                "security_type": kind,
            }
            if kind == "OPT":
                item.update(
                    con_id=contract.conId,
                    delta=None,
                    expiration=contract.lastTradeDateOrContractMonth,
                    strike=contract.strike,
                    option_type="CALL" if contract.right == "C" else "PUT",
                )
            result.append(item)
        return result

    def get_position_deltas(self):
        from core.position_greeks import position_deltas

        contracts = {
            position["contract"].conId: position["contract"]
            for position in self._portfolio().get("positions", {}).values()
            if position.get("security_type") == "OPT" and position.get("contract")
        }
        if not contracts:
            return []
        connection = self._ensure_connection()
        key = tuple(sorted(contracts))
        cached = getattr(connection, "_position_delta_cache", None)
        if cached and cached[0] == key and time.monotonic() - cached[1] < 15:
            return cached[2]
        result = connection.ib._run(position_deltas(connection, contracts.values()))
        connection._position_delta_cache = key, time.monotonic(), result
        return result

    def get_weekly_option_income(self):
        today = datetime.now(ZoneInfo("America/New_York"))
        friday = today + timedelta(days=(4 - today.weekday()) % 7)
        weekly = []
        for position in self.get_positions("OPT"):
            if position["position"] >= 0 or not today.strftime("%Y%m%d") <= position[
                "expiration"
            ] <= friday.strftime("%Y%m%d"):
                continue
            contracts = abs(position["position"])
            premium = (
                position.get("avg_cost") or 0
            )  # IB option average cost is per contract.
            notional = (
                position["strike"] * 100 * contracts
                if position["option_type"] == "PUT"
                else None
            )
            weekly.append(
                {
                    **position,
                    "premium_per_contract": premium,
                    "income": premium * contracts,
                    "notional_value": notional,
                    "commission": 0,
                }
            )
        return {
            "positions": weekly,
            "positions_count": len(weekly),
            "total_income": sum(item["income"] for item in weekly),
            "total_commission": 0,
            "total_put_notional": sum(item["notional_value"] or 0 for item in weekly),
            "this_friday": friday.strftime("%Y-%m-%d"),
        }
