# tests/test_oanda_implementation.py
import pytest
import os
import sys
import json
import requests

# --- Add src directory to Python path for imports ---
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# --- End Path Adjustment ---

from broker_interface.oanda_implementation import OandaBroker
# --- FIX #2: Import config_get for use in tests ---
from config.loader import get as config_get

@pytest.fixture
def mock_config(monkeypatch):
    """Fixture to provide a clean config environment for creating an OandaBroker instance."""
    def mock_config_get(key, default=None):
        if key == "OANDA_API_KEY": return "test_api_key"
        if key == "OANDA_ACCOUNT_ID": return "test_account_id"
        if key == "oanda.base_url": return "https://mocked-oanda-api.com"
        if key == "OANDA_API_URL": return "https://mocked-oanda-api.com"
        # For the limit order test assertion
        if key == "trading.defaults.time_in_force": return "GTC"
        return default
    
    from config import loader as config_loader_module
    import importlib
    monkeypatch.setattr(config_loader_module, 'get', mock_config_get)
    
    from broker_interface import oanda_implementation
    importlib.reload(oanda_implementation)


@pytest.fixture
def oanda_broker(mock_config):
    """Fixture to provide an instance of OandaBroker for testing."""
    return OandaBroker()


def test_get_account_summary_success(mocker, oanda_broker):
    """Tests successful get_account_summary."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "account": {"id": "test_account_id", "NAV": "10000.00"}
    }
    mock_response.raise_for_status = mocker.Mock()
    
    mocker.patch('broker_interface.oanda_implementation.requests.get', return_value=mock_response)
    
    summary, error = oanda_broker.get_account_summary()
    
    assert error is None
    assert summary['id'] == "test_account_id"


def test_place_market_order_success(mocker, oanda_broker):
    """Tests successful market order placement."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_fill_data = {"orderFillTransaction": {"id": "fill_tx_1"}}
    mock_response.json.return_value = mock_fill_data
    mock_response.raise_for_status = mocker.Mock()
    
    mocker.patch('broker_interface.oanda_implementation.requests.post', return_value=mock_response)
    
    response_data, error = oanda_broker.place_market_order("EUR_USD", 100)
    
    assert error is None
    assert response_data == mock_fill_data


def test_place_market_order_rejection(mocker, oanda_broker):
    """Tests handling of a rejected order."""
    mock_response = mocker.Mock()
    mock_response.status_code = 400
    rejection_data = {"orderRejectTransaction": {"rejectReason": "INSUFFICIENT_MARGIN"}}
    mock_response.json.return_value = rejection_data
    mock_response.content = json.dumps(rejection_data).encode('utf-8')
    
    http_error = requests.exceptions.HTTPError("400 Client Error")
    http_error.response = mock_response
    mock_response.raise_for_status = mocker.Mock(side_effect=http_error)
    
    mocker.patch('broker_interface.oanda_implementation.requests.post', return_value=mock_response)
    
    response_data, error = oanda_broker.place_market_order("USD_CAD", 500)
    
    assert response_data is None
    assert "INSUFFICIENT_MARGIN" in error


def test_place_limit_order_success(mocker, oanda_broker):
    """Tests successful limit order placement."""
    mock_response = mocker.Mock()
    mock_response.status_code = 201
    mock_create_data = {
        "orderCreateTransaction": {"id": "limit_order_123", "reason": "CLIENT_REQUEST"}
    }
    mock_response.json.return_value = mock_create_data
    mock_response.raise_for_status = mocker.Mock()
    
    mocker.patch('broker_interface.oanda_implementation.requests.post', return_value=mock_response)
    
    instrument = "GBP_USD"
    units = -50
    price = 1.2500
    response_data, error = oanda_broker.place_limit_order(instrument, units, price)
    
    assert error is None
    assert response_data == mock_create_data
    
    from broker_interface.oanda_implementation import requests
    requests.post.assert_called_once()
    args, kwargs = requests.post.call_args
    
    sent_payload = kwargs["json"]["order"]
    assert sent_payload["instrument"] == instrument
    assert sent_payload["units"] == str(units)
    assert sent_payload["type"] == "LIMIT"
    assert sent_payload["price"] == str(price)
    # The config_get call here now works because of the import
    assert sent_payload["timeInForce"] == config_get('trading.defaults.time_in_force', 'GTC')


def test_unimplemented_methods(oanda_broker):
    """Tests that remaining future methods still raise NotImplementedError."""
    # --- FIX #1: Removed the check for place_limit_order ---
    with pytest.raises(NotImplementedError):
        oanda_broker.cancel_order("some_order_id")

    with pytest.raises(NotImplementedError):
        oanda_broker.get_order_status("some_order_id")