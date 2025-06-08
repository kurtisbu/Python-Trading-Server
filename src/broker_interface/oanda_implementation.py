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
        self.base_url = config_get("brokers.oanda.base_url", config_get("OANDA_API_URL"))
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

    def place_market_order(self, instrument: str, units: int, stop_loss: float = None, take_profit: float = None) -> (dict, str):
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

        sl_tp_time_in_force = config_get('trading.defaults.time_in_force', 'GTC')
        if stop_loss:
            order_data["order"]["stopLossOnFill"] = {
                "timeInForce": sl_tp_time_in_force,
                "price": str(stop_loss)
            }
        if take_profit:
            order_data["order"]["takeProfitOnFill"] = {
                "timeInForce": sl_tp_time_in_force,
                "price": str(take_profit)
            }

        logger.info(f"Placing market order: {instrument}, Units: {units}, SL: {stop_loss if stop_loss else 'N/A'}, TP: {take_profit if take_profit else 'N/A'}")
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


    def place_limit_order(self, instrument: str, units: int, price: float, stop_loss: float = None, take_profit: float = None) -> (dict, str):
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

        if stop_loss:
            order_data["order"]["stopLossOnFill"] = {
                "timeInForce": time_in_force, # SL/TP orders are also GTC by default
                "price": str(stop_loss)
            }
        if take_profit:
            order_data["order"]["takeProfitOnFill"] = {
                "timeInForce": time_in_force,
                "price": str(take_profit)
            }

        logger.info(f"Placing LIMIT order: {instrument}, Units: {units}, SL: {stop_loss if stop_loss else 'N/A'}, TP: {take_profit if take_profit else 'N/A'}")
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

    def place_stop_order(self, instrument: str, units: int, price: float, stop_loss: float = None, take_profit: float = None) -> (dict, str):
        """
        Places a stop order (stop-entry order) with Oanda.

        Note: This creates an order that will become a market order when the price
        hits the specified stop price. It is NOT a stop-loss on an existing trade.
        """
        endpoint = f"{self.base_url}/v3/accounts/{self.account_id}/orders"

        time_in_force = config_get('trading.defaults.time_in_force', 'GTC')

        # Oanda API v20 payload for a STOP order
        order_data = {
            "order": {
                "units": str(units),
                "instrument": instrument,
                "price": str(price), # The stop price that triggers the market order
                "timeInForce": time_in_force,
                "type": "STOP",
                "positionFill": "DEFAULT"
            }
        }

        if stop_loss:
            order_data["order"]["stopLossOnFill"] = {
                "timeInForce": time_in_force,
                "price": str(stop_loss)
            }
        if take_profit:
            order_data["order"]["takeProfitOnFill"] = {
                "timeInForce": time_in_force,
                "price": str(take_profit)
            }

        logger.info(f"Placing STOP order: {instrument}, Units: {units}, SL: {stop_loss if stop_loss else 'N/A'}, TP: {take_profit if take_profit else 'N/A'}")
        logger.debug(f"Order request payload: {json.dumps(order_data)}")

        try:
            response = requests.post(endpoint, headers=self.headers, json=order_data, timeout=15)
            response.raise_for_status()
            order_response = response.json()

            # A successfully placed stop order will return an 'orderCreateTransaction'.
            if "orderCreateTransaction" in order_response:
                create_details = order_response["orderCreateTransaction"]
                logger.info(f"Successfully created STOP order. Oanda Order ID: {create_details.get('id')}, Reason: {create_details.get('reason')}")
            else:
                logger.info(f"Successfully placed STOP order (unexpected response format). Response: {order_response}")

            return order_response, None

        except requests.exceptions.HTTPError as http_err:
            # This error handling logic is the same as for other order types
            error_msg = f"HTTP error placing stop order: {http_err}"
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
            error_msg = f"Request exception placing stop order: {req_err}"
            logger.error(error_msg)
            return None, error_msg


    def get_order_status(self, order_id: str) -> (dict, str):
        logger.warning("get_order_status is not yet implemented for OandaBroker.")
        raise NotImplementedError("Get order status functionality is not implemented.")

    def cancel_order(self, order_id: str) -> (dict, str):
        """
        Cancels a pending order on Oanda.

        Args:
            order_id (str): The broker-specific order ID to cancel (e.g., "1234").

        Returns:
            tuple[dict, str]: Cancellation confirmation details or error.
        """
        # The Oanda API endpoint for cancelling an order is a PUT request
        endpoint = f"{self.base_url}/v3/accounts/{self.account_id}/orders/{order_id}/cancel"

        logger.info(f"Attempting to cancel order ID: {order_id} via endpoint: {endpoint}")

        try:
            response = requests.put(endpoint, headers=self.headers, timeout=15)
            response.raise_for_status()
            cancellation_response = response.json()

            if "orderCancelTransaction" in cancellation_response:
                cancel_details = cancellation_response["orderCancelTransaction"]
                reason = cancel_details.get('reason')
                logger.info(f"Successfully sent cancellation request for order ID {order_id}. Reason: {reason}")
            else:
                logger.warning(f"Order cancellation for {order_id} submitted, but response format was unexpected: {cancellation_response}")

            return cancellation_response, None

        except requests.exceptions.HTTPError as http_err:
            # This error logic is reusable and robust for handling API errors
            error_msg = f"HTTP error cancelling order {order_id}: {http_err}"
            if http_err.response is not None:
                response_text = http_err.response.content.decode() if http_err.response.content else ""
                # Oanda often provides a reject transaction on a failed cancel attempt (e.g., order already filled)
                try:
                    oanda_error_details = http_err.response.json()
                    reason = oanda_error_details.get("errorMessage") or oanda_error_details.get("orderCancelRejectTransaction", {}).get("rejectReason")
                    if reason:
                        error_msg = f"Oanda Error: {reason}"
                except json.JSONDecodeError:
                    error_msg = f"Oanda HTTP error (non-JSON response): {http_err.response.status_code} - {response_text}"
            logger.error(error_msg)
            return None, error_msg
        except requests.exceptions.RequestException as req_err:
            error_msg = f"Request exception cancelling order {order_id}: {req_err}"
            logger.error(error_msg)
            return None, error_msg