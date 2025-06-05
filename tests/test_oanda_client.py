# tests/test_oanda_client.py
import pytest
import os
import sys
import json
import requests # We'll be mocking methods from this library

# --- Add src directory to Python path for imports ---
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# --- End Path Adjustment ---

from broker_interface import oanda_client # Module to test
from config.loader import initialize_config, get as config_get

# --- Test Setup: Ensure config is initialized ---
# This ensures that oanda_client.API_KEY, oanda_client.ACCOUNT_ID, oanda_client.BASE_URL
# are populated from your config system when the oanda_client module is loaded by the tests.
# For these tests, we assume these config values are valid enough not to cause import-time errors.
# We will be mocking the actual HTTP requests, so valid *credentials* aren't strictly needed for mocks to work,
# but the variables need to be non-None for the client's internal checks.

@pytest.fixture(autouse=True) # Run automatically for every test in this file
def setup_config_for_oanda_client_tests(monkeypatch):
    """
    Ensures config is initialized and provides placeholder values for Oanda credentials
    if they are not set in the actual test environment's .env, to avoid ValueErrors
    from oanda_client's internal checks when we only intend to mock HTTP calls.
    """
    # Reset loader state in case other test files modified it globally
    from config import loader as config_loader_module
    config_loader_module._config = None
    config_loader_module._env_vars = {}

    # Temporarily set placeholder .env vars if not present,
    # because oanda_client checks for API_KEY etc. at module level or in functions.
    # The actual values don't matter as requests are mocked.
    monkeypatch.setenv("OANDA_API_KEY", "test_api_key_for_mocking")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "test_account_id_for_mocking")
    monkeypatch.setenv("OANDA_API_URL", "https://mocked-oanda-api.com") # Actual URL won't be hit

    initialize_config() # Load config.yaml and the (potentially monkeypatched) .env

    # Reload oanda_client module to make sure it picks up monkeypatched env vars via config
    # This is important if oanda_client.API_KEY etc. are set at module import time.
    import importlib
    importlib.reload(oanda_client)


# --- Test Cases ---

def test_check_oanda_connection_success(mocker):
    """Tests successful Oanda connection check."""
    # Mock the requests.get call
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "account": {"id": "test_account_id", "NAV": "10000.00"}
    }
    # Configure the mock to raise_for_status without error for 200
    mock_response.raise_for_status = mocker.Mock() 

    # Patch 'requests.get' within the 'broker_interface.oanda_client' module
    mocker.patch('broker_interface.oanda_client.requests.get', return_value=mock_response)

    result = oanda_client.check_oanda_connection()

    assert result is True
    oanda_client.requests.get.assert_called_once() # Verify it was called
    # We can also assert call arguments if needed:
    args, kwargs = oanda_client.requests.get.call_args
    expected_url_part = f"{oanda_client.BASE_URL}/v3/accounts/{oanda_client.ACCOUNT_ID}/summary"
    assert expected_url_part in args[0]


def test_check_oanda_connection_failure_http_error(mocker):
    """Tests Oanda connection check failing due to HTTP error."""
    mock_response = mocker.Mock()
    mock_response.status_code = 401 # Unauthorized
    mock_response.content = b'{"errorMessage": "Invalid token"}'
    # Configure raise_for_status to actually raise an HTTPError for non-2xx codes
    mock_response.raise_for_status = mocker.Mock(side_effect=requests.exceptions.HTTPError("401 Client Error"))

    mocker.patch('broker_interface.oanda_client.requests.get', return_value=mock_response)

    result = oanda_client.check_oanda_connection()
    assert result is False

def test_check_oanda_connection_failure_request_exception(mocker):
    """Tests Oanda connection check failing due to a requests.RequestException."""
    mocker.patch('broker_interface.oanda_client.requests.get', 
                 side_effect=requests.exceptions.ConnectionError("Failed to connect"))

    result = oanda_client.check_oanda_connection()
    assert result is False

