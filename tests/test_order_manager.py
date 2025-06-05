# tests/test_order_manager.py
import pytest
import sqlite3
import json
import os
import sys
from datetime import datetime, timezone

# --- Add src directory to Python path for imports ---
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# --- End Path Adjustment ---

from order_management import manager as order_manager

# Define a URI for a named in-memory database with a shared cache.
# This allows multiple connections in the same process to access the same DB.
SHARED_DB_URI = "file:test_om_db?mode=memory&cache=shared"

@pytest.fixture(scope="function") # "function" scope ensures this runs for each test
def shared_db_setup(monkeypatch):
    """
    This fixture does three things for each test function that uses it:
    1. Patches `order_manager.get_db_connection` to return new connections 
       to the SHARED_DB_URI.
    2. Calls `order_manager.initialize_database()` to ensure the schema exists
       in the database at SHARED_DB_URI.
    3. After the test, it cleans up by dropping the 'orders' table from SHARED_DB_URI.
    """
    
    # 1. Define the function that will be used as the mock for get_db_connection
    def mock_get_connection_to_shared_db():
        conn = sqlite3.connect(SHARED_DB_URI)
        conn.row_factory = sqlite3.Row # Important for accessing columns by name
        return conn

    # Patch the manager's connection getter
    monkeypatch.setattr(order_manager, 'get_db_connection', mock_get_connection_to_shared_db)
    
    # 2. Initialize the schema using the manager's own function.
    # This will use the patched get_db_connection.
    order_manager.initialize_database()

    yield # The test runs at this point

    # 3. Teardown: Clean up the database by dropping the table
    # This ensures the next test starts with a truly clean slate in the shared memory space.
    conn_cleanup = sqlite3.connect(SHARED_DB_URI)
    cursor_cleanup = conn_cleanup.cursor()
    try:
        # It's safer to check if the table exists before dropping, or handle the error
        cursor_cleanup.execute("DROP TABLE orders")
        conn_cleanup.commit()
    except sqlite3.OperationalError as e:
        # This can happen if a test failed very early and the table wasn't created,
        # or if initialize_database itself failed.
        if "no such table" not in str(e).lower():
            # If it's not a "no such table" error, then it's unexpected.
            # For tests, we might just want to ensure it's clean, so logging might be enough.
            print(f"Note: Error during test DB cleanup, possibly table 'orders' didn't exist: {e}")
    finally:
        conn_cleanup.close()


# --- Test Cases ---

def test_order_manager_initialize_database_idempotency(monkeypatch):
    """
    Tests the order_manager.initialize_database() function for idempotency
    (can be called multiple times without error). This test uses its own isolated DB URI.
    """
    # Use a unique URI for this specific test to ensure complete isolation
    test_init_db_uri = "file:test_init_idempotency_db?mode=memory&cache=shared"

    def mock_get_for_this_specific_test():
        conn = sqlite3.connect(test_init_db_uri)
        # No need for row_factory here if we are not fetching results in initialize_database
        return conn

    monkeypatch.setattr(order_manager, 'get_db_connection', mock_get_for_this_specific_test)

    # First call - should create the table
    order_manager.initialize_database() 

    # Second call - should not error due to "IF NOT EXISTS"
    try:
        order_manager.initialize_database()
    except Exception as e:
        pytest.fail(f"order_manager.initialize_database was not idempotent. Error: {e}")

    # Verify table exists by making a new connection (which mock_get_for_this_specific_test will provide)
    conn_verify = None
    try:
        conn_verify = mock_get_for_this_specific_test() # Get a connection using the mocked function
        conn_verify.row_factory = sqlite3.Row # Set for fetching
        cursor_verify = conn_verify.cursor()
        cursor_verify.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders';")
        table = cursor_verify.fetchone()
        assert table is not None, "The 'orders' table should exist after initialization."
        assert table['name'] == 'orders'
    finally:
        if conn_verify:
            conn_verify.close()
        # Clean up this specific test's DB
        conn_cleanup_init_test = sqlite3.connect(test_init_db_uri)
        conn_cleanup_init_test.execute("DROP TABLE IF EXISTS orders")
        conn_cleanup_init_test.commit()
        conn_cleanup_init_test.close()


def test_create_order_record(shared_db_setup): # Use the main fixture
    """Tests creating a new order record."""
    signal_data = {"instrument": "EUR_USD", "action": "buy", "quantity": 100}
    processed_params = {"instrument": "EUR_USD", "units": 100, "order_type": "MARKET"}
    
    # Action: This call will use the patched get_db_connection from shared_db_setup
    internal_id = order_manager.create_order_record(signal_data, processed_params)
    assert internal_id is not None

    # Verification: Use the manager's own getter, which also uses the patched connection
    record = order_manager.get_order_by_id(internal_id) 
    
    assert record is not None, "Order record should be found in the database."
    assert record["internal_order_id"] == internal_id
    assert record["status"] == "PENDING_SUBMISSION"
    assert record["signal_data"] == signal_data # Assumes _db_row_to_dict parses JSON correctly
    assert record["processed_params"] == processed_params
    now_iso_ish = datetime.now(timezone.utc).isoformat()[:16] 
    assert record["timestamp_created"][:16] == now_iso_ish
    assert record["timestamp_received"][:16] == now_iso_ish


