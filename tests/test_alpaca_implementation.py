# tests/test_alpaca_implementation.py
import pytest
import os
import sys
import requests # For creating exceptions in tests

# --- Add src directory to Python path for imports ---
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# --- End Path Adjustment ---

from broker_interface.alpaca_implementation import AlpacaBroker

@pytest.fixture
def mock_alpaca_config(monkeypatch):
    """
    Fixture to provide a clean config environment for creating an AlpacaBroker instance.
    It mocks config_get to return dummy credentials.
    """
    def mock_config_get(key, default=None):
        if key == "ALPACA_API_KEY_ID": return "test_alpaca_api_key"
        if key == "ALPACA_API_SECRET_KEY": return "test_alpaca_secret_key"
        if key == "brokers.alpaca.base_url": return "https://mocked-alpaca-api.com"
        return default

    # We need to import the loader and patch its 'get' function
    from config import loader as config_loader_module
    monkeypatch.setattr(config_loader_module, 'get', mock_config_get)

    # We may need to reload the implementation to ensure it uses the patched config
    from broker_interface import alpaca_implementation
    import importlib
    importlib.reload(alpaca_implementation)


@pytest.fixture
def alpaca_broker(mock_alpaca_config):
    """Fixture to provide an instance of AlpacaBroker for testing."""
    # The mock_alpaca_config fixture runs first, setting up the environment.
    return AlpacaBroker()


# --- Test Cases ---

def test_init_success(alpaca_broker):
    """Tests that the AlpacaBroker initializes correctly with valid config."""
    assert alpaca_broker.api_key_id == "test_alpaca_api_key"
    assert alpaca_broker.secret_key == "test_alpaca_secret_key"
    assert alpaca_broker.base_url == "https://mocked-alpaca-api.com"
    assert "APCA-API-KEY-ID" in alpaca_broker.headers
    assert "APCA-API-SECRET-KEY" in alpaca_broker.headers

def test_init_missing_config(monkeypatch): #<-- Removed 'mock_alpaca_config' fixture
    """Tests that the AlpacaBroker raises an error if config is missing."""
    # 1. Define the "bad" config function for this specific test
    def mock_missing_key(key, default=None):
        if key == "ALPACA_API_KEY_ID": return "test_key"
        if key == "ALPACA_API_SECRET_KEY": return None # Simulate missing secret key
        if key == "brokers.alpaca.base_url": return "https://mocked-alpaca-api.com"
        return default

    # 2. Patch the config loader with our "bad" function
    from config import loader as config_loader_module
    monkeypatch.setattr(config_loader_module, 'get', mock_missing_key)

    # 3. IMPORTANT: Now reload the module so it imports the "bad" config
    from broker_interface import alpaca_implementation
    import importlib
    importlib.reload(alpaca_implementation)

    # We need to re-import the class from the reloaded module
    from broker_interface.alpaca_implementation import AlpacaBroker

    # 4. Now, creating an instance should fail as expected
    with pytest.raises(ValueError) as excinfo:
        AlpacaBroker()
    assert "Alpaca API credentials or URL not fully configured" in str(excinfo.value)


def test_get_account_summary_success(mocker, alpaca_broker):
    """Tests a successful call to get_account_summary."""
    # Arrange: Mock the requests.get call
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_account_data = {
        "id": "some_uuid_for_account",
        "account_number": "PA...",
        "status": "ACTIVE",
        "buying_power": "200000",
        "equity": "100000"
    }
    mock_response.json.return_value = mock_account_data
    mock_response.raise_for_status = mocker.Mock()

    # Patch the 'get' method of the requests library used by the implementation
    mock_get_call = mocker.patch('broker_interface.alpaca_implementation.requests.get', return_value=mock_response)

    # Act
    summary, error = alpaca_broker.get_account_summary()

    # Assert
    assert error is None
    assert summary["status"] == "ACTIVE"
    assert summary["buying_power"] == "200000"

    # Verify the API call was made correctly
    expected_url = f"{alpaca_broker.base_url}/v2/account"
    mock_get_call.assert_called_once_with(expected_url, headers=alpaca_broker.headers, timeout=10)

    # In tests/test_alpaca_implementation.py

def test_place_market_order_simple_success(mocker, alpaca_broker):
    """Tests placing a simple market order (buy) without SL/TP."""
    # Arrange
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_order_confirmation = {
        "id": "a_mock_order_uuid",
        "client_order_id": "another_mock_uuid",
        "status": "accepted",
        "symbol": "AAPL",
        "qty": "10",
        "side": "buy",
        "type": "market"
    }
    mock_response.json.return_value = mock_order_confirmation
    mock_response.raise_for_status = mocker.Mock()

    mock_post_call = mocker.patch('broker_interface.alpaca_implementation.requests.post', return_value=mock_response)

    # Act
    response_data, error = alpaca_broker.place_market_order(instrument="AAPL", units=10)

    # Assert
    assert error is None
    assert response_data["status"] == "accepted"
    assert response_data["symbol"] == "AAPL"

    # Verify the payload sent to the API was correct
    mock_post_call.assert_called_once()
    args, kwargs = mock_post_call.call_args
    sent_payload = kwargs["json"]

    assert sent_payload["symbol"] == "AAPL"
    assert sent_payload["qty"] == 10
    assert sent_payload["side"] == "buy"
    assert sent_payload["type"] == "market"
    # For a simple order, 'order_class' should not be present
    assert "order_class" not in sent_payload