def test_place_market_order_success_fill(mocker):
    """Tests successful market order placement with immediate fill."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200 # Or 201 Created, depending on API
    mock_fill_data = {
        "orderFillTransaction": {
            "id": "fill_tx_1", "orderID": "order_1", "tradeOpenedID": "trade_1",
            "price": "1.1000", "units": "100"
        }
    }
    mock_response.json.return_value = mock_fill_data
    mock_response.raise_for_status = mocker.Mock()

    mocker.patch('broker_interface.oanda_client.requests.post', return_value=mock_response)

    response_data, error = oanda_client.place_market_order("EUR_USD", 100)

    assert error is None
    assert response_data == mock_fill_data

    # Verify requests.post was called correctly
    oanda_client.requests.post.assert_called_once()
    args, kwargs = oanda_client.requests.post.call_args
    expected_url_part = f"{oanda_client.BASE_URL}/v3/accounts/{oanda_client.ACCOUNT_ID}/orders"
    assert expected_url_part in args[0]
    assert kwargs["json"]["order"]["instrument"] == "EUR_USD"
    assert kwargs["json"]["order"]["units"] == "100"
    assert kwargs["json"]["order"]["type"] == "MARKET"


def test_place_market_order_rejection(mocker):
    """Tests market order placement that gets rejected by Oanda."""
    mock_response = mocker.Mock()
    mock_response.status_code = 400 # Bad Request - typical for rejections
    rejection_data = {
        "orderRejectTransaction": {"rejectReason": "INSUFFICIENT_MARGIN", "id": "reject_tx_1"}
    }
    # Simulate Oanda's error response format in the content
    mock_response.content = json.dumps(rejection_data).encode('utf-8') 
    mock_response.json.return_value = rejection_data # If json() is called on error response

    # raise_for_status should raise an HTTPError
    http_error = requests.exceptions.HTTPError("400 Client Error")
    http_error.response = mock_response # Attach the mock response to the error
    mock_response.raise_for_status = mocker.Mock(side_effect=http_error)

    mocker.patch('broker_interface.oanda_client.requests.post', return_value=mock_response)

    response_data, error = oanda_client.place_market_order("USD_CAD", 500)

    assert response_data is None # Should be None on error as per current client logic
    assert error is not None
    assert "INSUFFICIENT_MARGIN" in error
    assert "Oanda Order Reject Reason" in error

def test_place_market_order_http_error_non_json_response(mocker):
    """Tests HTTP error with a non-JSON response from Oanda."""
    mock_response = mocker.Mock()
    mock_response.status_code = 500 # Server error
    mock_response.content = b"<html><body>Internal Server Error</body></html>"
    mock_response.text = "<html><body>Internal Server Error</body></html>" # For error message

    # Make response.json() raise an error if called
    mock_response.json = mocker.Mock(side_effect=json.JSONDecodeError("Msg", "Doc", 0))

    http_error = requests.exceptions.HTTPError("500 Server Error")
    http_error.response = mock_response
    mock_response.raise_for_status = mocker.Mock(side_effect=http_error)

    mocker.patch('broker_interface.oanda_client.requests.post', return_value=mock_response)

    response_data, error = oanda_client.place_market_order("GBP_JPY", 200)

    assert response_data is None
    assert error is not None
    assert "Oanda HTTP error (non-JSON response): 500" in error
    assert "Internal Server Error" in error # From response.text

def test_get_headers_missing_api_key(mocker, monkeypatch):
    """Tests _get_headers when API_KEY is missing."""
    # Temporarily remove the API_KEY after it was set by setup_config_for_oanda_client_tests
    # by effectively making config_get return None for it.
    # This requires deeper patching of config_get or oanda_client.API_KEY itself.

    # Easiest: directly patch oanda_client.API_KEY for this test
    monkeypatch.setattr(oanda_client, 'API_KEY', None)

    with pytest.raises(ValueError) as excinfo:
        oanda_client._get_headers() # _get_headers is a "private" helper
    assert "OANDA_API_KEY not configured" in str(excinfo.value)