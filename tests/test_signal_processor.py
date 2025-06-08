# tests/test_signal_processor.py
import pytest # Import pytest if you need its specific features like fixtures, marks, etc.
               # For simple assert-based tests, it's not always strictly needed to import.
import os
import sys

# --- Add src directory to Python path for imports ---
# This allows tests/test_signal_processor.py to import from src/
# Adjust based on your project structure if pytest is run from project root
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# --- End Path Adjustment ---

from signal_processor.processor import process_signal
from config.loader import initialize_config, get as config_get # For config access

# --- Test Setup ---
# Ensure config is initialized before tests run that might rely on it.
# pytest fixtures are a more advanced way to handle setup like this (see later).
# For now, direct initialization works.
# Make sure your config.yaml and a dummy .env exist in PROJECT_ROOT_DIR if processor uses them
# The config.loader's __main__ block creates dummy files if they don't exist,
# which can be helpful if you also ran that.
# For robust tests, you might want specific test config files or mocks.

# Initialize config for testing - assumes config.yaml exists in project root
# You might want a separate test_config.yaml loaded via fixtures later for more complex scenarios.
initialize_config() 

# --- Test Cases ---

def test_process_signal_valid_buy():
    """Tests processing a valid buy signal."""
    signal = {"instrument": "EUR_USD", "action": "buy", "quantity": 100, "type": "market"}
    # Assuming EUR_USD is in allowed_instruments in your config.yaml
    # and 100 is a valid quantity based on your config.yaml min/max settings for EUR_USD.
    # Adjust the assertion based on how default quantities are handled if not provided.
    # The processor.py defaults to "MARKET" and converts quantity for "buy".

    expected_params = {"instrument": "EUR_USD", "units": 100, "order_type": "MARKET"}

    params, err = process_signal(signal)

    assert err is None, f"Expected no error, but got: {err}"
    assert params is not None, "Expected parameters, but got None"
    assert params["instrument"] == expected_params["instrument"]
    assert params["units"] == expected_params["units"]
    assert params["order_type"] == expected_params["order_type"]
    # A more concise way for dict comparison:
    assert params == expected_params

def test_process_signal_valid_sell_default_quantity():
    """Tests a valid sell signal using default quantity from config."""
    # This test assumes your config.yaml has:
    # trading:
    #   allowed_instruments:
    #     - USD_JPY
    #   defaults: (or instrument_settings for USD_JPY)
    #     quantity: 50 # or some other value

    signal = {"instrument": "USD_JPY", "action": "sell"} # Quantity not provided

    # Determine expected default quantity based on your config.yaml
    # Example: if USD_JPY specific default is 75, else global default is 50
    expected_instr_default_qty = config_get('trading.instrument_settings.USD_JPY.default_quantity')
    global_default_qty = config_get('trading.defaults.quantity', 1) # fallback default

    if expected_instr_default_qty is not None:
        expected_qty = expected_instr_default_qty
    else:
        expected_qty = global_default_qty

    expected_params = {"instrument": "USD_JPY", "units": -expected_qty, "order_type": "MARKET"}

    params, err = process_signal(signal)

    assert err is None, f"Expected no error, but got: {err}"
    assert params == expected_params, f"Processed params {params} did not match expected {expected_params}"

def test_process_signal_invalid_instrument():
    """Tests signal with an instrument not in allowed_instruments list."""
    signal = {"instrument": "NON_EXISTENT_INSTRUMENT", "action": "buy", "quantity": 100}
    # Ensure "NON_EXISTENT_INSTRUMENT" is NOT in your config.yaml's trading.allowed_instruments

    params, err = process_signal(signal)

    assert err is not None, "Expected an error for invalid instrument, but got None"
    assert params is None, "Expected no parameters for invalid instrument"
    assert "not in the allowed_instruments list" in err # Check for specific error message part

def test_process_signal_invalid_action():
    """Tests signal with an invalid action."""
    signal = {"instrument": "EUR_USD", "action": "hold_position", "quantity": 100}

    params, err = process_signal(signal)

    assert err is not None, "Expected an error for invalid action"
    assert params is None
    assert "Invalid action" in err

