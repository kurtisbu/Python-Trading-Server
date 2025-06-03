import requests
import json
import logging
import os # Keep os if still used for path constructions, but not for getenv directly for these configs

# --- Python Path Adjustment (if not already robustly handled elsewhere or if running standalone) ---
# Ensures 'config' can be found if this script is run directly for testing
if __name__ == '__main__': # Add path adjustment only when run directly
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir_path = os.path.dirname(current_script_dir) # Should be 'src'
    project_root_dir_path = os.path.dirname(src_dir_path) # Should be project root
    if src_dir_path not in sys.path:
        sys.path.insert(0, src_dir_path)
    if project_root_dir_path not in sys.path: # To find config if module is run directly
        sys.path.insert(0, project_root_dir_path)
# --- End Path Adjustment ---

from config.loader import get as config_get # Import the new config getter

logger = logging.getLogger(__name__)

# --- Remove old .env loading specific to this file ---
# # Load environment variables from .env file
# # Assuming .env is two levels up from src/broker_interface/
# dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
# load_dotenv(dotenv_path=dotenv_path, override=True) # Ensure override is True

# --- Get Oanda credentials and API URL from the centralized config system ---
# The config loader gives priority to these .env variables if they are defined.
# OANDA_API_URL from .env will be used for 'oanda.base_url' if config.loader's init has that logic.
API_KEY = config_get("OANDA_API_KEY")
ACCOUNT_ID = config_get("OANDA_ACCOUNT_ID")
# Get 'oanda.base_url' from config.yaml, which might have been overridden by OANDA_API_URL from .env
BASE_URL = config_get("oanda.base_url", config_get("OANDA_API_URL")) # Fallback to direct OANDA_API_URL if oanda.base_url isn't set

# Debugging: Print loaded values when module is loaded
# (Useful during development, can be commented out later)
# logger.debug(f"OANDA_CLIENT: API_KEY loaded: {'Yes' if API_KEY else 'No'}")
# logger.debug(f"OANDA_CLIENT: ACCOUNT_ID loaded: {ACCOUNT_ID}")
# logger.debug(f"OANDA_CLIENT: BASE_URL loaded: {BASE_URL}")

def _get_headers():
    """Helper function to get authorization headers."""
    if not API_KEY:
        logger.critical("OANDA_API_KEY not found in configuration.")
        # This typically means it's missing from your .env file
        raise ValueError("OANDA_API_KEY not configured.")
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

def check_oanda_connection():
    """
    Checks the connection to Oanda by fetching account summary.
    """
    # Ensure config values are loaded
    if not all([API_KEY, ACCOUNT_ID, BASE_URL]):
        logger.error("OANDA API credentials or URL not fully configured. Check .env and config.yaml.")
        # Print details for easier debugging
        logger.error(f"API_KEY: {'Set' if API_KEY else 'Missing'}, ACCOUNT_ID: {'Set' if ACCOUNT_ID else 'Missing'}, BASE_URL: {'Set' if BASE_URL else 'Missing'}")
        return False

    headers = _get_headers()
    endpoint = f"{BASE_URL}/v3/accounts/{ACCOUNT_ID}/summary"
    logger.info(f"Checking Oanda connection to endpoint: {endpoint}")

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        account_summary = response.json()
        logger.info("Successfully connected to Oanda and fetched account summary.")
        if 'account' in account_summary and 'NAV' in account_summary['account']:
             logger.info(f"  Account ID: {account_summary['account'].get('id')}, NAV: {account_summary['account'].get('NAV')}")
        else:
            logger.warning("Could not parse expected fields from account summary.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error during Oanda connection check: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response content: {e.response.content.decode() if e.response.content else 'No content'}")
        return False
    except Exception as e: # Catch any other unexpected error
        logger.error(f"Unexpected error during Oanda connection check: {e}", exc_info=True)
        return False