def test_place_market_order_with_sl_tp_success(mocker, alpaca_broker):
    """Tests placing a market order with Stop Loss and Take Profit (a bracket order)."""
    # Arrange
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_order_confirmation = {"id": "a_mock_bracket_order_uuid", "status": "accepted"}
    mock_response.json.return_value = mock_order_confirmation
    mock_response.raise_for_status = mocker.Mock()

    mock_post_call = mocker.patch('broker_interface.alpaca_implementation.requests.post', return_value=mock_response)

    # Act
    instrument = "TSLA"
    units = -5 # A short sell
    stop_loss_price = 310.0
    take_profit_price = 290.0
    response_data, error = alpaca_broker.place_market_order(
        instrument=instrument,
        units=units,
        stop_loss=stop_loss_price,
        take_profit=take_profit_price
    )

    # Assert
    assert error is None
    assert response_data["status"] == "accepted"

    # Verify the payload sent to the API was a correctly formatted bracket order
    mock_post_call.assert_called_once()
    args, kwargs = mock_post_call.call_args
    sent_payload = kwargs["json"]

    assert sent_payload["symbol"] == instrument
    assert sent_payload["qty"] == abs(units)
    assert sent_payload["side"] == "sell"
    assert sent_payload["type"] == "market"
    assert sent_payload["order_class"] == "bracket" # Must be a bracket order
    assert "stop_loss" in sent_payload
    assert sent_payload["stop_loss"]["stop_price"] == stop_loss_price
    assert "take_profit" in sent_payload
    assert sent_payload["take_profit"]["limit_price"] == take_profit_price


def test_place_limit_order_success(mocker, alpaca_broker):
    """Tests placing a simple limit order."""
    # Arrange
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_order_confirmation = {"id": "a_mock_limit_order_uuid", "status": "accepted"}
    mock_response.json.return_value = mock_order_confirmation
    mock_response.raise_for_status = mocker.Mock()

    mock_post_call = mocker.patch('broker_interface.alpaca_implementation.requests.post', return_value=mock_response)

    # Act
    instrument = "GOOGL"
    units = 10
    price = 175.50
    response_data, error = alpaca_broker.place_limit_order(instrument, units, price)

    # Assert
    assert error is None
    assert response_data["status"] == "accepted"

    # Verify the payload sent to the API was correct
    mock_post_call.assert_called_once()
    args, kwargs = mock_post_call.call_args
    sent_payload = kwargs["json"]

    assert sent_payload["symbol"] == instrument
    assert sent_payload["qty"] == units
    assert sent_payload["side"] == "buy"
    assert sent_payload["type"] == "limit"
    assert sent_payload["limit_price"] == price
    assert "order_class" not in sent_payload # Not a bracket order in this simple case


# In tests/test_alpaca_implementation.py

def test_place_stop_order_success(mocker, alpaca_broker):
    """Tests placing a simple stop order."""
    # Arrange
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_order_confirmation = {"id": "a_mock_stop_order_uuid", "status": "accepted"}
    mock_response.json.return_value = mock_order_confirmation
    mock_response.raise_for_status = mocker.Mock()

    mock_post_call = mocker.patch('broker_interface.alpaca_implementation.requests.post', return_value=mock_response)

    # Act
    instrument = "MSFT"
    units = 15
    price = 455.0 # Buy if price breaks out to 455
    response_data, error = alpaca_broker.place_stop_order(instrument, units, price)

    # Assert
    assert error is None
    assert response_data["status"] == "accepted"

    # Verify the payload sent to the API was correct
    mock_post_call.assert_called_once()
    args, kwargs = mock_post_call.call_args
    sent_payload = kwargs["json"]

    assert sent_payload["symbol"] == instrument
    assert sent_payload["qty"] == units
    assert sent_payload["side"] == "buy"
    assert sent_payload["type"] == "stop"
    assert sent_payload["stop_price"] == price


def test_cancel_order_success(mocker, alpaca_broker):
    """Tests successful order cancellation with Alpaca."""
    # Arrange
    order_to_cancel = "a_pending_alpaca_order_id"

    # A successful DELETE to Alpaca returns status 204 and no body.
    mock_response = mocker.Mock()
    mock_response.status_code = 204
    mock_response.raise_for_status = mocker.Mock()

    # Patch the requests.delete method
    mock_delete_call = mocker.patch('broker_interface.alpaca_implementation.requests.delete', return_value=mock_response)

    # Act
    response_data, error = alpaca_broker.cancel_order(order_to_cancel)

    # Assert
    assert error is None
    assert response_data["status"] == "cancellation_requested"

    # Verify that requests.delete was called correctly
    mock_delete_call.assert_called_once()
    args, kwargs = mock_delete_call.call_args
    expected_url = f"{alpaca_broker.base_url}/v2/orders/{order_to_cancel}"
    assert args[0] == expected_url