def test_get_order_by_id_exists(shared_db_setup):
    """Tests retrieving an existing order by its ID."""
    signal_data = {"instrument": "USD_JPY", "action": "sell", "quantity": 200}
    processed_params = {"instrument": "USD_JPY", "units": -200, "order_type": "MARKET"}
    internal_id = order_manager.create_order_record(signal_data, processed_params)

    retrieved_order = order_manager.get_order_by_id(internal_id) # Uses patched connection
    
    assert retrieved_order is not None, "Failed to retrieve existing order."
    assert retrieved_order["internal_order_id"] == internal_id
    assert retrieved_order["signal_data"] == signal_data


def test_get_order_by_id_not_exists(shared_db_setup):
    """Tests retrieving a non-existent order."""
    retrieved_order = order_manager.get_order_by_id("non-existent-uuid")
    assert retrieved_order is None


def test_get_all_orders_empty(shared_db_setup):
    """Tests retrieving all orders when the database is empty."""
    all_orders = order_manager.get_all_orders()
    assert isinstance(all_orders, list)
    assert len(all_orders) == 0, f"Expected empty list, got {len(all_orders)} orders."


def test_get_all_orders_multiple(shared_db_setup):
    """Tests retrieving multiple orders."""
    id1 = order_manager.create_order_record({"instrument": "AUD_USD", "action": "buy", "quantity": 50}, 
                                          {"instrument": "AUD_USD", "units": 50, "type": "MARKET"})
    # Adding a slight delay to ensure timestamp differences if order matters, though UUIDs are unique.
    # For this test, order of insertion and retrieval (DESC by created_at) matters.
    # The manager's default sort order is by timestamp_created DESC.
    import time; time.sleep(0.01) 
    id2 = order_manager.create_order_record({"instrument": "GBP_USD", "action": "sell", "quantity": 70},
                                          {"instrument": "GBP_USD", "units": -70, "type": "MARKET"})
    
    all_orders = order_manager.get_all_orders()
    assert len(all_orders) == 2, f"Expected 2 orders, got {len(all_orders)}."
    # order_manager.get_all_orders sorts by timestamp_created DESC
    assert all_orders[0]["internal_order_id"] == id2 # GBP_USD was created last
    assert all_orders[0]["signal_data"]["instrument"] == "GBP_USD"
    assert all_orders[1]["internal_order_id"] == id1 # AUD_USD was created first
    assert all_orders[1]["signal_data"]["instrument"] == "AUD_USD"


def test_update_order_with_successful_fill(shared_db_setup):
    signal = {"instrument": "EUR_USD", "action": "buy", "quantity": 100}
    params = {"instrument": "EUR_USD", "units": 100, "order_type": "MARKET"}
    internal_id = order_manager.create_order_record(signal, params)

    mock_oanda_fill_response = {
        "orderFillTransaction": {
            "id": "1234", "orderID": "OANDA_ORDER_5678",
            "tradeOpened": {"tradeID": "TRADE_91011", "units": "100.00"}, 
            "price": "1.08500", "units": "100.00", "reason": "MARKET_ORDER"
        }, "relatedTransactionIDs": ["1234"]
    }
    
    updated_record_dict = order_manager.update_order_with_submission_response(
        internal_id, oanda_response=mock_oanda_fill_response
    )
    assert updated_record_dict is not None, "Update response should not be None on success."
    assert updated_record_dict["status"] == "FILLED"
    assert updated_record_dict["oanda_order_id"] == "OANDA_ORDER_5678"
    assert updated_record_dict["broker_response"] == mock_oanda_fill_response

def test_update_order_with_rejection(shared_db_setup):
    internal_id = order_manager.create_order_record(
        {"instrument": "XYZ", "action":"buy", "quantity":1}, 
        {"instrument": "XYZ", "units":1, "order_type":"MARKET"}
    )
    rejection_reason = "INSUFFICIENT_MARGIN"
    mock_oanda_rejection_response = {
        "orderRejectTransaction": {"rejectReason": rejection_reason, "id": "REJECT_ID_123"}
    }
    simulated_oanda_client_error = f"Oanda Order Reject Reason: {rejection_reason}"

    updated_record_dict = order_manager.update_order_with_submission_response(
        internal_id, 
        oanda_response=mock_oanda_rejection_response,
        oanda_error=simulated_oanda_client_error
    )
    assert updated_record_dict is not None, "Update response should not be None on rejection."
    assert updated_record_dict["status"] == "REJECTED_BY_BROKER"
    assert rejection_reason in updated_record_dict["error_message"]
    assert updated_record_dict["broker_response"] == mock_oanda_rejection_response

def test_update_order_non_existent_id(shared_db_setup, caplog):
    order_manager.update_order_with_submission_response("non-existent-uuid", oanda_error="Some error")
    assert "Could not find order with internal_order_id: non-existent-uuid to update in DB." in caplog.text