# src/broker_interface/base.py
from abc import ABC, abstractmethod

class BrokerInterface(ABC):
    """
    Abstract Base Class defining the contract for all broker implementations.

    This ensures that any broker client we write has a consistent set of methods
    that the rest of our application can rely on.
    """

    @abstractmethod
    def __init__(self, config_params: dict):
        """
        Constructor for the broker implementation.
        Should take configuration parameters needed for this specific broker.
        """
        pass

    @abstractmethod
    def check_connection(self) -> (bool, str):
        """
        Verifies the connection to the broker's API using the provided credentials.

        Returns:
            tuple[bool, str]: A tuple containing:
                - bool: True if connection is successful, False otherwise.
                - str: A message indicating status or error details.
        """
        pass

    @abstractmethod
    def get_account_summary(self) -> (dict, str):
        """
        Retrieves a summary of the trading account.

        Returns:
            tuple[dict, str]: A tuple containing:
                - dict: Account summary data if successful, None otherwise.
                - str: An error message if failed, None otherwise.
        """
        pass

    @abstractmethod
    def place_market_order(self, instrument: str, units: int) -> (dict, str):
        """
        Places a market order for a specified instrument and number of units.

        Args:
            instrument (str): The trading instrument (e.g., "EUR_USD").
            units (int): The number of units to trade. Positive for buy, negative for sell.

        Returns:
            tuple[dict, str]: A tuple containing:
                - dict: The response from the broker if successful, None otherwise.
                - str: An error message if failed, None otherwise.
        """
        pass

    # --- Define methods for future features (like limit orders) ---
    # By defining them now, we ensure the interface is ready for them.
    # Implementations can raise NotImplementedError until they are built.

    @abstractmethod
    def place_limit_order(self, instrument: str, units: int, price: float) -> (dict, str):
        """
        Places a limit order.

        Args:
            instrument (str): The trading instrument.
            units (int): The number of units. Positive for buy, negative for sell.
            price (float): The limit price at which to execute the order.

        Returns:
            tuple[dict, str]: Broker response or error.
        """
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> (dict, str):
        """
        Retrieves the status of a specific order by its ID.

        Args:
            order_id (str): The broker-specific order ID.

        Returns:
            tuple[dict, str]: Order status details or error.
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> (dict, str):
        """
        Cancels a pending order.

        Args:
            order_id (str): The broker-specific order ID to cancel.

        Returns:
            tuple[dict, str]: Cancellation confirmation or error.
        """
        pass