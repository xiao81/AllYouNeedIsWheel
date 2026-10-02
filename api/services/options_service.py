"""
Options Service module
Handles options data retrieval and processing
"""

import logging
import math
import random
from datetime import datetime
from core.connection import IBConnection
from core.utils import is_market_hours
from core.option_scanner import following_friday
from config import Config
from db.database import OptionsDatabase
import traceback
from .order_validation import validate_order

logger = logging.getLogger("api.services.options")


class OptionsService:
    """
    Service for handling options data operations
    """

    def __init__(self):
        self.config = Config()
        self.connection = None
        db_path = self.config.get("db_path")
        self.db = OptionsDatabase(db_path)
        self.portfolio_service = None  # Will be initialized when needed

    def _ensure_connection(self):
        """
        Ensure that the IB connection exists and is connected.
        Reuses existing connection if already established.
        """
        try:
            # If we already have a connected instance, just return it
            if self.connection is not None and self.connection.is_connected():
                logger.debug("Reusing existing TWS connection")
                return self.connection

            # If connection exists but is disconnected, try to reconnect with same client ID
            if self.connection is not None:
                logger.info(
                    "Existing connection found but disconnected, attempting to reconnect"
                )
                if self.connection.connect():
                    logger.info(
                        "Successfully reconnected to TWS/IB Gateway with existing client ID"
                    )
                    return self.connection
                else:
                    logger.warning(
                        "Failed to reconnect with existing client ID, will create new connection"
                    )

            # No connection or reconnection failed, create a new one
            # Generate a unique client ID based on current timestamp and random number
            unique_client_id = random.randint(10000, 2000000000)
            logger.info(
                f"Creating new TWS connection with client ID: {unique_client_id}"
            )

            port = self.config.get("port", 7497)

            self.connection = IBConnection(
                host=self.config.get("host", "127.0.0.1"),
                port=port,
                client_id=unique_client_id,  # Use the unique client ID instead of fixed ID 1
                timeout=self.config.get("timeout", 10),
                readonly=self.config.get("readonly", True),
                account_id=self.config.get("account_id"),
            )

            # Try to connect with proper error handling
            if not self.connection.connect():
                logger.error("Failed to connect to TWS/IB Gateway")
                return None
            else:
                logger.info("Successfully connected to TWS/IB Gateway")
                return self.connection
        except Exception as e:
            logger.error(f"Error ensuring connection: {str(e)}")
            if "There is no current event loop" in str(e):
                logger.error(
                    "Asyncio event loop error - please check connection.py for proper handling"
                )
            return None

    def _adjust_to_standard_strike(self, price):
        """
        Adjust a price to a standard strike price

        Args:
            price (float): Price to adjust

        Returns:
            float: Adjusted standard strike price
        """
        return round(price)

    @staticmethod
    def prepare_drafts(orders):
        """Save two-decimal local drafts without any broker dependency."""
        from core.pricing import tick_price

        prepared = [validate_order(order) for order in orders]
        for order in prepared:
            if order["order_type"] == "LIMIT":
                order["limit_price"] = order["premium"] = tick_price(
                    order["limit_price"], 0.01, order["action"]
                )
        return prepared

    def prepare_submission_prices(self, orders):
        """Verify contract ticks before the user reviews a broker submission."""
        orders = [validate_order(order) for order in orders]
        limits = [order for order in orders if order["order_type"] == "LIMIT"]
        if not limits:
            return orders
        conn = self._ensure_connection()
        if not conn:
            raise ValueError("Connect to IBKR to verify draft price increments.")
        try:
            for order in limits:
                contract = conn.create_option_contract(
                    order["ticker"],
                    order["expiration"],
                    order["strike"],
                    order["option_type"],
                )
                price = conn.normalize_limit_price(
                    contract, order["limit_price"], order["action"]
                )
                order["limit_price"] = order["premium"] = price
            return orders
        finally:
            conn.disconnect()

    def execute_order(self, order_id, db):
        """Submit exactly the saved order, once. Never invent a missing quote."""
        order = db.get_order(order_id)
        if not order:
            return {"success": False, "error": "Order not found"}, 404
        if order["status"] != "pending":
            return {
                "success": False,
                "error": "Only pending orders can be submitted",
            }, 409
        if self.config.get("readonly", True):
            return {"success": False, "error": "Broker connection is read-only"}, 403
        try:
            order = validate_order(order)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}, 400
        conn = self._ensure_connection()
        if not conn:
            return {"success": False, "error": "Cannot connect to the broker"}, 503
        claimed = False
        submitted = False
        try:
            contract = conn.create_option_contract(
                order["ticker"],
                order["expiration"],
                order["strike"],
                order["option_type"],
            )
            if not contract or not conn.ib.qualifyContracts(contract):
                return {
                    "success": False,
                    "error": "Broker could not qualify this contract",
                }, 400
            if order["order_type"] == "LIMIT":
                price_error = conn.validate_limit_price(contract, order["limit_price"])
                if price_error:
                    return {"success": False, "error": price_error}, 400
            ib_order = conn.create_order(
                order["action"],
                order["quantity"],
                "LMT" if order["order_type"] == "LIMIT" else "MKT",
                order["limit_price"],
            )
            if not ib_order:
                return {"success": False, "error": "Cannot construct broker order"}, 400
            account = self.config.get("account_id")
            if account:
                ib_order.account = account
            if not db.claim_order(order_id):
                return {
                    "success": False,
                    "error": "Order is already being submitted or canceled",
                }, 409
            claimed = True
            submitted = True
            result = conn.place_order(contract, ib_order)
            if (
                not result
                or result.get("error")
                or not result.get("order_id")
                or result.get("status")
                not in {
                    "Submitted",
                    "PreSubmitted",
                    "Filled",
                    "Cancelled",
                    "ApiCancelled",
                    "Inactive",
                }
            ):
                db.update_order_status(
                    order_id,
                    "submission_unknown",
                    True,
                    {
                        "ib_client_id": conn.client_id,
                        "ib_order_id": getattr(ib_order, "orderId", None),
                        "ib_status": (result or {}).get("status", "Unknown"),
                    },
                )
                return {
                    "success": False,
                    "error": "Submission outcome is uncertain. Check TWS before retrying.",
                }, 502
            details = {
                "ib_order_id": result["order_id"],
                "ib_status": result.get("status"),
                "ib_client_id": conn.client_id,
                "ib_perm_id": result.get("perm_id"),
                "filled": result.get("filled", 0),
                "remaining": result.get("remaining", 0),
                "avg_fill_price": result.get("avg_fill_price", 0),
            }
            status = self._local_order_status(result.get("status"))
            if not db.update_order_status(order_id, status, True, details):
                return {
                    "success": False,
                    "error": "Order sent, but saving its status failed. Check TWS.",
                }, 500
            if status in {"rejected", "canceled"}:
                return {
                    "success": False,
                    "error": result.get("rejection_reason")
                    or "IBKR did not accept the order",
                    "status": status,
                    "order_id": order_id,
                }, 422
            return {
                "success": True,
                "order_id": order_id,
                "ib_order_id": result["order_id"],
                "status": status,
                "execution_details": details,
            }, 200
        except Exception as exc:
            logger.exception("Order submission failed")
            if claimed:
                db.update_order_status(
                    order_id,
                    "submission_unknown" if submitted else "pending",
                    submitted,
                )
            return {"success": False, "error": str(exc)}, 502
        finally:
            conn.disconnect()

    @staticmethod
    def _local_order_status(status):
        return {
            "Filled": "executed",
            "Cancelled": "canceled",
            "ApiCancelled": "canceled",
            "PendingCancel": "canceling",
            "Inactive": "rejected",
            "PendingSubmit": "submission_unknown",
            "ApiPending": "submission_unknown",
            "ValidationError": "submission_unknown",
        }.get(status, "processing")

    def get_otm_options(
        self, ticker, otm_percentage=10, option_type=None, expiration=None
    ):
        """
        Get option contracts that are OTM by the specified percentage

        Args:
            ticker (str): Ticker symbol or comma-separated list of tickers
            otm_percentage (float): Percentage OTM to filter by
            option_type (str, optional): Filter by option type ('CALL' or 'PUT')
            expiration (str, optional): Filter by specific expiration date

        Returns:
            dict: Dictionary of option data
        """
        # Validate option_type if provided
        if option_type and option_type not in ["CALL", "PUT"]:
            logger.error(f"Invalid option_type: {option_type}. Must be 'CALL' or 'PUT'")
            return {
                "error": f"Invalid option_type: {option_type}. Must be 'CALL' or 'PUT'"
            }

        # Use _ensure_connection instead of creating a new connection each time
        conn = self._ensure_connection()
        if not conn:
            logger.error("Failed to establish connection to IB")

        is_market_open = is_market_hours()

        # If no tickers provided, get them from portfolio
        tickers = list(
            dict.fromkeys(
                t.strip().upper() for t in (ticker or "").split(",") if t.strip()
            )
        )
        if not tickers:
            logger.info("No tickers found, unable to proceed")
            return {"error": "No tickers found for processing"}

        # Process each ticker
        result = {}

        for ticker in tickers:
            try:
                ticker_data = self._process_ticker_for_otm(
                    conn,
                    ticker,
                    otm_percentage,
                    expiration,
                    is_market_open,
                    option_type,
                )
                result[ticker] = ticker_data
            except Exception as e:
                logger.error(f"Error processing {ticker} for OTM options: {e}")
                logger.error(traceback.format_exc())
                result[ticker] = {"error": str(e)}

        # Return the results
        return {"data": result}

    def _process_ticker_for_otm(
        self,
        conn,
        ticker,
        otm_percentage,
        expiration=None,
        is_market_open=None,
        option_type=None,
    ):
        """
        Process a single ticker for OTM options

        Args:
            conn (IBConnection): Connection to Interactive Brokers
            ticker (str): Ticker symbol
            otm_percentage (float): Percentage OTM to filter by
            expiration (str, optional): Expiration date in YYYYMMDD format
            is_market_open (bool, optional): Whether the market is open
            option_type (str, optional): Filter by option type ('CALL' or 'PUT')

        Returns:
            dict: Option data for the ticker
        """
        result = {}

        # Get stock price from IB - will use frozen data if market is closed
        stock_price = None
        if conn and conn.is_connected():
            try:
                stock_price = conn.get_stock_price(ticker)
            except Exception as e:
                logger.error(f"Error getting stock price for {ticker}: {e}")
                logger.error(traceback.format_exc())

        # If we don't have a valid stock price, return an error
        if (
            stock_price is None
            or not isinstance(stock_price, (int, float))
            or not math.isfinite(stock_price)
            or stock_price <= 0
        ):
            logger.error(f"No valid stock price received for {ticker}")
            return {"error": "Unable to obtain valid stock price"}

        # Store stock price in result
        result["stock_price"] = stock_price

        # Get position information from portfolio
        position_size = 0
        try:
            # Import and use portfolio service to get position size if not already initialized
            if self.portfolio_service is None:
                from api.services.portfolio_service import PortfolioService

                self.portfolio_service = PortfolioService()

            # Get positions from portfolio service
            positions = self.portfolio_service.get_positions()

            # Find the matching ticker in positions
            for pos in positions:
                if pos.get("symbol") == ticker and pos.get("security_type") == "STK":
                    position_size = pos.get("position", 0)
                    break

            if position_size == 0:
                pass
        except Exception as e:
            logger.error(f"Error getting position for {ticker}: {e}")
            logger.error(traceback.format_exc())

        # Store position size in result
        result["position"] = position_size

        # Get options chain - use IB data (frozen when market is closed)
        options_data = {}
        if conn and conn.is_connected():
            try:
                # Calculate target strikes
                call_strike = round(stock_price * (1 + otm_percentage / 100), 2)
                put_strike = round(stock_price * (1 - otm_percentage / 100), 2)

                # Adjust to standard strike increments
                call_strike = self._adjust_to_standard_strike(call_strike)
                put_strike = self._adjust_to_standard_strike(put_strike)

                options = []

                # Get default expiration date (closest Friday) if not specified
                default_expiration = following_friday()

                # Use provided expiration if available, otherwise use default
                target_expiration = expiration if expiration else default_expiration

                # Get call options if requested
                if not option_type or option_type == "CALL":
                    call_option = conn.get_option_chain(
                        ticker, target_expiration, "C", call_strike
                    )
                    if call_option:
                        options.append(call_option)

                # Get put options if requested
                if not option_type or option_type == "PUT":
                    put_option = conn.get_option_chain(
                        ticker, target_expiration, "P", put_strike
                    )
                    if put_option:
                        options.append(put_option)

                if options:
                    options_data = self._process_options_chain(
                        options, ticker, stock_price, otm_percentage, option_type
                    )
                else:
                    if is_market_open:
                        logger.warning(
                            f"Could not get real-time options chain for {ticker}"
                        )
                    else:
                        logger.warning(
                            f"Could not get frozen options chain for {ticker}"
                        )
            except Exception as e:
                logger.error(f"Error getting options chain for {ticker}: {e}")
                logger.error(traceback.format_exc())

        # If we couldn't get any options data
        if not options_data:
            logger.error(f"No options data received from IB for {ticker}")
            options_data = {"error": "No options data available"}

        # Add options data to result
        result.update(options_data)

        return result

    def _process_options_chain(
        self, options_chains, ticker, stock_price, otm_percentage, option_type=None
    ):
        """
        Process options chain data and format it with flattened structure

        Args:
            options_chains (list): List of option chain objects from IB
            ticker (str): Stock symbol
            stock_price (float): Current stock price
            otm_percentage (float): OTM percentage to filter strikes
            option_type (str): Type of options to return ('CALL' or 'PUT'), if None returns both

        Returns:
            dict: Formatted options data
        """
        try:
            if not options_chains:
                logger.error(f"No options data available for {ticker}")
                return {}

            result = {
                "symbol": ticker,
                "stock_price": stock_price,
                "otm_percentage": otm_percentage,
                "calls": [],
                "puts": [],
            }

            # Process each option chain in the list
            for chain in options_chains:
                # Extract the list of options from the chain
                if not chain or "options" not in chain:
                    logger.warning(f"Invalid option chain format for {ticker}: {chain}")
                    continue

                options_list = chain.get("options", [])

                # Process each option in the chain
                for option in options_list:
                    try:
                        # Skip if we're filtering by option type and this doesn't match
                        current_option_type = option.get("option_type")
                        if option_type and current_option_type:
                            if (
                                option_type == "CALL" and current_option_type != "CALL"
                            ) or (
                                option_type == "PUT" and current_option_type != "PUT"
                            ):
                                continue

                        # Calculate ATM factor for Greeks
                        strike = option.get("strike", 0)
                        # Handle NaN and missing values
                        bid = option.get("bid", 0)
                        ask = option.get("ask", 0)
                        last = option.get("last", 0)

                        # If last is 0 or NaN, use mid price
                        if last == 0 or isinstance(last, float) and math.isnan(last):
                            last = (
                                (bid + ask) / 2
                                if bid > 0 and ask > 0
                                else max(bid, ask, 0)
                            )

                        # Handle NaN values for Greeks
                        iv = option.get("implied_volatility", 0)
                        if isinstance(iv, float) and math.isnan(iv):
                            iv = 0

                        delta = option.get("delta", 0)
                        if isinstance(delta, float) and math.isnan(delta):
                            delta = 0

                        gamma = option.get("gamma", 0)
                        if isinstance(gamma, float) and math.isnan(gamma):
                            gamma = 0

                        theta = option.get("theta", 0)
                        if isinstance(theta, float) and math.isnan(theta):
                            theta = 0

                        vega = option.get("vega", 0)
                        if isinstance(vega, float) and math.isnan(vega):
                            vega = 0

                        open_interest = option.get("open_interest", 0)
                        if isinstance(open_interest, float) and math.isnan(
                            open_interest
                        ):
                            open_interest = 0

                        # Format option data with flattened structure
                        option_data = {
                            "symbol": f"{ticker}{option.get('expiration')}{'C' if option.get('option_type') == 'CALL' else 'P'}{int(strike)}",
                            "strike": strike,
                            "expiration": option.get("expiration"),
                            "option_type": option.get("option_type"),
                            "bid": bid,
                            "ask": ask,
                            "last": last,
                            "open_interest": int(open_interest),
                            "implied_volatility": round(iv * 100, 2)
                            if iv is not None and iv < 1 and iv > 0
                            else (
                                0 if iv is None else round(iv, 2)
                            ),  # Handle percentage vs decimal
                            "delta": round(delta, 5) if delta is not None else 0,
                            "gamma": round(gamma, 5) if gamma is not None else 0,
                            "theta": round(theta, 5) if theta is not None else 0,
                            "vega": round(vega, 5) if vega is not None else 0,
                        }

                        # Calculate and add flattened earnings data based on option type
                        if option.get("option_type") == "CALL":
                            position_qty = (
                                100  # Assume 100 shares per standard position
                            )
                            max_contracts = int(
                                position_qty / 100
                            )  # Each contract represents 100 shares
                            premium_per_contract = (
                                last * 100
                            )  # Premium per contract (100 shares)
                            total_premium = premium_per_contract * max_contracts

                            # Ensure we don't divide by zero or NaN
                            if strike > 0 and max_contracts > 0:
                                return_on_capital = (
                                    total_premium / (strike * 100 * max_contracts)
                                ) * 100
                            else:
                                return_on_capital = 0

                            # Add flattened earnings data
                            option_data["earnings_max_contracts"] = max_contracts
                            option_data["earnings_premium_per_contract"] = round(
                                premium_per_contract, 2
                            )
                            option_data["earnings_total_premium"] = round(
                                total_premium, 2
                            )
                            option_data["earnings_return_on_capital"] = round(
                                return_on_capital, 2
                            )

                            # Add to calls list directly
                            result["calls"].append(option_data)

                        elif option.get("option_type") == "PUT":
                            position_value = (
                                strike * 100 * int(100 / 100)
                            )  # Cash needed to secure puts
                            max_contracts = (
                                1
                                if strike <= 0
                                else int(position_value / (strike * 100))
                            )
                            premium_per_contract = last * 100  # Premium per contract
                            total_premium = premium_per_contract * max_contracts

                            # Ensure we don't divide by zero or NaN
                            if position_value > 0:
                                return_on_cash = (total_premium / position_value) * 100
                            else:
                                return_on_cash = 0

                            # Add flattened earnings data
                            option_data["earnings_max_contracts"] = max_contracts
                            option_data["earnings_premium_per_contract"] = round(
                                premium_per_contract, 2
                            )
                            option_data["earnings_total_premium"] = round(
                                total_premium, 2
                            )
                            option_data["earnings_return_on_cash"] = round(
                                return_on_cash, 2
                            )

                            # Add to puts list directly
                            result["puts"].append(option_data)

                    except Exception as e:
                        logger.error(
                            f"Error processing individual option in chain for {ticker}: {str(e)}"
                        )
                        logger.error(traceback.format_exc())

            # Sort options by strike price
            result["calls"] = sorted(result["calls"], key=lambda x: x["strike"])
            result["puts"] = sorted(result["puts"], key=lambda x: x["strike"])

            # Final sanitization to ensure no NaN values exist in the result
            self._sanitize_result(result)

            return result

        except Exception as e:
            logger.error(f"Error processing options chain for {ticker}: {str(e)}")
            logger.error(traceback.format_exc())
            return {}

    def _sanitize_result(self, result):
        """
        Sanitize the result dictionary by replacing any NaN values with 0

        Args:
            result (dict): The result dictionary to sanitize
        """
        if not result or not isinstance(result, dict):
            return

        # Helper function to recursively sanitize dictionaries
        def sanitize_dict(d):
            if not isinstance(d, dict):
                return

            for key, value in d.items():
                # Check if value is NaN
                if isinstance(value, float) and math.isnan(value):
                    d[key] = 0
                # Recursively sanitize nested dictionaries
                elif isinstance(value, dict):
                    sanitize_dict(value)
                # Sanitize items in lists
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            sanitize_dict(item)

        # Sanitize the entire result dictionary
        sanitize_dict(result)

    def check_pending_orders(self):
        orders = self.db.get_orders(
            status_filter=["processing", "canceling", "submission_unknown"], limit=1000
        )
        if not orders:
            return {"success": True, "updated_orders": []}
        conn = self._ensure_connection()
        if not conn:
            return {"success": False, "error": "Cannot connect to the broker"}
        updated = []
        try:
            # One broker snapshot for the whole batch instead of a request per order.
            trades = list(conn.ib.reqAllOpenOrders()) + list(
                conn.ib.reqCompletedOrders(apiOnly=True)
            )
            for order in orders:
                if not order.get("ib_order_id"):
                    continue
                status = conn.check_order_status(
                    order["ib_order_id"],
                    order.get("ib_perm_id"),
                    order.get("ib_client_id"),
                    trades,
                )
                if not status or status["status"] == "NotFound":
                    continue  # Missing from a snapshot does not mean canceled or filled.
                local_status = self._local_order_status(status["status"])
                details = {
                    "ib_status": status["status"],
                    "filled": status["filled"],
                    "remaining": status["remaining"],
                    "avg_fill_price": status["avg_fill_price"],
                    "commission": status.get("commission", 0),
                }
                if self.db.update_order_status(
                    order["id"], local_status, True, details
                ):
                    updated.append(
                        {**order, **details, "status": local_status, "executed": True}
                    )
            return {"success": True, "updated_orders": updated}
        except Exception as exc:
            logger.exception("Order reconciliation failed")
            return {"success": False, "error": str(exc)}
        finally:
            conn.disconnect()

    def cancel_order(self, order_id):
        order = self.db.get_order(order_id)
        if not order:
            return {"success": False, "error": "Order not found"}, 404
        if order["status"] == "pending":
            # Atomic predicate prevents cancellation racing with submission.
            if self.db.cancel_pending_order(order_id):
                return {"success": True, "status": "canceled"}, 200
            return {
                "success": False,
                "error": "Order state changed; refresh and try again",
            }, 409
        if order["status"] not in ("processing", "canceling", "submission_unknown"):
            return {
                "success": False,
                "error": "Order cannot be canceled in its current state",
            }, 409
        if self.config.get("readonly", True):
            return {"success": False, "error": "Broker connection is read-only"}, 403
        if order.get("ib_client_id") is None:
            return {
                "success": False,
                "error": "Legacy order has no broker client identity; cancel it in TWS",
            }, 409
        conn = IBConnection(
            host=self.config.get("host", "127.0.0.1"),
            port=self.config.get("port", 7497),
            client_id=order["ib_client_id"],
            readonly=False,
            timeout=self.config.get("timeout", 10),
        )
        try:
            # IB requires cancellation from the client that owns the order.
            if self.connection and self.connection.client_id == order["ib_client_id"]:
                self.connection.disconnect()
            if not conn.connect():
                return {
                    "success": False,
                    "error": "Cannot connect to the order's broker client; order remains active",
                }, 503
            result = conn.cancel_order(order["ib_order_id"])
            if not result.get("success"):
                return {
                    "success": False,
                    "error": result.get("error", "Cancellation failed"),
                }, 502
            if not self.db.update_order_status(
                order_id, "canceling", True, {"ib_status": "PendingCancel"}
            ):
                return {
                    "success": False,
                    "error": "Cancellation requested, but saving status failed. Check TWS.",
                }, 500
            return {
                "success": True,
                "status": "canceling",
                "ib_status": "PendingCancel",
            }, 200
        except Exception as exc:
            logger.exception("Cancellation failed; preserving order state")
            return {"success": False, "error": str(exc)}, 502
        finally:
            conn.disconnect()

    def get_stock_price(self, ticker):
        """
        Get just the current stock price for a ticker without fetching options.
        This is a lightweight method for the stock-price endpoint.

        Args:
            ticker (str): Ticker symbol

        Returns:
            float: Current stock price
        """
        try:
            # Use _ensure_connection to get or create a connection
            conn = self._ensure_connection()
            if not conn:
                logger.error("Failed to establish connection to IB")
                return 0

            # Use the existing get_stock_price method from the connection
            stock_price = conn.get_stock_price(ticker)

            # Check if we got a valid price
            if (
                stock_price is None
                or not math.isfinite(stock_price)
                or stock_price <= 0
            ):
                logger.warning(f"Got invalid stock price for {ticker}: {stock_price}")
                return 0

            return stock_price

        except Exception as e:
            logger.error(f"Error getting stock price for {ticker}: {str(e)}")
            logger.error(traceback.format_exc())
            return 0

    def get_scanner(self):
        from core.option_scanner import OptionScanner

        conn = self._ensure_connection()
        if not conn:
            raise ConnectionError(
                "Cannot connect to the broker. Check Settings and your broker session."
            )
        if not hasattr(conn, "_scanner"):
            conn._scanner = OptionScanner(conn)
        return conn._scanner

    def get_option_expirations(self, ticker):
        from core.option_scanner import choose_expiration

        scanner = self.get_scanner()
        stock, chain = scanner.ib._run(scanner.metadata(ticker))
        selected, target = choose_expiration(chain.expirations)
        today = datetime.now().strftime("%Y%m%d")
        return {
            "ticker": ticker,
            "default_expiration": selected,
            "target_friday": target,
            "expirations": [
                {"value": exp, "label": f"{exp[:4]}-{exp[4:6]}-{exp[6:]}"}
                for exp in sorted(chain.expirations)
                if exp >= today
            ],
        }
