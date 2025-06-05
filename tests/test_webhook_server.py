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
@pytest.fixture(scope="function") # Or simply @pytest.fixture, as "function" is the default
def app(monkeypatch):
    """
    Create and configure a new app instance for each test module.
    Ensures that config (especially secrets for webhook) is loaded appropriately for tests.
    """
    # Monkeypatch any critical .env vars needed by the app at import time,
    # if they aren't reliably picked up from a test .env by the global initialize_config()
    # For WEBHOOK_SHARED_SECRET, it's read by server.py at module level via config_get.
    # So, we need to ensure config.loader's _env_vars has it.

    # Ensure config loader is reset and initialized with test-friendly values for secrets
    from config import loader as config_loader_module
    config_loader_module._config = None # Reset config
    config_loader_module._env_vars = {} # Reset env vars cache in loader

    # Simulate essential .env variables for the app to load via config_get
    monkeypatch.setenv("WEBHOOK_SHARED_SECRET", "testsecret123")
    monkeypatch.setenv("OANDA_API_KEY", "test_api_key") # Needed by oanda_client via config
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "test_account_id") # Needed by oanda_client via config
    monkeypatch.setenv("OANDA_API_URL", "https://api-fxpractice.oanda.com") # Needed by oanda_client

    # Initialize our main config system (it will pick up monkeypatched .env vars)
    config_loader_module.initialize_config()

    # Now import the app from webhook_server. This should use the config we just set up.
    # We might need to reload it if it was imported by other test modules already with different config.
    from webhook_server import server # server.py
    import importlib
    importlib.reload(server) # Reload to ensure it picks up config possibly changed by monkeypatch

    # Configure the app for testing
    server.app.config.update({
        "TESTING": True,
        # Add other test-specific configurations if needed
        # e.g., WTF_CSRF_ENABLED = False if using Flask-WTF forms
    })

    # Here, other services like the database should be set up for testing if not handled by autouse fixtures
    # order_manager.initialize_database() (if it uses a test DB URI from config)

    yield server.app # provide the app instance

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

# --- Test Cases ---

def test_health_check(client):
    """Test the /health endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "ok"
    assert json_data["message"] == "Webhook server is running."

# (Continuing tests/test_webhook_server.py)

    # Test data
    VALID_SIGNAL_PAYLOAD = {
        "instrument": "EUR_USD",
        "action": "buy",
        "quantity": 100,
        "webhook_secret": "testsecret123" # Matches what we set via monkeypatch for the app fixture
    }

    PROCESSED_TRADE_PARAMS = {
        "instrument": "EUR_USD",
        "units": 100,
        "order_type": "MARKET"
    }
    
    MOCK_OANDA_RESPONSE_SUCCESS = {
        "orderFillTransaction": {"id": "mock_fill_id"}
    }

    INTERNAL_ORDER_ID = "test-internal-order-uuid-123"


    def test_webhook_success(client, mocker):
        """Test successful webhook call and trade processing."""
        # Mock downstream services
        mocker.patch('webhook_server.server.process_signal', return_value=(PROCESSED_TRADE_PARAMS, None))
        mocker.patch('webhook_server.server.create_order_record', return_value=INTERNAL_ORDER_ID)
        mocker.patch('webhook_server.server.place_market_order', return_value=(MOCK_OANDA_RESPONSE_SUCCESS, None))
        mocker.patch('webhook_server.server.update_order_with_submission_response') # Just ensure it's called

        response = client.post('/webhook', json=VALID_SIGNAL_PAYLOAD)
        
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data["status"] == "success"
        assert json_data["internal_order_id"] == INTERNAL_ORDER_ID
        assert json_data["oanda_response"] == MOCK_OANDA_RESPONSE_SUCCESS

        # Assert that mocked functions were called
        from webhook_server import server # To access the patched functions
        server.process_signal.assert_called_once_with(VALID_SIGNAL_PAYLOAD)
        server.create_order_record.assert_called_once_with(VALID_SIGNAL_PAYLOAD, PROCESSED_TRADE_PARAMS)
        server.place_market_order.assert_called_once_with(instrument="EUR_USD", units=100)
        server.update_order_with_submission_response.assert_called_once_with(
            INTERNAL_ORDER_ID, MOCK_OANDA_RESPONSE_SUCCESS, None
        )

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
        mocker.patch('webhook_server.server.place_market_order', return_value=(None, oanda_error_msg))
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