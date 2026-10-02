"""
Stock and Options Trading Connection Module for Interactive Brokers
"""

import logging
import asyncio
import math
import time
import traceback
from core.utils import is_market_hours
from .currency import CurrencyHelper

# Import ib_async instead of ib_insync
from ib_async import IB, Stock, Option, Contract

# Import our logging configuration
from core.logging_config import get_logger

# Configure logging
logger = get_logger("autotrader.connection", "tws")


# Set ib_async logger to WARNING level to reduce noise
def suppress_ib_logs():
    """
    Suppress verbose logs from the ib_async library by setting higher log levels
    """
    # Base ib_async loggers
    logging.getLogger("ib_async").setLevel(logging.WARNING)
    logging.getLogger("ib_async.wrapper").setLevel(logging.WARNING)
    logging.getLogger("ib_async.client").setLevel(logging.WARNING)
    logging.getLogger("ib_async.ticker").setLevel(logging.WARNING)

    # Additional ib_async logger components
    logging.getLogger("ib_async.event").setLevel(logging.WARNING)
    logging.getLogger("ib_async.util").setLevel(logging.WARNING)
    logging.getLogger("ib_async.objects").setLevel(logging.WARNING)
    logging.getLogger("ib_async.contract").setLevel(logging.WARNING)
    logging.getLogger("ib_async.order").setLevel(logging.WARNING)
    logging.getLogger("ib_async.ib").setLevel(logging.WARNING)

    # Suppress related lower-level modules used by ib_async
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("eventkit").setLevel(logging.WARNING)


# Call to suppress IB logs
suppress_ib_logs()


