"""
Database module for SQLite logging of trades
"""

import sqlite3
from datetime import datetime
from pathlib import Path
import traceback


class OptionsDatabase:
    """
    Class for logging options recommendations to SQLite database
    """

    def __init__(self, db_name=None):
        """
        Initialize the options database

        Args:
            db_path (str, optional): Path to the SQLite database.
                                    If None, creates 'options.db' in current directory.
        """
        if db_name is None:
            db_path = Path.cwd() / "options.db"
        else:
            db_path = Path.cwd() / db_name

        self.db_path = db_path
        self._create_tables_if_not_exist()
        self._migrate_database()

    def _create_tables_if_not_exist(self):
        """Create necessary tables with flattened structure"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create recommendations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                option_type TEXT NOT NULL,
                action TEXT NOT NULL,
                strike REAL NOT NULL,
                expiration TEXT NOT NULL,
                premium REAL,
                details TEXT
            )
        """)

        # Create orders table with flattened structure
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                option_type TEXT NOT NULL,
                action TEXT NOT NULL,
                strike REAL NOT NULL,
                expiration TEXT NOT NULL,
                premium REAL,
                quantity INTEGER DEFAULT 1,
                status TEXT DEFAULT 'pending',
                executed BOOLEAN DEFAULT 0,
                
                -- Price data
                bid REAL DEFAULT 0,
                ask REAL DEFAULT 0,
                last REAL DEFAULT 0,
                
                -- Greeks
                delta REAL DEFAULT 0,
                gamma REAL DEFAULT 0,
                theta REAL DEFAULT 0,
                vega REAL DEFAULT 0,
                implied_volatility REAL DEFAULT 0,
                
                -- Market data
                open_interest INTEGER DEFAULT 0,
                volume INTEGER DEFAULT 0,
                is_mock BOOLEAN DEFAULT 0,
                
                -- Earnings data
                earnings_max_contracts INTEGER DEFAULT 0,
                earnings_premium_per_contract REAL DEFAULT 0,
                earnings_total_premium REAL DEFAULT 0,
                earnings_return_on_cash REAL DEFAULT 0,
                earnings_return_on_capital REAL DEFAULT 0,
                
                -- Execution data
                ib_order_id TEXT,
                ib_status TEXT,
                filled INTEGER DEFAULT 0,
                remaining INTEGER DEFAULT 0,
                avg_fill_price REAL DEFAULT 0,
                
                -- Rollover data
                isRollover BOOLEAN DEFAULT 0
            )
        """)

        conn.commit()
        conn.close()

    def _migrate_database(self):
        """
        Run database migrations for backward compatibility

        This function checks for missing columns in existing tables
        and adds them if necessary.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get the current columns in the orders table
            cursor.execute("PRAGMA table_info(orders)")
            columns = cursor.fetchall()
            column_names = [column[1] for column in columns]

            for name, definition in {
                "order_type": "TEXT DEFAULT 'LIMIT'",
                "limit_price": "REAL",
                "ib_client_id": "INTEGER",
                "ib_perm_id": "INTEGER",
                "commission": "REAL DEFAULT 0",
            }.items():
                if name not in column_names:
                    cursor.execute(f"ALTER TABLE orders ADD COLUMN {name} {definition}")

            # Check if we need to add the isRollover column
            if "isRollover" not in column_names:
                print("Running migration: Adding isRollover column to orders table")
                cursor.execute(
                    "ALTER TABLE orders ADD COLUMN isRollover BOOLEAN DEFAULT 0"
                )
                print("Migration completed: isRollover column added")

                # Look for paired orders that might be rollover orders
                # For simplicity, we'll identify orders created close in time with opposite actions
                cursor.execute("""
                    WITH order_pairs AS (
                        SELECT o1.id as buy_id, o2.id as sell_id
                        FROM orders o1
                        JOIN orders o2 ON o1.ticker = o2.ticker 
                                      AND o1.option_type = o2.option_type
                                      AND datetime(o1.timestamp) BETWEEN datetime(o2.timestamp, '-2 minutes') AND datetime(o2.timestamp, '+2 minutes')
                                      AND o1.action = 'BUY' AND o2.action = 'SELL'
                                      AND o1.isRollover = 0 AND o2.isRollover = 0
                    )
                    SELECT buy_id, sell_id FROM order_pairs
                """)

                potential_rollover_pairs = cursor.fetchall()

                if potential_rollover_pairs:
                    print(
                        f"Found {len(potential_rollover_pairs)} potential rollover order pairs"
                    )

                    for buy_id, sell_id in potential_rollover_pairs:
                        # Update the buy order
                        cursor.execute(
                            """
                            UPDATE orders
                            SET isRollover = 1
                            WHERE id = ?
                        """,
                            (buy_id,),
                        )

                        # Update the sell order
                        cursor.execute(
                            """
                            UPDATE orders
                            SET isRollover = 1
                            WHERE id = ?
                        """,
                            (sell_id,),
                        )

                    print(
                        f"Migration: Marked {len(potential_rollover_pairs) * 2} orders as potential rollovers"
                    )

            conn.commit()
            conn.close()
            print("Database migration completed successfully")
        except Exception as e:
            print(f"Error during database migration: {str(e)}")
            print(traceback.format_exc())

    def save_order(self, order_data, connection=None):
        """
        Save an option order to the database using flattened structure

        Args:
            order_data (dict): Option order data

        Returns:
            int: ID of the inserted record
        """
        try:
            conn = connection or sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Extract data from order
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ticker = order_data.get("ticker", "")
            option_type = order_data.get("option_type", "")
            action = order_data.get(
                "action", "SELL"
            )  # Default action is sell for options
            strike = order_data.get("strike", 0)
            expiration = order_data.get("expiration", "")
            premium = order_data.get("premium", 0)
            quantity = order_data.get("quantity", 1)

            # Extract pricing data
            bid = order_data.get("bid", 0)
            ask = order_data.get("ask", 0)
            last = order_data.get("last", 0)

            # Extract greeks
            delta = order_data.get("delta", 0)
            gamma = order_data.get("gamma", 0)
            theta = order_data.get("theta", 0)
            vega = order_data.get("vega", 0)
            implied_volatility = order_data.get("implied_volatility", 0)

            # Extract market data
            open_interest = order_data.get("open_interest", 0)
            volume = order_data.get("volume", 0)
            is_mock = order_data.get("is_mock", False)

            # Extract earnings data
            earnings_max_contracts = order_data.get("earnings_max_contracts", 0)
            earnings_premium_per_contract = order_data.get(
                "earnings_premium_per_contract", 0
            )
            earnings_total_premium = order_data.get("earnings_total_premium", 0)
            earnings_return_on_cash = order_data.get("earnings_return_on_cash", 0)
            earnings_return_on_capital = order_data.get("earnings_return_on_capital", 0)

            # Extract rollover specific data
            is_rollover = order_data.get("isRollover", False)

            # Insert order with all fields using the flattened structure
            cursor.execute(
                """
                INSERT INTO orders 
                (timestamp, ticker, option_type, action, strike, expiration, premium, quantity, 
                 bid, ask, last, delta, gamma, theta, vega, implied_volatility, 
                 open_interest, volume, is_mock,
                 earnings_max_contracts, earnings_premium_per_contract, 
                 earnings_total_premium, earnings_return_on_cash, 
                 earnings_return_on_capital, status, executed, isRollover)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    timestamp,
                    ticker,
                    option_type,
                    action,
                    strike,
                    expiration,
                    premium,
                    quantity,
                    bid,
                    ask,
                    last,
                    delta,
                    gamma,
                    theta,
                    vega,
                    implied_volatility,
                    open_interest,
                    volume,
                    is_mock,
                    earnings_max_contracts,
                    earnings_premium_per_contract,
                    earnings_total_premium,
                    earnings_return_on_cash,
                    earnings_return_on_capital,
                    "pending",
                    False,
                    is_rollover,
                ),
            )

            record_id = cursor.lastrowid
            conn.execute(
                "UPDATE orders SET order_type = ?, limit_price = ? WHERE id = ?",
                (
                    order_data.get("order_type", "LIMIT"),
                    order_data.get("limit_price"),
                    record_id,
                ),
            )
            if connection is None:
                conn.commit()

            return record_id
        except Exception as e:
            if connection is not None:
                raise
            print(f"Error saving order: {str(e)}")
            return None
        finally:
            if connection is None and "conn" in locals():
                conn.close()

    def save_orders(self, orders):
        """Save all drafts or rollover legs in one transaction."""
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                return [self.save_order(order, connection=conn) for order in orders]
        finally:
            conn.close()

    def update_draft_prices(self, originals, prepared):
        """Apply verified draft prices atomically, never touching a submitted order."""
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                for original, order in zip(originals, prepared):
                    changed = conn.execute(
                        "UPDATE orders SET limit_price = ?, premium = ? "
                        "WHERE id = ? AND status = 'pending' "
                        "AND limit_price IS ? AND quantity = ?",
                        (
                            order.get("limit_price"),
                            order.get("premium"),
                            original["id"],
                            original.get("limit_price"),
                            original["quantity"],
                        ),
                    ).rowcount
                    if changed != 1:
                        raise ValueError(
                            "Draft changed while verifying prices. Refresh and try again."
                        )
        finally:
            conn.close()

    def cancel_pending_order(self, order_id):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                return (
                    conn.execute(
                        "UPDATE orders SET status = 'canceled', executed = 1 WHERE id = ? AND status = 'pending'",
                        (order_id,),
                    ).rowcount
                    == 1
                )
        finally:
            conn.close()

    def claim_order(self, order_id):
        """Reserve a pending order once, even across concurrent server workers."""
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                result = conn.execute(
                    "UPDATE orders SET status = 'submitting' WHERE id = ? AND status = 'pending'",
                    (order_id,),
                )
                return result.rowcount == 1
        finally:
            conn.close()

    def get_pending_orders(self, executed=False, limit=50, isRollover=None):
        """
        Get pending orders from the database

        Args:
            executed (bool): Whether to return executed orders (True) or pending orders (False)
            limit (int): Maximum number of orders to return
            isRollover (bool): Whether to filter for rollover orders

        Returns:
            list: List of order dictionaries
        """
        if executed:
            # Return executed orders (completed, cancelled, etc.)
            return self.get_orders(
                executed=executed, limit=limit, isRollover=isRollover
            )
        else:
            # Return pending/processing orders specifically
            return self.get_orders(
                status_filter=[
                    "pending",
                    "submitting",
                    "processing",
                    "canceling",
                    "submission_unknown",
                ],
                limit=limit,
                isRollover=isRollover,
            )

    def update_order_status(
        self, order_id, status, executed=False, execution_details=None
    ):
        """
        Update the status of an order

        Args:
            order_id (int): ID of the order to update
            status (str): New status
            executed (bool): Whether the order has been executed
            execution_details (dict): Optional details about the execution

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Start with basic update query
            update_query = """
                UPDATE orders
                SET status = ?, executed = ?
                WHERE id = ?
            """
            params = [status, executed]

            # If we have execution details, update those fields too
            if execution_details and isinstance(execution_details, dict):
                set_clauses = []

                # Map execution details to database fields
                field_mappings = {
                    "ib_order_id": "ib_order_id",
                    "ib_status": "ib_status",
                    "filled": "filled",
                    "remaining": "remaining",
                    "avg_fill_price": "avg_fill_price",
                    "ib_client_id": "ib_client_id",
                    "ib_perm_id": "ib_perm_id",
                    "commission": "commission",
                    "is_mock": "is_mock",
                }

                # Check for each field in the mapping
                for api_field, db_field in field_mappings.items():
                    if api_field in execution_details:
                        set_clauses.append(f"{db_field} = ?")
                        params.append(execution_details[api_field])

                # If we have additional fields to set, add them to the query
                if set_clauses:
                    # Reconstruct the query with the additional fields
                    update_query = """
                        UPDATE orders
                        SET status = ?, executed = ?, {}
                        WHERE id = ?
                    """.format(", ".join(set_clauses))

            # Execute the query
            params.append(order_id)
            cursor.execute(update_query, params)

            # Check if any rows were affected
            affected_rows = cursor.rowcount

            conn.commit()

            conn.close()

            return affected_rows > 0
        except Exception as e:
            print(f"ERROR: Error updating order status: {str(e)}")
            print(f"ERROR: {traceback.format_exc()}")
            return False

    def remove_local_order(self, order_id):
        """Forget a stale broker-linked record without contacting the broker."""
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                return (
                    conn.execute(
                        "DELETE FROM orders WHERE id = ? AND status IN ('processing', 'canceling', 'submission_unknown')",
                        (order_id,),
                    ).rowcount
                    == 1
                )
        finally:
            conn.close()

    def delete_order(self, order_id):
        """
        Delete an order from the database

        Args:
            order_id (int): ID of the order to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                DELETE FROM orders
                WHERE id = ? AND status = 'pending'
            """,
                (order_id,),
            )

            # Check if any rows were affected
            affected_rows = cursor.rowcount

            conn.commit()
            conn.close()

            # Return True if at least one row was deleted
            return affected_rows > 0
        except Exception as e:
            print(f"Error deleting order: {str(e)}")
            return False

    def update_order_quantity(self, order_id, quantity):
        """
        Update the quantity of a specific order

        Args:
            order_id (int): ID of the order to update
            quantity (int): New quantity value

        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get current order to validate it exists and check its status
            cursor.execute(
                """
                SELECT status FROM orders
                WHERE id = ?
            """,
                (order_id,),
            )

            order = cursor.fetchone()
            if not order:
                print(f"No order found with ID {order_id}")
                conn.close()
                return False

            # Only update if the order is in 'pending' status
            if order[0] != "pending":
                print(f"Cannot update quantity for order with status '{order[0]}'")
                conn.close()
                return False

            # Update the order quantity
            cursor.execute(
                """
                UPDATE orders 
                SET quantity = ?,
                    timestamp = ?
                WHERE id = ? AND status = 'pending'
            """,
                (quantity, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), order_id),
            )

            # Check if any rows were updated
            affected_rows = cursor.rowcount

            conn.commit()
            conn.close()

            if affected_rows > 0:
                print(
                    f"Successfully updated quantity to {quantity} for order {order_id}"
                )
                return True
            else:
                print(f"No changes made to order {order_id}")
                return False

        except Exception as e:
            error_msg = f"Error updating order quantity: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            return False

    def get_order(self, order_id):
        """
        Get a specific order by ID

        Args:
            order_id (int): ID of the order to retrieve

        Returns:
            dict: Order data or None if not found
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # This enables column access by name
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM orders
                WHERE id = ?
            """,
                (order_id,),
            )

            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            # Convert row to dictionary
            order = dict(row)
            return order

        except Exception as e:
            print(f"Error getting order: {str(e)}")
            return None

    def get_orders(
        self,
        status=None,
        executed=None,
        ticker=None,
        limit=50,
        status_filter=None,
        isRollover=None,
    ):
        """
        Get orders from the database with flexible filtering

        Args:
            status (str): Filter by a single status (e.g., 'pending', 'completed', 'cancelled')
            executed (bool): Filter by executed flag
            ticker (str): Filter by ticker symbol
            limit (int): Maximum number of orders to return
            status_filter (list): Filter by multiple status values
            isRollover (bool): Filter by rollover flag (None = no filter)

        Returns:
            list: List of order dictionaries
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # This enables column access by name
            cursor = conn.cursor()

            # Build the query based on filters
            query = "SELECT * FROM orders WHERE 1=1"
            params = []

            # Handle status filtering (single status or list of statuses)
            if (
                status_filter is not None
                and isinstance(status_filter, list)
                and status_filter
            ):
                placeholders = ", ".join(["?" for _ in status_filter])
                query += f" AND status IN ({placeholders})"
                params.extend(status_filter)
            elif status is not None:
                query += " AND status = ?"
                params.append(status)

            if executed is not None:
                query += " AND executed = ?"
                params.append(executed)

            if ticker is not None:
                query += " AND ticker = ?"
                params.append(ticker)

            # Add rollover filter if specified
            if isRollover is not None:
                query += " AND isRollover = ?"
                params.append(isRollover)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)

            rows = cursor.fetchall()
            conn.close()

            # Convert rows to dictionaries
            orders = []
            for row in rows:
                order = dict(row)
                orders.append(order)

            return orders
        except Exception as e:
            print(f"Error getting orders: {str(e)}")
            return []