def test_process_signal_missing_required_field_instrument():
    """Tests signal missing the 'instrument' field."""
    signal = {"action": "buy", "quantity": 100}

    params, err = process_signal(signal)

    assert err is not None, "Expected an error for missing instrument field"
    assert params is None
    assert "Missing required signal field: instrument" in err # Adjusted based on typical error from processor

def test_process_signal_quantity_below_min():
    """Tests signal with quantity below configured minimum (if min_quantity is set)."""
    # Assumes config.yaml has:
    # trading:
    #   instrument_settings:
    #     EUR_USD:
    #       min_quantity: 10
    signal = {"instrument": "EUR_USD", "action": "buy", "quantity": 1}
    min_qty_eur_usd = config_get('trading.instrument_settings.EUR_USD.min_quantity')

    if min_qty_eur_usd is None: # Skip test if min_quantity isn't configured for this instrument
        pytest.skip("min_quantity not configured for EUR_USD in config.yaml, skipping test.")

    params, err = process_signal(signal)
    assert err is not None, f"Expected error for quantity below min, got None. Min Qty: {min_qty_eur_usd}"
    assert params is None
    assert f"below minimum allowed ({min_qty_eur_usd})" in err

def test_process_signal_quantity_above_max():
    """Tests signal with quantity above configured maximum (if max_quantity is set)."""
    # Assumes config.yaml has:
    # trading:
    #   instrument_settings:
    #     USD_JPY:
    #       max_quantity: 1000
    signal = {"instrument": "USD_JPY", "action": "sell", "quantity": 2000}
    max_qty_usd_jpy = config_get('trading.instrument_settings.USD_JPY.max_quantity')

    if max_qty_usd_jpy is None: # Skip test if max_quantity isn't configured
        pytest.skip("max_quantity not configured for USD_JPY in config.yaml, skipping test.")

    params, err = process_signal(signal)
    assert err is not None, f"Expected error for quantity above max, got None. Max Qty: {max_qty_usd_jpy}"
    assert params is None
    assert f"exceeds maximum allowed ({max_qty_usd_jpy})" in err

def test_process_signal_valid_limit_buy():
    """Tests processing a valid limit buy signal."""
    # This test assumes EUR_USD is an allowed instrument in your test config setup
    signal = {
        "instrument": "EUR_USD",
        "action": "buy",
        "quantity": 100,
        "type": "limit",
        "price": 1.0500
    }

    expected_params = {
        "instrument": "EUR_USD",
        "units": 100,
        "order_type": "LIMIT",
        "price": 1.0500
    }

    params, err = process_signal(signal)

    assert err is None, f"Expected no error, but got: {err}"
    assert params == expected_params

def test_process_signal_invalid_limit_order_missing_price():
    """Tests a limit order signal that is missing the price."""
    signal = {
        "instrument": "EUR_USD",
        "action": "buy",
        "quantity": 100,
        "type": "limit" # No 'price' field
    }

    params, err = process_signal(signal)

    assert params is None
    assert err is not None
    assert "Invalid or missing 'price' for LIMIT order" in err

def test_process_signal_valid_stop_buy():
    """Tests processing a valid stop buy signal."""
    # A buy stop order is placed above the current price to catch a breakout
    signal = {
        "instrument": "EUR_USD",
        "action": "buy",
        "quantity": 100,
        "type": "stop",
        "price": 1.0950
    }

    expected_params = {
        "instrument": "EUR_USD",
        "units": 100,
        "order_type": "STOP",
        "price": 1.0950
    }

    params, err = process_signal(signal)

    assert err is None, f"Expected no error, but got: {err}"
    assert params == expected_params

def test_process_signal_invalid_stop_order_missing_price():
    """Tests a stop order signal that is missing the price."""
    signal = {
        "instrument": "EUR_USD",
        "action": "buy",
        "quantity": 100,
        "type": "stop" # No 'price' field
    }

    params, err = process_signal(signal)

    assert params is None
    assert err is not None
    assert "Invalid or missing 'price' for STOP order" in err