class IBConnection:
    """
    Class for managing connection to Interactive Brokers
    """

    def __init__(
        self,
        host="127.0.0.1",
        port=7497,
        client_id=1,
        timeout=20,
        readonly=True,
        account_id=None,
    ):
        """
        Initialize the IB connection

        Args:
            host (str): TWS/IB Gateway host (default: 127.0.0.1)
            port (int): TWS/IB Gateway port (default: 7497 for paper trading, 7496 for live)
            client_id (int): Client ID for TWS/IB Gateway
            timeout (int): Connection timeout in seconds
            readonly (bool): Whether to connect in readonly mode
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout
        self.readonly = readonly
        self.account_id = account_id
        self.ib = IB()
        self._connected = False

        # Suppress ib_async logs when initializing
        suppress_ib_logs()

    def _ensure_event_loop(self):
        """
        Ensure that an event loop exists for the current thread
        """
        try:
            # Check if an event loop exists and is running
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                pass  # Loop exists but not running, which is fine
        except RuntimeError:
            # No event loop exists in this thread, create one
            logger.debug("Creating new event loop for thread")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return True

    def connect(self):
        """
        Connect to TWS/IB Gateway

        Returns:
            bool: True if successful, False otherwise
        """
        # Suppress logs during connection attempt
        suppress_ib_logs()

        try:
            if self._connected and self.ib.isConnected():
                return True

            # Ensure event loop exists
            self._ensure_event_loop()

            self.ib.clientId = self.client_id
            self.ib.connect(
                self.host,
                self.port,
                clientId=self.client_id,
                readonly=self.readonly,
                timeout=self.timeout,
            )

            self._connected = self.ib.isConnected()
            if self._connected:
                logger.info(
                    f"Successfully connected to IB with client ID {self.client_id}"
                )
                return True
            else:
                logger.error(f"Failed to connect to IB with client ID {self.client_id}")
                return False
        except Exception as e:
            error_msg = str(e)
            if "clientId" in error_msg and "already in use" in error_msg:
                logger.error(
                    f"Connection error: Client ID {self.client_id} is already in use by another application."
                )
                logger.error(
                    "Please try using a different client ID, or close other applications connected to TWS/IB Gateway."
                )
            elif "There is no current event loop" in error_msg:
                logger.error(
                    "Asyncio event loop error detected. This may be due to threading issues."
                )
                logger.error(
                    "Please try running your code in the main thread or configuring asyncio properly."
                )
            else:
                logger.error(f"Error connecting to IB: {error_msg}")
                # Log more detailed error information for debugging
                logger.error(
                    f"Connection details: host={self.host}, port={self.port}, clientId={self.client_id}, readonly={self.readonly}"
                )
                logger.debug(traceback.format_exc())

            self._connected = False
            return False

    def disconnect(self):
        """
        Disconnect from Interactive Brokers
        """
        if self._connected:
            self.ib.disconnect()
            self._connected = False
            logger.info("Disconnected from IB")

    def is_connected(self):
        """
        Check if connected to Interactive Brokers

        Returns:
            bool: True if connected, False otherwise
        """
        return self._connected and self.ib.isConnected()

    def get_stock_price(self, symbol):
        """
        Get the current price of a stock

        Args:
            symbol (str): Stock symbol

        Returns:
            float: Current stock price or None if error
        """
        if not self.is_connected():
            logger.warning("Not connected to IB. Attempting to connect...")
            if not self.connect():
                return None

        try:
            # Ensure event loop exists for this thread
            self._ensure_event_loop()

            # Determine if market is open and set data type accordingly
            is_market_open = is_market_hours()

            if not is_market_open:
                # Use frozen data when market is closed
                self.set_market_data_type(2)  # 2 = Frozen
            else:
                # Use live data when market is open
                self.set_market_data_type(1)  # 1 = Live

            # Create a stock contract
            contract = Contract(
                symbol=symbol, secType="STK", exchange="SMART", currency="USD"
            )

            # Qualify the contract
            qualified_contracts = self.ib.qualifyContracts(contract)
            if not qualified_contracts:
                logger.error(f"Failed to qualify contract for {symbol}")
                return None

            qualified_contract = qualified_contracts[0]

            # Request market data
            ticker = self.ib.reqMktData(contract=qualified_contract)

            for _ in range(10):
                self.ib.sleep(0.1)
                if ticker.marketPrice() is not None and ticker.marketPrice() > 0:
                    break

            def valid(value):
                return (
                    isinstance(value, (int, float))
                    and math.isfinite(value)
                    and value > 0
                )

            candidates = [ticker.marketPrice(), ticker.last, ticker.close]
            last_price = next((value for value in candidates if valid(value)), None)
            if last_price is None and valid(ticker.bid) and valid(ticker.ask):
                last_price = (ticker.bid + ticker.ask) / 2

            # Cancel the market data subscription
            self.ib.cancelMktData(qualified_contract)

            if last_price is None:
                logger.error(f"Could not get price for {symbol}")
                return None

            return last_price

        except Exception as e:
            error_msg = str(e)
            if "There is no current event loop" in error_msg:
                logger.error(
                    "Asyncio event loop error in get_stock_price. Retrying with new event loop."
                )
                # Try one more time with a fresh event loop
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    return self.get_stock_price(symbol)
                except Exception as retry_error:
                    logger.error(
                        f"Failed to get stock price after event loop retry: {str(retry_error)}"
                    )
                    return None
            else:
                logger.error(f"Error getting {symbol} price: {error_msg}")
            return None

    def set_market_data_type(self, data_type=1):
        """
        Set market data type for IB client

        Args:
            data_type (int): Market data type
                1 = Live
                2 = Frozen
                3 = Delayed
                4 = Delayed frozen

        Returns:
            bool: Success or failure
        """
        try:
            if not self.is_connected():
                logger.warning("Cannot set market data type - not connected")
                return False

            self.ib.reqMarketDataType(data_type)
            return True
        except Exception as e:
            logger.error(f"Error setting market data type: {e}")
            return False

    def get_option_chain(
        self, symbol, expiration=None, right="C", target_strike=None, exchange="SMART"
    ):
        """Compatibility for the OTM API, using bounded batched quotes."""
        from core.option_scanner import OptionScanner, choose_expiration

        if not self.is_connected():
            return None
        if not hasattr(self, "_scanner"):
            self._scanner = OptionScanner(self)
        scanner = self._scanner

        async def retrieve():
            stock, chain = await scanner.metadata(symbol)
            expiry = expiration or choose_expiration(chain.expirations)[0]
            if expiry not in chain.expirations:
                raise ValueError("Expiration is not listed by the broker")
            self.set_market_data_type(1 if is_market_hours() else 2)
            underlying = self.ib.reqMktData(stock, "", False, False)
            try:
                from core.option_scanner import finite

                await scanner.wait_ready(
                    underlying,
                    lambda t: finite(t.marketPrice()) and t.marketPrice() > 0,
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
                    raise ValueError("No underlying price available")
                strikes = sorted(chain.strikes)
                if target_strike is not None:
                    strikes = [
                        min(strikes, key=lambda value: abs(value - target_strike))
                    ]
                elif len(strikes) > 24:
                    strikes = sorted(strikes, key=lambda value: abs(value - price))[:24]
                semaphore = asyncio.Semaphore(scanner.concurrency)
                results = await asyncio.gather(
                    *(
                        scanner.quote(symbol, expiry, right, strike, chain, semaphore)
                        for strike in strikes
                    ),
                    return_exceptions=True,
                )
                options = [
                    {**quote, "last": quote["mid"] or 0, "open_interest": 0}
                    for quote in results
                    if isinstance(quote, dict)
                ]
                return {
                    "symbol": symbol,
                    "expiration": expiry,
                    "stock_price": price,
                    "right": right,
                    "options": options,
                }
            finally:
                self.ib.cancelMktData(stock)

        try:
            return self.ib._run(retrieve())
        except Exception:
            logger.exception("Cannot retrieve option chain")
            return None

    def _convert_to_usd(self, value, currency):
        """
        Convert a value to USD if needed

        Args:
            value (float): The value to convert
            currency (str): The currency of the value

        Returns:
            float: The value in USD
        """
        if not currency or currency == "USD":
            return value
        return CurrencyHelper.convert_amount(value, currency, "USD")

    def get_portfolio(self):
        """
        Get current portfolio positions and account information from IB
        Returns all positions (Stocks, Options, and other security types)

        Returns:
            dict: Dictionary containing account information and all positions

        Raises:
            ConnectionError: If connection fails during market hours
            ValueError: If no data available during market hours
        """
        is_market_open = is_market_hours()

        if not self.is_connected():
            if is_market_open:
                logger.error("Not connected to IB during market hours")
                raise ConnectionError("Not connected to IB during market hours")
            else:
                # Try to connect even when market is closed
                if not self.connect():
                    logger.error("Could not connect to IB during closed market.")
                    return None

        try:
            # Set market data type based on market hours
            if not is_market_open:
                # Use frozen data when market is closed
                self.set_market_data_type(2)  # 2 = Frozen
            else:
                # Use live data when market is open
                self.set_market_data_type(1)  # 1 = Live

            # Get account summary
            account_id = self.account_id or self.ib.managedAccounts()[0]
            if account_id not in self.ib.managedAccounts():
                raise ValueError(
                    "Configured account is not available on this broker connection"
                )
            account_values = self.ib.accountSummary(account_id)

            if not account_values:
                logger.warning("No account data available")
                return None

            # Extract relevant account information
            account_info = {
                "account_id": account_id,
                "available_cash": 0,
                "account_value": 0,
                "excess_liquidity": 0,
                "initial_margin": 0,
                "leverage_percentage": 0,
            }

            # Map account tags to their corresponding fields
            account_fields = {
                "TotalCashValue": "available_cash",
                "NetLiquidation": "account_value",
                "ExcessLiquidity": "excess_liquidity",
                "FullInitMarginReq": "initial_margin",
            }

            for av in account_values:
                try:
                    # Skip if not a numeric field we care about
                    if av.tag not in account_fields:
                        continue

                    # Get the currency for this value, default to USD if empty or missing
                    currency = (
                        av.currency
                        if hasattr(av, "currency") and av.currency
                        else "USD"
                    )
                    value = float(av.value)

                    # Store the converted value
                    account_info[account_fields[av.tag]] = self._convert_to_usd(
                        value, currency
                    )
                except Exception as e:
                    logger.error(f"Error processing account value {av.tag}: {str(e)}")

            # Calculate leverage percentage
            if account_info["account_value"] > 0 and account_info["initial_margin"] > 0:
                account_info["leverage_percentage"] = (
                    account_info["initial_margin"] / account_info["account_value"]
                ) * 100

            # Get positions
            portfolio = self.ib.portfolio(account_id)
            positions = {}

            # Process all positions (both Stocks and Options)
            stock_count = 0
            option_count = 0
            other_count = 0

            # Import Option class for isinstance check
            from ib_async import Option

            for position in portfolio:
                try:
                    symbol = position.contract.symbol
                    position_key = symbol
                    position_type = "UNKNOWN"
                    # Default to USD if currency is empty or missing
                    position_currency = (
                        position.contract.currency
                        if position.contract.currency
                        else "USD"
                    )

                    # Determine position type and create an appropriate key
                    if isinstance(position.contract, Stock):
                        position_type = "STK"
                        stock_count += 1
                    elif isinstance(position.contract, Option):
                        position_type = "OPT"
                        option_count += 1
                        # For options, create a unique key including strike, expiry, and right
                        expiry = position.contract.lastTradeDateOrContractMonth
                        strike = position.contract.strike
                        right = position.contract.right
                        position_key = f"{symbol}_{expiry}_{strike}_{right}"
                    else:
                        position_type = position.contract.secType
                        other_count += 1

                    # Convert position values to USD if needed
                    positions[position_key] = {
                        "shares": position.position,
                        "avg_cost": self._convert_to_usd(
                            position.averageCost, position_currency
                        ),
                        "market_price": self._convert_to_usd(
                            position.marketPrice, position_currency
                        ),
                        "market_value": self._convert_to_usd(
                            position.marketValue, position_currency
                        ),
                        "unrealized_pnl": self._convert_to_usd(
                            position.unrealizedPNL, position_currency
                        ),
                        "realized_pnl": self._convert_to_usd(
                            position.realizedPNL, position_currency
                        ),
                        "contract": position.contract,
                        "security_type": position_type,
                    }

                except Exception as e:
                    logger.error(f"Error processing position: {str(e)}")

            return {
                "account_id": account_id,
                "available_cash": account_info.get("available_cash", 0),
                "account_value": account_info.get("account_value", 0),
                "excess_liquidity": account_info.get("excess_liquidity", 0),
                "initial_margin": account_info.get("initial_margin", 0),
                "leverage_percentage": account_info.get("leverage_percentage", 0),
                "positions": positions,
                "is_frozen": not is_market_open,  # Indicate if data is frozen
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error getting portfolio: {error_msg}")
            logger.error(traceback.format_exc())

            # During market hours, propagate the error
            raise

    def create_option_contract(
        self, symbol, expiry, strike, option_type, exchange="SMART", currency="USD"
    ):
        """
        Create an option contract for TWS

        Args:
            symbol (str): Ticker symbol
            expiry (str): Expiration date in YYYYMMDD format
            strike (float): Strike price
            option_type (str): 'C', 'CALL', 'P', or 'PUT'
            exchange (str): Exchange name, default 'SMART'
            currency (str): Currency code, default 'USD'

        Returns:
            Option: Contract object ready for use with TWS
        """
        # Normalize option type to standard format
        if option_type.upper() in ["C", "CALL"]:
            right = "C"
        elif option_type.upper() in ["P", "PUT"]:
            right = "P"
        else:
            logger.error(f"Invalid option type: {option_type}")
            return None

        try:
            contract = Option(
                symbol=symbol,
                lastTradeDateOrContractMonth=expiry,
                strike=float(strike),
                right=right,
                exchange=exchange,
                currency=currency,
            )

            return contract
        except Exception as e:
            logger.error(f"Error creating option contract: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def create_order(
        self, action, quantity, order_type="LMT", limit_price=None, tif="DAY"
    ):
        """
        Create an order for TWS

        Args:
            action (str): 'BUY' or 'SELL'
            quantity (int): Number of contracts
            order_type (str): 'MKT', 'LMT', etc.
            limit_price (float): Price for limit orders
            tif (str): Time in force - 'DAY', 'GTC', etc.

        Returns:
            Order: Order object ready for use with TWS
        """
        from ib_async import LimitOrder, MarketOrder

        try:
            if order_type.upper() == "LMT":
                if limit_price is None:
                    logger.error("Limit price required for limit orders")
                    return None

                order = LimitOrder(
                    action=action.upper(),
                    totalQuantity=quantity,
                    lmtPrice=limit_price,
                    tif=tif,
                )
            elif order_type.upper() == "MKT":
                order = MarketOrder(
                    action=action.upper(), totalQuantity=quantity, tif=tif
                )
            else:
                logger.error(f"Unsupported order type: {order_type}")
                return None
            return order
        except Exception as e:
            logger.error(f"Error creating order: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def price_increment(self, contract, price):
        """Read the routing exchange price increment at this premium."""
        key = (
            contract.symbol,
            contract.lastTradeDateOrContractMonth,
            contract.strike,
            contract.right,
            contract.exchange,
            contract.currency,
        )
        cache = self.__dict__.setdefault("_price_rule_cache", {})
        cached = cache.get(key)
        if cached and time.monotonic() - cached[0] < 300:
            detail, cached_tiers = cached[1:]
            eligible = [tier for tier in cached_tiers if tier.lowEdge <= price]
            return (
                max(eligible, key=lambda tier: tier.lowEdge).increment
                if eligible
                else detail.minTick
            )
        details = self.ib.reqContractDetails(contract)
        if not details:
            raise ValueError(
                "Cannot verify the contract's price increment. No order was sent."
            )
        detail = details[0]
        exchanges = detail.validExchanges.split(",")
        rules = detail.marketRuleIds.split(",")
        increment = detail.minTick
        tiers = []
        if contract.exchange in exchanges:
            index = exchanges.index(contract.exchange)
            if index < len(rules) and rules[index].strip():
                tiers = self.ib.reqMarketRule(int(rules[index]))
                eligible = [tier for tier in (tiers or []) if tier.lowEdge <= price]
                if not eligible:
                    raise ValueError(
                        "Cannot verify the broker's price rule. No order was sent."
                    )
                increment = max(eligible, key=lambda tier: tier.lowEdge).increment
        if not math.isfinite(increment) or increment <= 0:
            raise ValueError(
                "Cannot verify the contract's price increment. No order was sent."
            )
        if len(cache) >= 1024:
            cache.clear()
        cache[key] = (time.monotonic(), detail, tiers)
        return increment

    def normalize_limit_price(self, contract, price, action):
        from core.pricing import tick_price

        for _ in range(4):
            adjusted = tick_price(price, self.price_increment(contract, price), action)
            if adjusted == price:
                return adjusted
            price = adjusted
        raise ValueError("Cannot determine a valid limit price for this contract.")

    def validate_limit_price(self, contract, price):
        try:
            increment = self.price_increment(contract, price)
        except ValueError as error:
            return str(error)
        steps = price / increment
        if not math.isclose(steps, round(steps), rel_tol=0, abs_tol=1e-7):
            return (
                f"{contract.symbol} limit ${price:g} is invalid: IBKR requires "
                f"${increment:g} price increments. No order was sent."
            )
        return None

    def place_order(self, contract, order):
        """
        Place an order for a contract

        Args:
            contract: The contract to trade
            order: The order to place

        Returns:
            dict: Result with order details
        """
        if not self.is_connected():
            logger.error("Cannot place order - not connected to TWS")
            return None

        try:
            # Place the order
            trade = self.ib.placeOrder(contract, order)

            # orderId is assigned locally by ib_async; it is not an acknowledgment.
            acknowledged = {"Submitted", "PreSubmitted", "Filled"}
            terminal = {"Cancelled", "ApiCancelled", "Inactive"}
            deadline = time.monotonic() + 10
            while (
                getattr(getattr(trade, "orderStatus", None), "status", None)
                not in acknowledged | terminal
                and self.is_connected()
                and time.monotonic() < deadline
            ):
                self.ib.waitOnUpdate(timeout=0.1)
            if not hasattr(trade, "orderStatus"):
                return {
                    "order_id": getattr(order, "orderId", 0),
                    "status": "Unknown",
                    "error": "Broker acknowledgment was not received",
                }

            # Create result dictionary with safe attribute access
            order_status = {
                "order_id": getattr(trade.orderStatus, "orderId", 0),
                "status": getattr(trade.orderStatus, "status", "Unknown"),
                "filled": getattr(trade.orderStatus, "filled", 0),
                "remaining": getattr(
                    trade.orderStatus, "remaining", getattr(order, "totalQuantity", 0)
                ),
                "avg_fill_price": getattr(trade.orderStatus, "avgFillPrice", 0),
                "perm_id": getattr(trade.orderStatus, "permId", 0),
                "last_fill_price": getattr(trade.orderStatus, "lastFillPrice", 0),
                "client_id": getattr(trade.orderStatus, "clientId", 0),
                "why_held": getattr(trade.orderStatus, "whyHeld", ""),
                "market_cap": getattr(trade.orderStatus, "mktCapPrice", 0),
            }

            if order_status["status"] in terminal:
                errors = [entry.message for entry in trade.log if entry.errorCode]
                order_status["rejection_reason"] = (
                    errors[-1] if errors else "IBKR did not accept the order"
                )
            elif order_status["status"] not in acknowledged:
                order_status["error"] = "Broker acknowledgment was not received"
            return order_status
        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            logger.error(traceback.format_exc())
            # If we at least have an order ID, return that with an error status
            try:
                order_id = getattr(order, "orderId", 0)
                if order_id > 0:
                    return {
                        "order_id": order_id,
                        "status": "Error",
                        "filled": 0,
                        "remaining": getattr(order, "totalQuantity", 0),
                        "error": str(e),
                    }
            except:
                pass

            return None

    def check_order_status(self, order_id, perm_id=None, client_id=None, trades=None):
        """Read trade status using durable identity, including completed trades."""
        if not self.is_connected():
            return None
        try:
            if trades is None:
                trades = list(self.ib.reqAllOpenOrders()) + list(
                    self.ib.reqCompletedOrders(apiOnly=True)
                )
            for trade in trades:
                order = trade.order
                matches = (
                    (int(order.permId or 0) == int(perm_id))
                    if perm_id
                    else (
                        client_id is not None
                        and int(order.orderId) == int(order_id)
                        and int(order.clientId) == int(client_id)
                    )
                )
                if not matches:
                    continue
                status = trade.orderStatus
                commissions = [
                    float(fill.commissionReport.commission or 0) for fill in trade.fills
                ]
                return {
                    "status": status.status,
                    "filled": status.filled,
                    "remaining": status.remaining,
                    "avg_fill_price": status.avgFillPrice,
                    "commission": sum(
                        c for c in commissions if math.isfinite(c) and abs(c) < 1e100
                    ),
                }
            return {
                "status": "NotFound",
                "filled": 0,
                "remaining": 0,
                "avg_fill_price": 0,
            }
        except Exception:
            logger.exception("Cannot retrieve order status")
            return None

    def cancel_order(self, order_id):
        """
        Cancel an open order by its IB order ID

        Args:
            order_id (int): The IB order ID to cancel

        Returns:
            dict: Result with success/failure info
        """

        try:
            # Ensure connection
            if not self.is_connected():
                logger.error("Not connected to TWS")
                return {"success": False, "error": "Not connected to TWS"}

            # Ensure order ID is an integer
            order_id = int(order_id)

            # Get all open orders
            open_orders = [trade.order for trade in self.ib.reqOpenOrders()]

            # Find the order to cancel
            order_to_cancel = None
            for o in open_orders:
                if hasattr(o, "orderId") and o.orderId == order_id:
                    order_to_cancel = o
                    break

            # If not found in open orders, check trades
            if not order_to_cancel:
                trades = self.ib.trades()
                for trade in trades:
                    if (
                        hasattr(trade.order, "orderId")
                        and trade.order.orderId == order_id
                    ):
                        order_to_cancel = trade.order
                        break

            if not order_to_cancel:
                logger.warning(
                    f"Order with ID {order_id} not found in open orders or trades"
                )
                return {
                    "success": False,
                    "error": f"Order with ID {order_id} not found in open orders",
                }

            # Cancel the order
            try:
                self.ib.cancelOrder(order_to_cancel)
                return {
                    "success": True,
                    "message": f"Cancellation request sent for order {order_id}",
                }
            except Exception as e:
                logger.error(f"Error cancelling order: {str(e)}")
                return {"success": False, "error": str(e)}

        except Exception as e:
            logger.error(f"Error in cancel_order: {str(e)}")
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