def place_market_order(instrument: str, units: int):
    """
    Places a market order with Oanda.
    """
    if not all([API_KEY, ACCOUNT_ID, BASE_URL]):
        error_msg = "OANDA API credentials or URL not fully configured for placing order."
        logger.critical(error_msg)
        logger.critical(f"API_KEY: {'Set' if API_KEY else 'Missing'}, ACCOUNT_ID: {'Set' if ACCOUNT_ID else 'Missing'}, BASE_URL: {'Set' if BASE_URL else 'Missing'}")
        return None, error_msg

    headers = _get_headers()
    endpoint = f"{BASE_URL}/v3/accounts/{ACCOUNT_ID}/orders"

    order_data = {
        "order": {
            "units": str(units),
            "instrument": instrument,
            "timeInForce": "FOK", 
            "type": "MARKET",
            "positionFill": "DEFAULT"
        }
    }

    logger.info(f"Attempting to place market order via {endpoint}: {instrument}, Units: {units}")
    logger.debug(f"Order request payload: {json.dumps(order_data)}")

    try:
        response = requests.post(endpoint, headers=headers, json=order_data, timeout=15)
        response.raise_for_status() 

        order_response = response.json()
        # ... (rest of the parsing logic for order_response, unchanged) ...
        logger.info(f"Successfully placed market order. Response: {order_response}")
        if "orderFillTransaction" in order_response:
            fill_details = order_response["orderFillTransaction"]
            logger.info(f"Order filled. Trade ID: {fill_details.get('tradeOpenedID') or fill_details.get('tradeReducedID')}, Price: {fill_details.get('price')}, Units: {fill_details.get('units')}")
            return order_response, None
        elif "orderCreateTransaction" in order_response:
            create_details = order_response["orderCreateTransaction"]
            logger.info(f"Order created. Order ID: {create_details.get('id')}")
            return order_response, None 
        else:
            logger.warning(f"Order placement response did not contain expected transaction details directly. Full response: {order_response}")
            return order_response, "Order placed but response format unexpected."

    except requests.exceptions.HTTPError as http_err:
        error_msg = f"HTTP error placing order: {http_err}"
        logger.error(error_msg)
        if http_err.response is not None:
            response_text = http_err.response.content.decode() if http_err.response.content else "No response content"
            logger.error(f"Oanda Response Content: {response_text}")
            try:
                oanda_error_details = http_err.response.json()
                if "errorMessage" in oanda_error_details:
                    error_msg = f"Oanda Error: {oanda_error_details['errorMessage']}"
                elif "rejectReason" in oanda_error_details.get("orderRejectTransaction", {}):
                     error_msg = f"Oanda Order Reject Reason: {oanda_error_details['orderRejectTransaction']['rejectReason']}"
            except json.JSONDecodeError:
                error_msg = f"Oanda HTTP error (non-JSON response): {http_err.response.status_code} - {response_text}"
        return None, error_msg
    except requests.exceptions.RequestException as req_err: # Catch other requests errors like connection issues
        error_msg = f"Request exception placing order: {req_err}"
        logger.error(error_msg)
        return None, error_msg
    except Exception as e: # Catch any other unexpected error
        error_msg = f"An unexpected error occurred during order placement: {e}"
        logger.critical(error_msg, exc_info=True)
        return None, error_msg

if __name__ == "__main__":
    # --- Add sys import for path adjustment when run directly ---
    import sys 
    # --- End sys import ---

    # Basic logging for direct script execution
    # The config.loader will initialize config if not already done by an import
    # but for standalone, we might need to ensure logging is set up.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("--- Oanda Client Script Execution (using centralized config) ---")

    # The config should be initialized by importing config.loader.
    # If you need to force re-init for standalone test:
    # from config.loader import initialize_config
    # initialize_config()

    if not all([API_KEY, ACCOUNT_ID, BASE_URL]):
        logger.error("API credentials or URL not fully loaded via config. Check .env, config.yaml, and config/loader.py.")
        logger.error(f"Current values - API_KEY: {'Set' if API_KEY else 'Not Set'}, ACCOUNT_ID: {ACCOUNT_ID}, BASE_URL: {BASE_URL}")
    else:
        logger.info(f"Using Account ID: {ACCOUNT_ID} and Base URL: {BASE_URL}")

        logger.info("1. Testing Oanda Connection...")
        if check_oanda_connection():
            logger.info("Connection test PASSED.")
        else:
            logger.error("Connection test FAILED.")

        # ... (rest of the test code for placing market order can remain, it will use the config-loaded values) ...
        confirm_trade = input("Do you want to attempt to place a test market order on your DEMO account? (yes/no): ").lower()
        if confirm_trade == 'yes':
            logger.info("\n2. Testing Market Order Placement...")
            test_instrument = config_get("trading.instrument_settings.EUR_USD.test_instrument", "EUR_USD") # Example getting a test param
            test_units_buy = config_get("trading.instrument_settings.EUR_USD.test_units", 1)

            logger.info(f"Attempting to BUY {test_units_buy} of {test_instrument}")
            order_resp_buy, error_buy = place_market_order(test_instrument, test_units_buy)
            if error_buy:
                logger.error(f"BUY Order Test FAILED: {error_buy}")
            else:
                logger.info(f"BUY Order Test SUCCEEDED. Response: {order_resp_buy}")
        else:
            logger.info("Skipping test market order placement.")
    logger.info("--- Oanda Client Script Execution Finished ---")