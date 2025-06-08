# src/broker_interface/alpaca_implementation.py
import requests
import json
import logging

from .base import BrokerInterface
from config.loader import get as config_get

logger = logging.getLogger(__name__)

class AlpacaBroker(BrokerInterface):
    """
    The Alpaca-specific implementation of the BrokerInterface.
    """
    def __init__(self, config_params: dict = None):
        """
        Initializes the AlpacaBroker.
        It retrieves its necessary configuration using the central config loader.
        """
        self.api_key_id = config_get("ALPACA_API_KEY_ID")
        self.secret_key = config_get("ALPACA_API_SECRET_KEY")
        self.base_url = config_get("brokers.alpaca.base_url")
        self.headers = self._get_headers()

        if not all([self.api_key_id, self.secret_key, self.base_url]):
            raise ValueError("Alpaca API credentials or URL not fully configured. Check .env and config.yaml.")

        logger.info("AlpacaBroker initialized.")

    def _get_headers(self):
        """Helper method to construct Alpaca-specific authorization headers."""
        return {
            "APCA-API-KEY-ID": self.api_key_id,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json"
        }

    def check_connection(self) -> (bool, str):
        """Verifies connection by fetching account details."""
        # We'll implement this next. For now, it relies on get_account_summary.
        account_summary, error = self.get_account_summary()
        if error:
            message = f"Alpaca connection check failed: {error}"
            logger.error(message)
            return False, message

        message = f"Alpaca connection successful. Account ID: {account_summary.get('id')}, Buying Power: {account_summary.get('buying_power')}"
        logger.info(message)
        return True, message

    def get_account_summary(self) -> (dict, str):
        """Retrieves account information from Alpaca."""
        endpoint = f"{self.base_url}/v2/account"
        logger.info(f"Getting Alpaca account summary from: {endpoint}")

        try:
            response = requests.get(endpoint, headers=self.headers, timeout=10)
            response.raise_for_status()
            # The entire response body is the account object for Alpaca
            account_summary = response.json()
            return account_summary, None
        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching Alpaca account summary: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    # Alpaca error messages are often in a 'message' key
                    error_details = e.response.json().get('message', 'No details provided.')
                    error_msg += f" | Details: {error_details}"
                except json.JSONDecodeError:
                    error_msg += f" | Response: {e.response.content.decode() if e.response.content else 'No content'}"
            logger.error(error_msg)
            return None, error_msg

    # --- Stubs for all other required methods ---

    def place_market_order(self, instrument: str, units: int, stop_loss: float = None, take_profit: float = None) -> (dict, str):
        """
        Places a market order with Alpaca.
        Handles optional Stop Loss and Take Profit (bracket order).
        """
        endpoint = f"{self.base_url}/v2/orders"

        # --- TRANSLATION LOGIC ---
        # Alpaca uses 'symbol' instead of 'instrument'
        # Alpaca uses 'side' ('buy'/'sell') and positive 'qty' instead of signed 'units'
        side = 'buy' if units > 0 else 'sell'
        qty = abs(units)
        # Alpaca uses 'day' as a common time_in_force for stocks
        time_in_force = 'day'

        order_data = {
            "symbol": instrument,
            "qty": qty,
            "side": side,
            "type": "market",
            "time_in_force": time_in_force
        }

        # --- Add SL/TP if provided (Bracket Order) ---
        if stop_loss or take_profit:
            order_data["order_class"] = "bracket"
            if stop_loss:
                order_data["stop_loss"] = {"stop_price": stop_loss}
            if take_profit:
                order_data["take_profit"] = {"limit_price": take_profit}

        logger.info(f"Placing Alpaca market order: {side} {qty} {instrument}")
        logger.debug(f"Alpaca order request payload: {json.dumps(order_data)}")

        try:
            response = requests.post(endpoint, headers=self.headers, json=order_data, timeout=15)
            response.raise_for_status()
            order_response = response.json()
            logger.info(f"Successfully placed Alpaca market order. Response: {order_response}")
            return order_response, None
        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP error placing Alpaca order: {http_err}"
            if http_err.response is not None:
                try:
                    error_details = http_err.response.json().get('message', 'No details provided.')
                    error_msg += f" | Details: {error_details}"
                except json.JSONDecodeError:
                    error_msg += f" | Response: {http_err.response.text}"
            logger.error(error_msg)
            return None, error_msg
        except requests.exceptions.RequestException as req_err:
            error_msg = f"Request exception placing Alpaca order: {req_err}"
            logger.error(error_msg)
            return None, error_msg

    def place_limit_order(self, instrument: str, units: int, price: float, stop_loss: float = None, take_profit: float = None) -> (dict, str):
        """
        Places a limit order with Alpaca.
        Handles optional Stop Loss and Take Profit (bracket order).
        """
        endpoint = f"{self.base_url}/v2/orders"

        # --- Parameter Translation ---
        side = 'buy' if units > 0 else 'sell'
        qty = abs(units)
        time_in_force = config_get('trading.defaults.time_in_force', 'gtc').lower() # gtc is common for limit

        order_data = {
            "symbol": instrument,
            "qty": qty,
            "side": side,
            "type": "limit",
            "time_in_force": time_in_force,
            "limit_price": price # Key for limit orders
        }

        # --- Add SL/TP if provided (Bracket Order) ---
        if stop_loss or take_profit:
            order_data["order_class"] = "bracket"
            if stop_loss:
                order_data["stop_loss"] = {"stop_price": stop_loss}
            if take_profit:
                order_data["take_profit"] = {"limit_price": take_profit}

        logger.info(f"Placing Alpaca LIMIT order: {side} {qty} {instrument} @ {price}")
        logger.debug(f"Alpaca order request payload: {json.dumps(order_data)}")

        try:
            response = requests.post(endpoint, headers=self.headers, json=order_data, timeout=15)
            response.raise_for_status()
            order_response = response.json()
            logger.info(f"Successfully placed Alpaca limit order. Response: {order_response}")
            return order_response, None
        except requests.exceptions.HTTPError as http_err:
            # This generic error handler works well for all order types
            error_msg = f"HTTP error placing Alpaca order: {http_err}"
            if http_err.response is not None:
                try:
                    error_details = http_err.response.json().get('message', 'No details provided.')
                    error_msg += f" | Details: {error_details}"
                except json.JSONDecodeError:
                    error_msg += f" | Response: {http_err.response.text}"
            logger.error(error_msg)
            return None, error_msg
        except requests.exceptions.RequestException as req_err:
            error_msg = f"Request exception placing Alpaca order: {req_err}"
            logger.error(error_msg)
            return None, error_msg

    def place_stop_order(self, instrument: str, units: int, price: float, stop_loss: float = None, take_profit: float = None) -> (dict, str):
        """
        Places a stop order with Alpaca.
        Handles optional Stop Loss and Take Profit (bracket order).
        """
        endpoint = f"{self.base_url}/v2/orders"

        # --- Parameter Translation ---
        side = 'buy' if units > 0 else 'sell'
        qty = abs(units)
        time_in_force = config_get('trading.defaults.time_in_force', 'gtc').lower()

        order_data = {
            "symbol": instrument,
            "qty": qty,
            "side": side,
            "type": "stop",
            "time_in_force": time_in_force,
            "stop_price": price # Key for stop orders
        }

        # --- Add SL/TP if provided (Bracket Order) ---
        if stop_loss or take_profit:
            order_data["order_class"] = "bracket"
            if stop_loss:
                order_data["stop_loss"] = {"stop_price": stop_loss}
            if take_profit:
                order_data["take_profit"] = {"limit_price": take_profit}

        logger.info(f"Placing Alpaca STOP order: {side} {qty} {instrument} @ {price}")
        logger.debug(f"Alpaca order request payload: {json.dumps(order_data)}")

        try:
            # The execution logic is identical to the other order types
            response = requests.post(endpoint, headers=self.headers, json=order_data, timeout=15)
            response.raise_for_status()
            order_response = response.json()
            logger.info(f"Successfully placed Alpaca stop order. Response: {order_response}")
            return order_response, None
        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP error placing Alpaca order: {http_err}"
            if http_err.response is not None:
                try:
                    error_details = http_err.response.json().get('message', 'No details provided.')
                    error_msg += f" | Details: {error_details}"
                except json.JSONDecodeError:
                    error_msg += f" | Response: {http_err.response.text}"
            logger.error(error_msg)
            return None, error_msg
        except requests.exceptions.RequestException as req_err:
            error_msg = f"Request exception placing Alpaca order: {req_err}"
            logger.error(error_msg)
            return None, error_msg

    def get_order_status(self, order_id: str) -> (dict, str):
        raise NotImplementedError("get_order_status is not yet implemented for AlpacaBroker.")

    def cancel_order(self, order_id: str) -> (dict, str):
        """
        Cancels a pending order on Alpaca.

        Args:
            order_id (str): The broker-specific order ID from Alpaca.

        Returns:
            tuple[dict, str]: An empty dict on success, or an error message.
        """
        # The Alpaca API endpoint for cancelling an order is a DELETE request
        endpoint = f"{self.base_url}/v2/orders/{order_id}"

        logger.info(f"Attempting to cancel Alpaca order ID: {order_id} via endpoint: {endpoint}")

        try:
            response = requests.delete(endpoint, headers=self.headers, timeout=15)
            response.raise_for_status()

            # A successful DELETE request to Alpaca returns a 204 No Content status
            # and an empty response body. We'll return a simple success dictionary.
            logger.info(f"Successfully sent cancellation request for Alpaca order ID {order_id}.")
            success_response = {
                "status": "cancellation_requested",
                "order_id": order_id
            }
            return success_response, None

        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP error cancelling Alpaca order {order_id}: {http_err}"
            if http_err.response is not None:
                try:
                    # e.g., Alpaca returns 422 Unprocessable Entity if order isn't open
                    error_details = http_err.response.json().get('message', 'No details provided.')
                    error_msg += f" | Details: {error_details}"
                except json.JSONDecodeError:
                    error_msg += f" | Response: {http_err.response.text}"
            logger.error(error_msg)
            return None, error_msg
        except requests.exceptions.RequestException as req_err:
            error_msg = f"Request exception cancelling Alpaca order {order_id}: {req_err}"
            logger.error(error_msg)
            return None, error_msg