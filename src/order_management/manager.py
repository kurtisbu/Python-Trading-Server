import sqlite3
import uuid
from datetime import datetime, timezone
import logging
import json # For handling JSON data storage
import os
import copy # Keep for deepcopying objects before they might be mutated or for return values

logger = logging.getLogger(__name__)

# Determine project root to place the DB file there
# This assumes manager.py is in src/order_management/
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATABASE_NAME = "trading_orders.db"
DATABASE_PATH = os.path.join(PROJECT_ROOT_DIR, DATABASE_NAME)

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row # Access columns by name
    return conn

def initialize_database():
    """Creates the orders table if it doesn't exist."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                internal_order_id TEXT PRIMARY KEY,
                timestamp_received TEXT NOT NULL,
                signal_data_json TEXT,
                processed_params_json TEXT,
                status TEXT NOT NULL,
                oanda_order_id TEXT,
                oanda_trade_id TEXT,
                fill_price REAL,
                fill_quantity REAL,
                broker_response_json TEXT,
                error_message TEXT,
                timestamp_created TEXT NOT NULL,
                timestamp_updated TEXT NOT NULL
            )
        """)
        conn.commit()
        logger.info(f"Database initialized/checked at {DATABASE_PATH}. Orders table is ready.")
    except sqlite3.Error as e:
        logger.critical(f"Database initialization error: {e}", exc_info=True)
        raise # Reraise the exception to signal a critical failure
    finally:
        if conn:
            conn.close()

def generate_internal_order_id():
    return str(uuid.uuid4())

