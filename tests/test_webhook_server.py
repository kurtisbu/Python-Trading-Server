# tests/test_webhook_server.py
import pytest
import json
import os
import sys

# --- Add src directory to Python path for imports ---
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT_DIR not in sys.path: # For config loader to find root
    sys.path.insert(0, PROJECT_ROOT_DIR)
# --- End Path Adjustment ---

# Import the Flask app instance from your server.py
# We need to ensure config is initialized before server.py is fully imported if it relies on it at module level.
# The config.loader.initialize_config() is called at the module level in server.py,
# so just importing should be fine if config.yaml and .env are findable.

# For testing, it's often better to have a create_app() function in server.py
# so we can create a fresh app instance for tests with specific test configurations.
# However, for now, we'll try to import the existing app.
# We might need to monkeypatch config values before importing the app for full isolation.

# Let's create a fixture that sets up the app with a test configuration.
# In tests/test_webhook_server.py

# In tests/test_webhook_server.py

# In tests/test_webhook_server.py

@pytest.fixture
def app(monkeypatch, mocker):
    """
    Creates the Flask app for testing and injects a mock broker.
    """
    # 1. Import the server module. This is now safe.
    from webhook_server import server

    # 2. Create the mock broker object.
    mock_broker = mocker.Mock()
    # Configure its methods with default successful return values
    mock_broker.place_market_order.return_value = ({"status": "mock_market_ok"}, None)
    mock_broker.place_limit_order.return_value = ({"status": "mock_limit_ok"}, None)

    # 3. Use monkeypatch to set the global 'broker' variable in the server module.
    monkeypatch.setattr(server, 'broker', mock_broker)
    
    # 4. Also patch the shared secret for authentication tests
    monkeypatch.setattr(server, 'WEBHOOK_SHARED_SECRET', 'testsecret123')

    # 5. Configure app for testing and yield.
    server.app.config.update({"TESTING": True})
    yield server.app

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

# --- Test Cases ---

# def test_health_check(client):
#     """Test the /health endpoint."""
#     response = client.get('/health')
#     assert response.status_code == 200
#     json_data = response.get_json()
#     assert json_data["status"] == "ok"
#     assert json_data["message"] == "Webhook server is running."

# # (Continuing tests/test_webhook_server.py)

#     # Test data
#     VALID_SIGNAL_PAYLOAD = {
#         "instrument": "EUR_USD",
#         "action": "buy",
#         "quantity": 100,
#         "webhook_secret": "testsecret123" # Matches what we set via monkeypatch for the app fixture
#     }

#     PROCESSED_TRADE_PARAMS = {
#         "instrument": "EUR_USD",
#         "units": 100,
#         "order_type": "MARKET"
#     }
    
#     MOCK_OANDA_RESPONSE_SUCCESS = {
#         "orderFillTransaction": {"id": "mock_fill_id"}
#     }

#     INTERNAL_ORDER_ID = "test-internal-order-uuid-123"


#     def test_webhook_limit_order_success(client, mocker):
#         """Test successful webhook call for a LIMIT order."""
#         # 1. Arrange
#         limit_signal_payload = {
#             "instrument": "GBP_USD", "action": "sell", "quantity": 50,
#             "type": "limit", "price": 1.2700, "webhook_secret": "testsecret123"
#         }
#         limit_trade_params = {
#             "instrument": "GBP_USD", "units": -50,
#             "order_type": "LIMIT", "price": 1.2700
#         }
        
#         # Mock the functions that are NOT part of the broker object
#         mocker.patch('webhook_server.server.process_signal', return_value=(limit_trade_params, None))
#         mocker.patch('webhook_server.server.create_order_record', return_value="test-limit-order-uuid-456")
#         mocker.patch('webhook_server.server.update_order_with_submission_response')

#         # Get a reference to the mock broker object that was injected by the app fixture
#         from webhook_server.server import broker as mock_broker_in_server
        
#         # 2. Act
#         response = client.post('/webhook', json=limit_signal_payload)
        
#         # 3. Assert
#         assert response.status_code == 200
        
