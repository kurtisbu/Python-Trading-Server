# src/broker_interface/__init__.py
import logging
from config.loader import get as config_get

logger = logging.getLogger(__name__)

# NOTE: The broker implementations are NOT imported at the top level anymore.

def get_broker():
    """
    Broker Factory.

    Reads the configuration to determine which broker to instantiate,
    creates an instance, and returns it. Imports are done within this
    function to avoid circular dependency issues at module load time.

    Returns:
        An instance of a class that implements the BrokerInterface,
        or raises an exception if the configuration is invalid.
    """

    # 1. Import broker implementations inside the function.
    # This is the key change to break the import cycle.
    from .oanda_implementation import OandaBroker
    # Future brokers would be imported here too:
    # from .alpaca_implementation import AlpacaBroker

    # 2. Define the mapping inside the function as well.
    BROKER_MAPPING = {
        "oanda": OandaBroker,
        # "alpaca": AlpacaBroker,
    }

    broker_name = config_get('broker.name')
    if not broker_name:
        logger.critical("No broker specified in configuration (broker.name is missing).")
        raise ValueError("Broker not specified in configuration.")

    broker_name = broker_name.lower()
    broker_class = BROKER_MAPPING.get(broker_name)

    if not broker_class:
        logger.critical(f"Broker '{broker_name}' is not supported. Supported brokers are: {list(BROKER_MAPPING.keys())}")
        raise ValueError(f"Unsupported broker: {broker_name}")

    logger.info(f"Instantiating broker: '{broker_name}'")
    try:
        broker_instance = broker_class()
        return broker_instance
    except Exception as e:
        logger.critical(f"Failed to instantiate broker '{broker_name}': {e}", exc_info=True)
        raise