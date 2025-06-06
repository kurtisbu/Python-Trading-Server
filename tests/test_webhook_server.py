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