#         # Assert that the correct broker method was called on our mock object
#         mock_broker_in_server.place_market_order.assert_called_once_with(
#             instrument="GBP_USD", units=-50, price=1.2700
#         )
#         mock_broker_in_server.place_limit_order.assert_not_called()

    def test_webhook_invalid_secret(client, mocker):
        """Test webhook call with an invalid secret."""
        # No need to mock downstream if secret check fails first
        payload_with_wrong_secret = {**VALID_SIGNAL_PAYLOAD, "webhook_secret": "wrongsecret"}
        
        response = client.post('/webhook', json=payload_with_wrong_secret)
        
        assert response.status_code == 403 # Forbidden
        json_data = response.get_json()
        assert json_data["status"] == "error"
        assert "Invalid webhook secret" in json_data["message"]

    def test_webhook_missing_secret_in_payload(client, mocker):
        """Test webhook call with missing secret in payload when server expects one."""
        payload_missing_secret = {"instrument": "EUR_USD", "action": "buy", "quantity": 50}
        
        response = client.post('/webhook', json=payload_missing_secret)
        
        assert response.status_code == 403 # Forbidden (or 401 if you prefer for missing auth element)
        json_data = response.get_json()
        assert "Invalid webhook secret" in json_data["message"] # Current logic bundles missing/invalid

    def test_webhook_not_json(client, mocker):
        """Test webhook call with non-JSON payload."""
        response = client.post('/webhook', data="this is not json", content_type="text/plain")
        assert response.status_code == 400 # Bad Request
        json_data = response.get_json()
        assert "Request was not JSON" in json_data["message"]

    def test_webhook_signal_processor_error(client, mocker):
        """Test webhook when process_signal returns an error."""
        error_message = "Invalid instrument in signal"
        mocker.patch('webhook_server.server.process_signal', return_value=(None, error_message))
        # Mock other downstream calls so they are not made if process_signal fails
        mocker.patch('webhook_server.server.create_order_record')
        mocker.patch('webhook_server.server.place_market_order')
        
        response = client.post('/webhook', json=VALID_SIGNAL_PAYLOAD)
        
        assert response.status_code == 400
        json_data = response.get_json()
        assert json_data["status"] == "error"
        assert error_message in json_data["message"]
        from webhook_server import server
        server.create_order_record.assert_not_called() # Ensure it wasn't called
        server.place_market_order.assert_not_called()

    def test_webhook_oanda_placement_error(client, mocker):
        """Test webhook when place_market_order returns an error."""
        oanda_error_msg = "Oanda unavailable"
        mocker.patch('webhook_server.server.process_signal', return_value=(PROCESSED_TRADE_PARAMS, None))
        mocker.patch('webhook_server.server.create_order_record', return_value=INTERNAL_ORDER_ID)
        mock_place_order = mocker.patch(
        'broker_interface.oanda_implementation.OandaBroker.place_market_order',
        return_value=(MOCK_OANDA_RESPONSE_SUCCESS, None)
        )
        mocker.patch('webhook_server.server.update_order_with_submission_response')

        response = client.post('/webhook', json=VALID_SIGNAL_PAYLOAD)
        
        assert response.status_code == 500 # Or whatever status code your handler returns for this
        json_data = response.get_json()
        assert json_data["status"] == "error"
        assert oanda_error_msg in json_data["oanda_error"]
        assert json_data["internal_order_id"] == INTERNAL_ORDER_ID
        from webhook_server import server
        server.update_order_with_submission_response.assert_called_once_with(
            INTERNAL_ORDER_ID, None, oanda_error_msg
        )
        # (Continuing tests/test_webhook_server.py)

    def test_list_orders_success(client, mocker):
        """Test GET /orders successfully."""
        mock_orders_data = [
            {"internal_order_id": "uuid1", "status": "FILLED"},
            {"internal_order_id": "uuid2", "status": "PENDING_SUBMISSION"}
        ]
        mocker.patch('webhook_server.server.get_all_orders', return_value=mock_orders_data)
        
        response = client.get('/orders')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data["status"] == "success"
        assert json_data["orders"] == mock_orders_data
        from webhook_server import server
        server.get_all_orders.assert_called_once()

    def test_get_specific_order_success(client, mocker):
        """Test GET /orders/<id> for an existing order."""
        order_id = "existing_uuid"
        mock_order_data = {"internal_order_id": order_id, "status": "FILLED", "instrument": "EUR_USD"}
        mocker.patch('webhook_server.server.get_order_by_id', return_value=mock_order_data)
        
        response = client.get(f'/orders/{order_id}')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data["status"] == "success"
        assert json_data["order"] == mock_order_data
        from webhook_server import server
        server.get_order_by_id.assert_called_once_with(order_id)

    def test_get_specific_order_not_found(client, mocker):
        """Test GET /orders/<id> for a non-existent order."""
        order_id = "non_existent_uuid"
        mocker.patch('webhook_server.server.get_order_by_id', return_value=None) # Simulate not found
        
        response = client.get(f'/orders/{order_id}')
        assert response.status_code == 404
        json_data = response.get_json()
        assert json_data["status"] == "error"
        assert "Order not found" in json_data["message"]
        from webhook_server import server
        server.get_order_by_id.assert_called_once_with(order_id)

    def test_webhook_limit_order_success(client, mocker):
        """Test successful webhook call for a LIMIT order."""
        # 1. Arrange
        limit_signal_payload = {
            "instrument": "GBP_USD", "action": "sell", "quantity": 50,
            "type": "limit", "price": 1.2700, "webhook_secret": "testsecret123"
        }
        limit_trade_params = {
            "instrument": "GBP_USD", "units": -50,
            "order_type": "LIMIT", "price": 1.2700
        }
        
        # Mock the functions that are NOT part of the broker object
        mocker.patch('webhook_server.server.process_signal', return_value=(limit_trade_params, None))
        mocker.patch('webhook_server.server.create_order_record', return_value="test-limit-order-uuid-456")
        mocker.patch('webhook_server.server.update_order_with_submission_response')

        # Get a reference to the mock broker object that was injected by the app fixture
        from webhook_server.server import broker as mock_broker_in_server
        
        # 2. Act
        response = client.post('/webhook', json=limit_signal_payload)
        
        # 3. Assert
        assert response.status_code == 200
        
        # Assert that the correct broker method was called on our mock object
        mock_broker_in_server.place_limit_order.assert_called_once_with(
            instrument="GBP_USD", units=-50, price=1.2700
        )
        mock_broker_in_server.place_market_order.assert_not_called()

