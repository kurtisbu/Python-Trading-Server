# src/broker_interface/oanda_implementation.py
import requests
import json
import logging

from .base import BrokerInterface # Import the base class from the same directory
from config.loader import get as config_get

logger = logging.getLogger(__name__)

class OandaBroker(BrokerInterface):
    """
    The Oanda-specific implementation of the BrokerInterface.
    """
    def __init__(self, config_params: dict = None):
        """
        Initializes the OandaBroker.
        It retrieves its necessary configuration using the central config loader.
        """
        self.api_key = config_get("OANDA_API_KEY")
        self.account_id = config_get("OANDA_ACCOUNT_ID")
        self.base_url = config_get("oanda.base_url", config_get("OANDA_API_URL"))
        self.headers = self._get_headers()

        if not all([self.api_key, self.account_id, self.base_url]):
            raise ValueError("OANDA API credentials or URL not fully configured. Check .env and config.yaml.")

        logger.info("OandaBroker initialized.")

    def _get_headers(self):
        """Helper method to construct authorization headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def check_connection(self) -> (bool, str):
        """Verifies connection and credentials by fetching account summary."""
        account_summary, error = self.get_account_summary()
        if error:
            message = f"Connection check failed: {error}"
            logger.error(message)
            return False, message

        message = f"Connection successful. Account ID: {account_summary.get('id')}, NAV: {account_summary.get('NAV')}"
        logger.info(message)
        return True, message

    def get_account_summary(self) -> (dict, str):
        """Retrieves account summary from Oanda."""
        endpoint = f"{self.base_url}/v3/accounts/{self.account_id}/summary"
        logger.info(f"Getting account summary from: {endpoint}")

        try:
            response = requests.get(endpoint, headers=self.headers, timeout=10)
            response.raise_for_status()
            account_summary = response.json().get('account', {})
            return account_summary, None
        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching account summary: {e}"
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f" | Response: {e.response.content.decode() if e.response.content else 'No content'}"
            logger.error(error_msg)
            return None, error_msg

    def place_market_order(self, instrument: str, units: int) -> (dict, str):
        """Places a market order with Oanda."""
        endpoint = f"{self.base_url}/v3/accounts/{self.account_id}/orders"
        order_data = {
            "order": {
                "units": str(units),
                "instrument": instrument,
                "timeInForce": "FOK",
                "type": "MARKET",
                "positionFill": "DEFAULT"
            }
        }

        logger.info(f"Placing market order via {endpoint}: {instrument}, Units: {units}")
        logger.debug(f"Order request payload: {json.dumps(order_data)}")

        try:
            response = requests.post(endpoint, headers=self.headers, json=order_data, timeout=15)
            response.raise_for_status()
            order_response = response.json()
            logger.info(f"Successfully placed market order. Response: {order_response}")
            return order_response, None
        except requests.exceptions.HTTPError as http_err:
            # ... (this detailed error parsing logic can be copied from your old oanda_client.py) ...
            error_msg = f"HTTP error placing order: {http_err}"
            if http_err.response is not None:
                response_text = http_err.response.content.decode() if http_err.response.content else ""
                try:
                    oanda_error_details = http_err.response.json()
                    reason = oanda_error_details.get("errorMessage") or oanda_error_details.get("orderRejectTransaction", {}).get("rejectReason")
                    if reason:
                         error_msg = f"Oanda Error: {reason}"
                except json.JSONDecodeError:
                    error_msg = f"Oanda HTTP error (non-JSON response): {http_err.response.status_code} - {response_text}"
            logger.error(error_msg)
            return None, error_msg
        except requests.exceptions.RequestException as req_err:
            error_msg = f"Request exception placing order: {req_err}"
            logger.error(error_msg)
            return None, error_msg


    def place_limit_order(self, instrument: str, units: int, price: float) -> (dict, str):
        """
        Places a limit order with Oanda.
        """
        endpoint = f"{self.base_url}/v3/accounts/{self.account_id}/orders"

        # Get the default time in force for limit orders from config
        time_in_force = config_get('trading.defaults.time_in_force', 'GTC')

        # Oanda API v20 payload for a LIMIT order
        order_data = {
            "order": {
                "units": str(units),
                "instrument": instrument,
                "price": str(price), # Oanda expects price as a string
                "timeInForce": time_in_force, # e.g., "GTC", "GFD", "GTD"
                "type": "LIMIT",
                "positionFill": "DEFAULT"
            }
        }

        logger.info(f"Placing LIMIT order via {endpoint}: {instrument}, Units: {units}, Price: {price}")
        logger.debug(f"Order request payload: {json.dumps(order_data)}")

        try:
            response = requests.post(endpoint, headers=self.headers, json=order_data, timeout=15)
            response.raise_for_status()
            order_response = response.json()

            # A successfully placed limit order will usually return an 'orderCreateTransaction'.
            # It will not be filled immediately unless the price is already met.
            if "orderCreateTransaction" in order_response:
                create_details = order_response["orderCreateTransaction"]
                logger.info(f"Successfully created LIMIT order. Oanda Order ID: {create_details.get('id')}, Reason: {create_details.get('reason')}")
            elif "orderCancelTransaction" in order_response:
                # This could happen if the order is immediately cancelled for some reason (e.g., price is too far away)
                cancel_details = order_response["orderCancelTransaction"]
                logger.warning(f"LIMIT order was immediately cancelled. Reason: {cancel_details.get('reason')}")
            else:
                logger.info(f"Successfully placed LIMIT order (unexpected response format). Response: {order_response}")

            return order_response, None

        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP error placing limit order: {http_err}"
            if http_err.response is not None:
                response_text = http_err.response.content.decode() if http_err.response.content else ""
                try:
                    oanda_error_details = http_err.response.json()
                    reason = oanda_error_details.get("errorMessage") or oanda_error_details.get("orderRejectTransaction", {}).get("rejectReason")
                    if reason:
                        error_msg = f"Oanda Error: {reason}"
                except json.JSONDecodeError:
                    error_msg = f"Oanda HTTP error (non-JSON response): {http_err.response.status_code} - {response_text}"
            logger.error(error_msg)
            return None, error_msg
        except requests.exceptions.RequestException as req_err:
            error_msg = f"Request exception placing limit order: {req_err}"
            logger.error(error_msg)
            return None, error_msg



    # --- Implement future methods with NotImplementedError ---
    def get_order_status(self, order_id: str) -> (dict, str):
        logger.warning("get_order_status is not yet implemented for OandaBroker.")
        raise NotImplementedError("Get order status functionality is not implemented.")

    def cancel_order(self, order_id: str) -> (dict, str):
        logger.warning("cancel_order is not yet implemented for OandaBroker.")
        raise NotImplementedError("Cancel order functionality is not implemented.")