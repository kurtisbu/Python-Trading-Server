import logging
import os # Keep for path constructions if needed in standalone test

# --- Python Path Adjustment (if not already robustly handled elsewhere or if running standalone) ---
if __name__ == '__main__': # Add path adjustment only when run directly
    import sys
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir_path = os.path.dirname(current_script_dir)
    project_root_dir_path = os.path.dirname(src_dir_path)
    if src_dir_path not in sys.path:
        sys.path.insert(0, src_dir_path)
    if project_root_dir_path not in sys.path:
         sys.path.insert(0, project_root_dir_path) # To find config if module is run directly
# --- End Path Adjustment ---

from config.loader import get as config_get # Import the new config getter

logger = logging.getLogger(__name__)

def process_signal(signal_data: dict):
    """
    Validates and processes the incoming signal data using centralized configuration.
    Converts it into parameters suitable for placing a trade.
    """
    logger.info(f"Processing signal: {signal_data}")

    # --- Get configurations ---
    allowed_instruments = config_get('trading.allowed_instruments', []) # Default to empty list if not in config
    global_default_quantity = config_get('trading.defaults.quantity', 1) # Default from global settings
    global_default_order_type = config_get('trading.defaults.order_type', 'MARKET')

    required_fields = ["instrument", "action"] # Quantity can now be optional if defaults are used
    for field in required_fields:
        if field not in signal_data:
            error_msg = f"Missing required signal field: {field}"
            logger.error(error_msg)
            return None, error_msg

    instrument = signal_data.get("instrument", "").upper() # Ensure instrument is uppercase for matching
    action = signal_data.get("action", "").lower()
    quantity_from_signal = signal_data.get("quantity") # Can be None
    order_type_from_signal = signal_data.get("type", global_default_order_type).lower()

    # 1. Validate Instrument
    if not instrument:
        error_msg = "Instrument field is missing or empty in the signal."
        logger.error(error_msg)
        return None, error_msg
    if allowed_instruments and instrument not in allowed_instruments:
        error_msg = f"Instrument '{instrument}' is not in allowed_instruments list from config. Allowed: {allowed_instruments}"
        logger.error(error_msg)
        return None, error_msg

    # 2. Validate Action
    if action not in ["buy", "sell"]:
        error_msg = f"Invalid action: '{action}'. Must be 'buy' or 'sell'."
        logger.error(error_msg)
        return None, error_msg

    # 3. Determine Quantity (use signal, then instrument-specific default, then global default)
    final_quantity = quantity_from_signal
    if final_quantity is None:
        # Check for instrument-specific default quantity
        instr_specific_qty = config_get(f'trading.instrument_settings.{instrument}.default_quantity')
        if instr_specific_qty is not None:
            final_quantity = instr_specific_qty
            logger.info(f"Using instrument-specific default quantity for {instrument}: {final_quantity}")
        else:
            final_quantity = global_default_quantity
            logger.info(f"Using global default quantity: {final_quantity}")

    # 4. Validate Quantity (must be a positive number after defaults are applied)
    if not isinstance(final_quantity, (int, float)) or final_quantity <= 0:
        error_msg = f"Invalid quantity: {final_quantity}. Must be a positive number (from signal or defaults)."
        logger.error(error_msg)
        return None, error_msg

    # Optional: Validate against min/max quantity from config if defined
    min_qty = config_get(f'trading.instrument_settings.{instrument}.min_quantity')
    max_qty = config_get(f'trading.instrument_settings.{instrument}.max_quantity')
    if min_qty is not None and final_quantity < min_qty:
        error_msg = f"Quantity {final_quantity} for {instrument} is below minimum allowed ({min_qty})."
        logger.error(error_msg)
        return None, error_msg
    if max_qty is not None and final_quantity > max_qty:
        error_msg = f"Quantity {final_quantity} for {instrument} exceeds maximum allowed ({max_qty})."
        logger.error(error_msg)
        return None, error_msg


    # 5. Validate Order Type (for now, only market is processed for action by Oanda client)
    if order_type_from_signal != "market":
        # If you plan to support other types, this logic will expand.
        # For now, our Oanda client only places market orders.
        logger.warning(f"Signal specified order type '{order_type_from_signal}'. Current execution is for MARKET orders.")
        # If strictly only market, you might return an error here:
        # error_msg = f"Unsupported order type: {order_type_from_signal}. Currently only 'market' is supported."
        # logger.error(error_msg)
        # return None, error_msg
        pass # Allow it to proceed as 'market' effectively if that's the only execution path


    # Convert 'buy'/'sell' and quantity to Oanda's unit convention
    units = final_quantity if action == "buy" else -final_quantity

    trade_parameters = {
        "instrument": instrument,
        "units": units,
        "order_type": "MARKET" # Hardcoding to market as it's what oanda_client supports now
                               # order_type_from_signal can be used for future logic/logging
    }

    logger.info(f"Processed trade parameters: {trade_parameters} (Original signal type: {order_type_from_signal})")
    return trade_parameters, None

if __name__ == '__main__':
    # --- Add sys import for path adjustment when run directly ---
    import sys
    # --- End sys import ---

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # Ensure config is initialized for standalone testing of processor.py
    from config.loader import initialize_config
    _config = None # Force re-init for testing if needed
    _env_vars = {} # Force re-init for testing if needed
    initialize_config() # This uses default paths to config.yaml and .env in project root

    logger.info("--- Testing Signal Processor with Centralized Config ---")

    # Test cases - assuming config.yaml has EUR_USD and USD_JPY in allowed_instruments
    # and relevant default quantities.
    tests = [
        {"signal": {"instrument": "EUR_USD", "action": "buy", "quantity": 150}, "desc": "Valid EUR_USD Buy"},
        {"signal": {"instrument": "USD_JPY", "action": "sell"}, "desc": "Valid USD_JPY Sell, use default qty"},
        {"signal": {"instrument": "EUR_USD", "action": "buy"}, "desc": "EUR_USD buy, use instrument-specific default qty"},
        {"signal": {"instrument": "NON_EXISTENT", "action": "buy", "quantity": 100}, "desc": "Invalid Instrument"},
        {"signal": {"instrument": "EUR_USD", "action": "hold", "quantity": 100}, "desc": "Invalid Action"},
        {"signal": {"instrument": "EUR_USD", "action": "buy", "quantity": 0}, "desc": "Invalid Quantity (zero)"},
        {"signal": {"action": "buy", "quantity": 100}, "desc": "Missing Instrument"},
        # Add a test for min_quantity if configured
        # {"signal": {"instrument": "EUR_USD", "action": "buy", "quantity": 0.5}, "desc": "Below min quantity (if min_qty for EUR_USD is 1)"},
    ]

    for test in tests:
        print(f"\n--- Test: {test['desc']} ---")
        print(f"Input Signal: {test['signal']}")
        params, err = process_signal(test['signal'])
        if err:
            print(f"Error: {err}")
        else:
            print(f"Processed Params: {params}")

    logger.info("--- Signal Processor Tests Complete ---")