# In tests/test_webhook_server.py

def test_webhook_stop_order_success(client, mocker):
    """Test successful webhook call for a STOP order without SL/TP."""
    # 1. Arrange
    stop_signal_payload = {
        "instrument": "USD_JPY", "action": "buy", "quantity": 200,
        "type": "stop", "price": 158.00, "webhook_secret": "testsecret123"
    }
    # The processed params do not have SL/TP for this test case
    stop_trade_params = {
        "instrument": "USD_JPY", "units": 200,
        "order_type": "STOP", "price": 158.00
    }
    mock_broker_response = {"orderCreateTransaction": {"id": "mock_stop_order_id"}}

    # Mock downstream services
    mocker.patch('webhook_server.server.process_signal', return_value=(stop_trade_params, None))
    mocker.patch('webhook_server.server.create_order_record', return_value="test-stop-order-uuid-789")
    mocker.patch('webhook_server.server.update_order_with_submission_response')

    from webhook_server.server import broker as mock_broker_in_server
    mock_broker_in_server.place_stop_order.return_value = (mock_broker_response, None)

    # 2. Act
    response = client.post('/webhook', json=stop_signal_payload)

    # 3. Assert
    assert response.status_code == 200

    # --- THIS IS THE FIX ---
    # The assertion now includes the optional stop_loss and take_profit arguments,
    # which will be None in this test case.
    mock_broker_in_server.place_stop_order.assert_called_once_with(
        instrument="USD_JPY",
        units=200,
        price=158.00,
        stop_loss=None,
        take_profit=None
    )
    # --- END OF FIX ---

    mock_broker_in_server.place_market_order.assert_not_called()
    mock_broker_in_server.place_limit_order.assert_not_called()

# In tests/test_webhook_server.py

def test_cancel_order_endpoint_success(client, mocker):
    """Tests successfully cancelling an order via the API endpoint."""
    # Arrange
    internal_id = "test-uuid-to-cancel"
    oanda_order_id = "12345"

    # 1. Mock the order record fetched from our DB
    mock_order_from_db = {
        "internal_order_id": internal_id,
        "oanda_order_id": oanda_order_id,
        "status": "ORDER_ACCEPTED" # A cancelable status
    }
    mocker.patch('webhook_server.server.get_order_by_id', return_value=mock_order_from_db)

    # 2. Mock the successful response from the broker's cancel_order method
    mock_cancellation_response = {"orderCancelTransaction": {"orderID": oanda_order_id, "reason": "CLIENT_REQUEST"}}
    # Get a handle to the injected mock broker and configure its return value
    from webhook_server.server import broker as mock_broker_in_server
    mock_broker_in_server.cancel_order.return_value = (mock_cancellation_response, None)

    # 3. Mock the DB update function
    mock_update_call = mocker.patch('webhook_server.server.update_order_with_submission_response')

    # Act
    response = client.post(f'/orders/{internal_id}/cancel')

    # Assert
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "success"
    assert json_data["broker_response"] == mock_cancellation_response

    # Verify the correct functions were called
    mock_broker_in_server.cancel_order.assert_called_once_with(oanda_order_id)
    mock_update_call.assert_called_once_with(internal_id, mock_cancellation_response, None)


