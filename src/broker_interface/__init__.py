# src/broker_interface/__init__.py
import logging
from config.loader import get as config_get

logger = logging.getLogger(__name__)

def get_broker():
    """
    Broker Factory.
    """
    # Import broker implementations inside the function to avoid circular imports
    from .oanda_implementation import OandaBroker
    from .alpaca_implementation import AlpacaBroker # <-- NEW: Import AlpacaBroker

    # A mapping of broker names (from config) to their implementation classes
    BROKER_MAPPING = {
        "oanda": OandaBroker,
        "alpaca": AlpacaBroker, # <-- NEW: Add Alpaca to the mapping
    }

    # ... (rest of the get_broker function is unchanged) ...
    broker_name = config_get('broker.name')
    if not broker_name:
        raise ValueError("Broker not specified in configuration.")

    broker_class = BROKER_MAPPING.get(broker_name.lower())

    if not broker_class:
        raise ValueError(f"Unsupported broker: {broker_name}")

    logger.info(f"Instantiating broker: '{broker_name}'")
    try:
        broker_instance = broker_class()
        return broker_instance
    except Exception as e:
        logger.critical(f"Failed to instantiate broker '{broker_name}': {e}", exc_info=True)
        raise