def create_order_record(signal_data: dict, processed_params: dict):
    internal_id = generate_internal_order_id()
    now_utc_iso = datetime.now(timezone.utc).isoformat()

    order_data_tuple = (
        internal_id,
        now_utc_iso, # timestamp_received (same as created for this initial record)
        json.dumps(signal_data) if signal_data else None,
        json.dumps(processed_params) if processed_params else None,
        "PENDING_SUBMISSION", # status
        None, # oanda_order_id
        None, # oanda_trade_id
        None, # fill_price
        None, # fill_quantity
        None, # broker_response_json
        None, # error_message
        now_utc_iso, # timestamp_created
        now_utc_iso  # timestamp_updated
    )

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        sql = """
            INSERT INTO orders (
                internal_order_id, timestamp_received, signal_data_json, processed_params_json, 
                status, oanda_order_id, oanda_trade_id, fill_price, fill_quantity, 
                broker_response_json, error_message, timestamp_created, timestamp_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor.execute(sql, order_data_tuple)
        conn.commit()
        logger.info(f"Created order record ID: {internal_id} in DB with status PENDING_SUBMISSION.")
        return internal_id
    except sqlite3.Error as e:
        logger.error(f"Failed to create order record ID {internal_id} in DB: {e}", exc_info=True)
        return None # Or raise exception
    finally:
        if conn:
            conn.close()

def update_order_with_submission_response(internal_order_id: str, oanda_response: dict = None, oanda_error: str = None):
    """
    Updates an existing order record with the response from a broker after submission.
    This function is now generic and can parse responses from different brokers.
    """
    # For clarity, let's rename the main response variable
    broker_response = oanda_response
    broker_error = oanda_error

    now_utc = datetime.now(timezone.utc)
    updated_record = None

    # This part of the logic remains the same
    db_uri_for_verification = f"file:{DATABASE_PATH}?mode=rw" # Ensure we can write
    conn = None
    try:
        conn = sqlite3.connect(db_uri_for_verification, uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find the order to update
        cursor.execute("SELECT * FROM orders WHERE internal_order_id = ?", (internal_order_id,))
        order_row = cursor.fetchone()
        if not order_row:
            logger.error(f"Could not find order with internal_order_id: {internal_order_id} to update.")
            return None

        # --- THIS IS THE UPDATED LOGIC ---

        fields_to_update = {
            "timestamp_updated": now_utc.isoformat(),
            "broker_response_json": json.dumps(broker_response) if broker_response else None
        }

        if broker_error:
            fields_to_update["status"] = "ERROR_SUBMITTING"
            if "Oanda" in broker_error or "Alpaca" in broker_error:
                fields_to_update["status"] = "REJECTED_BY_BROKER"
            fields_to_update["error_message"] = broker_error
            logger.error(f"Order ID {internal_order_id} failed. Error: {broker_error}. Response: {broker_response}")
        elif broker_response:
            fields_to_update["status"] = "SUBMITTED_TO_BROKER" # Default success status

            # Try to parse Oanda-style responses
            if "orderFillTransaction" in broker_response:
                fill_tx = broker_response["orderFillTransaction"]
                fields_to_update["status"] = "FILLED"
                fields_to_update["oanda_order_id"] = fill_tx.get("orderID")
                # ... (rest of Oanda fill parsing logic as before)
                if fill_tx.get("tradeOpened"):
                    fields_to_update["oanda_trade_id"] = fill_tx.get("tradeOpened", {}).get("tradeID")
                fields_to_update["fill_price"] = float(fill_tx.get("price", 0.0))
                fields_to_update["fill_quantity"] = float(fill_tx.get("units", 0.0))

            elif "orderCreateTransaction" in broker_response:
                create_tx = broker_response["orderCreateTransaction"]
                fields_to_update["status"] = "ORDER_ACCEPTED"
                fields_to_update["oanda_order_id"] = create_tx.get("id") # Oanda's ID for pending orders

            elif "orderCancelTransaction" in broker_response:
                cancel_tx = broker_response["orderCancelTransaction"]
                fields_to_update["status"] = "CANCELLED" # Simplified status
                fields_to_update["oanda_order_id"] = cancel_tx.get("orderID")
                fields_to_update["error_message"] = f"Order cancelled by broker. Reason: {cancel_tx.get('reason')}"

            # Try to parse Alpaca-style responses
            # A successful Alpaca order submission returns an order entity
            elif "id" in broker_response and "client_order_id" in broker_response:
                # Check the status from Alpaca to set our internal status
                alpaca_status = broker_response.get("status")
                if alpaca_status in ["accepted", "pending_new", "new"]:
                    fields_to_update["status"] = "ORDER_ACCEPTED"
                elif alpaca_status == "filled":
                    fields_to_update["status"] = "FILLED"
                    # Parse fill details if available
                    fields_to_update["fill_quantity"] = float(broker_response.get("filled_qty", 0.0))
                    fields_to_update["fill_price"] = float(broker_response.get("filled_avg_price", 0.0))

                # This is the key fix: get the order ID from Alpaca's `id` field
                fields_to_update["oanda_order_id"] = broker_response.get("id")

        # --- END OF UPDATED LOGIC ---

        set_clauses = ", ".join([f"{key} = ?" for key in fields_to_update.keys()])
        values = list(fields_to_update.values())
        values.append(internal_order_id)
        sql = f"UPDATE orders SET {set_clauses} WHERE internal_order_id = ?"
        cursor.execute(sql, values)
        conn.commit()

        logger.info(f"Order ID {internal_order_id} updated in DB. New status: {fields_to_update.get('status')}")
        # Fetch and return the fully updated record
        return get_order_by_id(internal_order_id) # Uses its own connection

    except sqlite3.Error as e:
        logger.error(f"Failed to update order ID {internal_order_id} in DB: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()


def _db_row_to_dict(row: sqlite3.Row):
        """Converts a sqlite3.Row object to a dictionary, parsing JSON strings safely."""
        if row is None:
            return None
        
        # Convert sqlite3.Row to a standard dictionary to make it mutable
        order_dict = dict(row) 
        
        # Identify keys ending with '_json' that have non-null values.
        # These are candidates for transformation.
        # We create a list of these keys first, so we're not iterating over
        # the dictionary view that's being modified.
        keys_to_transform = [key for key in order_dict if key.endswith("_json") and order_dict[key] is not None]
        
        for key in keys_to_transform: # Iterate over the pre-collected list of keys
            json_string_value = order_dict[key] # Get the JSON string
            new_key = key[:-5] # Remove '_json' suffix (e.g., 'signal_data_json' -> 'signal_data')
            
            try:
                parsed_value = json.loads(json_string_value)
                order_dict[new_key] = parsed_value # Add the new key with the parsed JSON
            except json.JSONDecodeError:
                # Log the error and decide what to put in the new key's place
                logger.error(f"Error decoding JSON for key {key} in order {order_dict.get('internal_order_id')}. Raw value snippet: '{str(json_string_value)[:100]}...'")
                order_dict[new_key] = None # Or you could store the raw string, or a specific error marker
            
            del order_dict[key] # Remove the original key (e.g., 'signal_data_json') after processing
            
        return order_dict

def get_order_by_id(internal_order_id: str):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE internal_order_id = ?", (internal_order_id,))
        row = cursor.fetchone()
        return _db_row_to_dict(row)
    except sqlite3.Error as e:
        logger.error(f"Error fetching order ID {internal_order_id} from DB: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

def get_all_orders():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders ORDER BY timestamp_created DESC")
        rows = cursor.fetchall()
        return [_db_row_to_dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Error fetching all orders from DB: {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()

# --- Example Usage and Test (can be run directly) ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    logger.info("--- Testing Order Manager with SQLite ---")
    initialize_database() # Ensure DB and table exist

    # Clean up old test data if any - for repeatable tests
    conn_test = get_db_connection()
    conn_test.execute("DELETE FROM orders WHERE signal_data_json LIKE '%test_signal%'")
    conn_test.commit()
    conn_test.close()

    # Test 1: Create an order
    sample_signal = {"instrument": "EUR_USD", "action": "buy", "quantity": 100, "type":"test_signal"}
    sample_processed = {"instrument": "EUR_USD", "units": 100, "order_type": "market"}
    new_id = create_order_record(sample_signal, sample_processed)
    print(f"Created Order ID: {new_id}")

    retrieved_order = get_order_by_id(new_id)
    print(f"Retrieved Order (Initial): {retrieved_order}")
    assert retrieved_order["status"] == "PENDING_SUBMISSION"
    assert retrieved_order["signal_data"]["type"] == "test_signal" # Check JSON parsing

    # Test 2: Update with a simulated successful Oanda fill response
    mock_oanda_fill_response = {
        "orderFillTransaction": {
            "id": "DB_1234", "orderID": "DB_OANDA_ORDER_5678",
            "tradeOpened": {"tradeID": "DB_TRADE_91011"},
            "price": "1.09500", "units": "100.00", "reason": "MARKET_ORDER"
        }, "relatedTransactionIDs": ["DB_1234"]
    }
    update_order_with_submission_response(new_id, oanda_response=mock_oanda_fill_response)
    updated_order_fill = get_order_by_id(new_id)
    print(f"Updated Order (Fill): {updated_order_fill}")
    assert updated_order_fill["status"] == "FILLED"
    assert updated_order_fill["oanda_trade_id"] == "DB_TRADE_91011"
    assert updated_order_fill["broker_response"]["orderFillTransaction"]["id"] == "DB_1234" # Check JSON parsing

    # Test 3: Get all orders
    all_orders_data = get_all_orders()
    print(f"All Orders ({len(all_orders_data)} current):")
    found_new_id = any(o['internal_order_id'] == new_id for o in all_orders_data)
    assert found_new_id, f"Order {new_id} not found in all_orders"

    logger.info("--- Order Manager SQLite Tests Complete ---")