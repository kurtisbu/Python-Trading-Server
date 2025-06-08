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
    Validates and processes incoming signal data, now supporting MARKET, LIMIT, and STOP orders.
    """
    logger.info(f"Processing signal: {signal_data}")

    # --- Get configurations ---
    allowed_instruments = config_get('trading.allowed_instruments', [])
    global_default_quantity = config_get('trading.defaults.quantity', 1)
    global_default_order_type = config_get('trading.defaults.order_type', 'MARKET').upper()

    required_fields = ["instrument", "action"]
    for field in required_fields:
        if field not in signal_data:
            error_msg = f"Missing required signal field: {field}"
            logger.error(error_msg)
            return None, error_msg

    instrument = signal_data.get("instrument", "").upper()
    action = signal_data.get("action", "").lower()
    
    # --- FIX: Ensure quantity_from_signal is defined here ---
    quantity_from_signal = signal_data.get("quantity")
    
    order_type_from_signal = signal_data.get("type", global_default_order_type).upper()
    trigger_price = signal_data.get("price")
    stop_loss_price = signal_data.get("stop_loss")
    take_profit_price = signal_data.get("take_profit")
    
    # ... (rest of the validation and parameter building logic) ...
    # This part should be correct from your previous fixes.
    # The important part was adding the quantity_from_signal line above.
    
    if not instrument or (allowed_instruments and instrument not in allowed_instruments):
        error_msg = f"Instrument '{instrument}' is not in the allowed_instruments list."
        return None, error_msg
    if action not in ["buy", "sell"]:
        error_msg = f"Invalid action: '{action}'. Must be 'buy' or 'sell'."
        return None, error_msg

    supported_order_types = ["MARKET", "LIMIT", "STOP"]
    if order_type_from_signal not in supported_order_types:
        error_msg = f"Unsupported order type: '{order_type_from_signal}'. Supported types: {supported_order_types}"
        logger.error(error_msg)
        return None, error_msg

    if order_type_from_signal in ["LIMIT", "STOP"]:
        if not isinstance(trigger_price, (int, float)) or trigger_price <= 0:
            error_msg = f"Invalid or missing 'price' for {order_type_from_signal} order. Received: {trigger_price}"
            logger.error(error_msg)
            return None, error_msg

    if stop_loss_price is not None:
        if not isinstance(stop_loss_price, (int, float)) or stop_loss_price <= 0:
            error_msg = f"Invalid 'stop_loss' price provided: {stop_loss_price}"
            logger.error(error_msg)
            return None, error_msg
    
    if take_profit_price is not None:
        if not isinstance(take_profit_price, (int, float)) or take_profit_price <= 0:
            error_msg = f"Invalid 'take_profit' price provided: {take_profit_price}"
            logger.error(error_msg)
            return None, error_msg

    final_quantity = quantity_from_signal
    if final_quantity is None:
        instr_specific_qty = config_get(f'trading.instrument_settings.{instrument}.default_quantity')
        final_quantity = instr_specific_qty if instr_specific_qty is not None else global_default_quantity
    if not isinstance(final_quantity, (int, float)) or final_quantity <= 0:
        error_msg = f"Invalid quantity: {final_quantity}. Must be a positive number."
        return None, error_msg
        
    min_qty = config_get(f'trading.instrument_settings.{instrument}.min_quantity')
    max_qty = config_get(f'trading.instrument_settings.{instrument}.max_quantity')
    if min_qty is not None and final_quantity < min_qty:
        error_msg = f"Quantity {final_quantity} for {instrument} is below minimum allowed ({min_qty})."
        return None, error_msg
    if max_qty is not None and final_quantity > max_qty:
        error_msg = f"Quantity {final_quantity} for {instrument} exceeds maximum allowed ({max_qty})."
        return None, error_msg

    units = final_quantity if action == "buy" else -final_quantity

    trade_parameters = {
        "instrument": instrument,
        "units": units,
        "order_type": order_type_from_signal
    }

    if trade_parameters["order_type"] in ["LIMIT", "STOP"]:
        trade_parameters["price"] = trigger_price
    
    if stop_loss_price is not None:
        trade_parameters["stop_loss"] = stop_loss_price
    
    if take_profit_price is not None:
        trade_parameters["take_profit"] = take_profit_price
    
    logger.info(f"Processed trade parameters: {trade_parameters}")
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