def test_cancel_order_endpoint_not_cancelable_status(client, mocker):
    """Tests trying to cancel an order that is already filled."""
    # Arrange
    internal_id = "test-uuid-filled"
    mock_order_from_db = {
        "internal_order_id": internal_id,
        "oanda_order_id": "56789",
        "status": "FILLED" # NOT a cancelable status
    }
    mocker.patch('webhook_server.server.get_order_by_id', return_value=mock_order_from_db)

    # Act
    response = client.post(f'/orders/{internal_id}/cancel')

    # Assert
    assert response.status_code == 400 # Bad Request
    json_data = response.get_json()
    assert "not in a cancelable state" in json_data["message"]


def test_cancel_order_endpoint_not_found(client, mocker):
    """Tests trying to cancel an order that doesn't exist in our DB."""
    # Arrange
    mocker.patch('webhook_server.server.get_order_by_id', return_value=None)

    # Act
    response = client.post('/orders/non-existent-id/cancel')

    # Assert
    assert response.status_code == 404 # Not Found
    json_data = response.get_json()
    assert "Order not found" in json_data["message"]


def test_get_all_positions_endpoint(client, mocker):
    """Tests the GET /positions endpoint."""
    # Arrange: Mock the backend function
    mock_positions_data = {
        "EUR_USD": 150.5,
        "USD_JPY": -1000.0
    }
    mocker.patch('webhook_server.server.get_all_positions', return_value=mock_positions_data)

    # Act
    response = client.get('/positions')

    # Assert
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "success"
    assert json_data["positions"] == mock_positions_data

    # Verify the mocked function was called
    from webhook_server.server import get_all_positions
    get_all_positions.assert_called_once()


def test_get_instrument_position_endpoint(client, mocker):
    """Tests the GET /positions/<instrument> endpoint for a specific instrument."""
    # Arrange
    instrument = "EUR_USD"
    mock_position = 150.5
    mock_get_pos = mocker.patch('webhook_server.server.get_position', return_value=mock_position)

    # Act
    response = client.get(f'/positions/{instrument}')

    # Assert
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "success"
    assert json_data["instrument"] == instrument
    assert json_data["net_position"] == mock_position

    # Verify the mocked function was called with the correct argument
    mock_get_pos.assert_called_once_with(instrument)

def test_webhook_market_order_with_sl_tp_success(client, mocker):
    """Test a successful webhook call for a market order that includes SL and TP."""
    # Arrange
    # 1. Define the incoming signal with SL/TP
    signal_with_sl_tp = {
        "instrument": "EUR_USD", "action": "buy", "quantity": 100,
        "type": "market", "webhook_secret": "testsecret123",
        "stop_loss": 1.0700, "take_profit": 1.0900
    }

    # 2. Define what the signal processor will return
    processed_params_with_sl_tp = {
        "instrument": "EUR_USD", "units": 100, "order_type": "MARKET",
        "stop_loss": 1.0700, "take_profit": 1.0900
    }

    # 3. Mock the downstream services
    mocker.patch('webhook_server.server.process_signal', return_value=(processed_params_with_sl_tp, None))
    mocker.patch('webhook_server.server.create_order_record', return_value="test-sl-tp-uuid")
    mocker.patch('webhook_server.server.update_order_with_submission_response')

    # 4. Get a handle on the injected mock broker
    from webhook_server.server import broker as mock_broker_in_server
    # Configure its return value for this specific test
    mock_broker_in_server.place_market_order.return_value = ({"status": "ok_with_sl_tp"}, None)

    # Act
    response = client.post('/webhook', json=signal_with_sl_tp)

    # Assert
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

    # Assert that the broker method was called with the correct SL/TP parameters
    mock_broker_in_server.place_market_order.assert_called_once_with(
        instrument="EUR_USD",
        units=100,
        stop_loss=1.0700,
        take_profit=1.0900
    )