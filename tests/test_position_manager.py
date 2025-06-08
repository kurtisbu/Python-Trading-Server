# tests/test_position_manager.py
import pytest
import sqlite3
import os
import sys

# --- Add src directory to Python path for imports ---
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# --- End Path Adjustment ---

from position_management import manager as position_manager

# Define a shared in-memory database URI for this test file
TEST_DB_URI = "file:test_pm_db?mode=memory&cache=shared"

@pytest.fixture(scope="function")
def db_with_filled_orders(monkeypatch):
    """
    Pytest fixture that:
    1. Patches the position_manager to use a shared in-memory DB.
    2. Creates the 'orders' table.
    3. Inserts a set of sample filled orders for testing calculations.
    4. Cleans up the table after the test.
    """
    def mock_get_connection():
        conn = sqlite3.connect(TEST_DB_URI)
        # --- THIS IS THE FIX ---
        # Ensure the test DB connection also returns dictionary-like rows
        conn.row_factory = sqlite3.Row
        # --- END OF FIX ---
        return conn

    monkeypatch.setattr(position_manager, '_get_db_connection', mock_get_connection)
    
    # Setup: create schema and insert test data
    conn = mock_get_connection()
    cursor = conn.cursor()
    # Create table
    cursor.execute("""
        CREATE TABLE orders (
            internal_order_id TEXT PRIMARY KEY, fill_quantity REAL,
            instrument TEXT, status TEXT, oanda_order_id TEXT, oanda_trade_id TEXT,
            timestamp_received TEXT, signal_data_json TEXT, processed_params_json TEXT,
            fill_price REAL, broker_response_json TEXT, error_message TEXT,
            timestamp_created TEXT, timestamp_updated TEXT
        )
    """)
    
    # Insert sample filled orders
    sample_orders = [
        ('eur_buy_1', 100.0, 'EUR_USD', 'FILLED'),
        ('eur_buy_2', 50.0, 'EUR_USD', 'FILLED'),
        ('eur_sell_1', -75.0, 'EUR_USD', 'FILLED'),
        ('jpy_sell_1', -500.0, 'USD_JPY', 'FILLED'),
        ('jpy_sell_2', -1000.0, 'USD_JPY', 'FILLED'),
        ('gbp_buy_1', 200.0, 'GBP_USD', 'FILLED'),
        ('gbp_close_1', -200.0, 'GBP_USD', 'FILLED'),
        ('aud_buy_1', 1000.0, 'AUD_USD', 'PENDING_FILL'),
    ]
    
    cursor.executemany(
        "INSERT INTO orders (internal_order_id, fill_quantity, instrument, status) VALUES (?, ?, ?, ?)",
        sample_orders
    )
    conn.commit()
    conn.close()

    yield # Run the test

    # Teardown: drop the table
    conn = mock_get_connection()
    conn.execute("DROP TABLE IF EXISTS orders")
    conn.commit()
    conn.close()

def test_get_position_long(db_with_filled_orders):
    """Tests calculating a net long position."""
    position = position_manager.get_position("EUR_USD")
    assert position == pytest.approx(75.0) # 100 + 50 - 75 = 75

def test_get_position_short(db_with_filled_orders):
    """Tests calculating a net short position."""
    position = position_manager.get_position("USD_JPY")
    assert position == pytest.approx(-1500.0) # -500 - 1000 = -1500

def test_get_position_flat(db_with_filled_orders):
    """Tests calculating a flat position."""
    position = position_manager.get_position("GBP_USD")
    assert position == pytest.approx(0.0) # 200 - 200 = 0

def test_get_position_no_filled_trades(db_with_filled_orders):
    """Tests an instrument with no FILLED trades (or no trades at all)."""
    position = position_manager.get_position("NZD_USD") # This instrument is not in our test data
    assert position == pytest.approx(0.0)

def test_get_all_positions(db_with_filled_orders):
    """Tests calculating all non-flat positions."""
    all_positions = position_manager.get_all_positions()

    expected_positions = {
        "EUR_USD": 75.0,
        "USD_JPY": -1500.0
    }

    assert isinstance(all_positions, dict)
    # Compare dictionaries, converting values to floats for reliable comparison
    assert {k: float(v) for k, v in all_positions.items()} == pytest.approx(expected_positions)
    # GBP_USD should not be in the result because its net position is 0
    assert "GBP_USD" not in all_positions
    # AUD_USD should not be in the result because its only order is not 'FILLED'
    assert "AUD_USD" not in all_positions