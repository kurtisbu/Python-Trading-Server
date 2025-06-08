# src/webhook_server/server.py
import sys
import os
# Get the absolute path of the 'src' directory
SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Add it to the beginning of the Python path
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import logging
import json
import os
import sys
from flask import Flask, request, jsonify
import yaml
from config.loader import initialize_config, get as config_get
from broker_interface import get_broker
from signal_processor.processor import process_signal
from order_management.manager import (
    create_order_record, update_order_with_submission_response,
    get_order_by_id, get_all_orders, initialize_database as initialize_order_db
)
from position_management.manager import get_position, get_all_positions
# --- App and Config Initialization ---
initialize_config()
app = Flask(__name__)
LOGGING_LEVEL = config_get('logging.level', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOGGING_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
WEBHOOK_SHARED_SECRET = config_get("WEBHOOK_SHARED_SECRET")

# --- Global Broker Instance ---
# Define the variable but initialize it as None.
# This makes the module safe to import for testing.
broker = None

# --- Route Definitions ---

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    # This check ensures the broker has been initialized before use.
    if not broker:
        logger.error("CRITICAL: Broker is not initialized. Cannot process trade.")
        return jsonify({"status": "error", "message": "Critical Server Error: Broker not initialized"}), 500

    # ... (The rest of your webhook logic here remains unchanged) ...
    # This part should be identical to your last working version.
    if not request.is_json:
        return jsonify({"status": "error", "message": "Request was not JSON"}), 400
    signal_data = request.get_json()
    if WEBHOOK_SHARED_SECRET and signal_data.get("webhook_secret") != WEBHOOK_SHARED_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized: Invalid webhook secret"}), 403
    trade_params, signal_proc_error_msg = process_signal(signal_data)
    if signal_proc_error_msg:
        return jsonify({"status": "error", "message": f"Signal error: {signal_proc_error_msg}"}), 400
    internal_order_id = create_order_record(signal_data, trade_params)
    broker_response = None
    broker_error = None
    try:
        # Extract all potential parameters from the processed signal
        order_type = trade_params.get("order_type")
        instrument = trade_params.get("instrument")
        units = trade_params.get("units")
        price = trade_params.get("price") # For LIMIT/STOP orders
        stop_loss = trade_params.get("stop_loss") # NEW
        take_profit = trade_params.get("take_profit") # NEW

        if not all([order_type, instrument, units is not None]):
            err_msg = "Internal error: Missing order_type, instrument, or units after processing."
            # ... (error handling as before) ...
            return jsonify({"status": "error", "message": err_msg, "internal_order_id": internal_order_id}), 500

        # --- Updated Order Routing Logic ---
        if order_type == "MARKET":
            logger.info(f"Routing to place_market_order for internal ID {internal_order_id} with SL/TP.")
            broker_response, broker_error = broker.place_market_order(
                instrument=instrument,
                units=units,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
        elif order_type == "LIMIT":
            if not price:
                # ... (error handling as before) ...
                return jsonify({"status": "error", "message": "Internal error: Missing price for LIMIT order"}), 500
            logger.info(f"Routing to place_limit_order for internal ID {internal_order_id} with SL/TP.")
            broker_response, broker_error = broker.place_limit_order(
                instrument=instrument,
                units=units,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
        elif order_type == "STOP":
            if not price:
                # ... (error handling as before) ...
                return jsonify({"status": "error", "message": "Internal error: Missing price for STOP order"}), 500
            logger.info(f"Routing to place_stop_order for internal ID {internal_order_id} with SL/TP.")
            broker_response, broker_error = broker.place_stop_order(
                instrument=instrument,
                units=units,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
        else:
            broker_error = f"Unknown order type '{order_type}' cannot be routed."
            broker_response = None
        # --- END of Updated Logic ---

        # ... (The rest of the function for handling the response and errors remains the same) ...
        update_order_with_submission_response(internal_order_id, broker_response, broker_error)
        if broker_error:
            return jsonify({"status": "error", "message": "Broker error", "broker_error": broker_error}), 500
        return jsonify({"status": "success", "internal_order_id": internal_order_id, "broker_response": broker_response}), 200

    except Exception as e:
        logger.critical(f"Unexpected error during trade execution for ID {internal_order_id}: {e}", exc_info=True)
        update_order_with_submission_response(internal_order_id, oanda_error=str(e))
        return jsonify({"status": "error", "message": "An unexpected server error occurred"}), 500


@app.route('/orders', methods=['POST'])
def create_manual_order():
    """
    API endpoint for creating a new order manually, e.g., from a GUI.
    This takes a structured JSON payload and processes it like a webhook signal.
    """
    logger.info("Received request to create a manual order.")

    if not broker:
        logger.error("CRITICAL: Broker is not initialized. Cannot process trade.")
        return jsonify({"status": "error", "message": "Critical Server Error: Broker not initialized"}), 500

    signal_data = request.get_json()
    if not signal_data:
        return jsonify({"status": "error", "message": "No JSON payload received."}), 400

    # --- This logic is nearly identical to the webhook handler ---
    # 1. Process the signal
    trade_params, signal_proc_error_msg = process_signal(signal_data)
    if signal_proc_error_msg:
        return jsonify({"status": "error", "message": f"Signal error: {signal_proc_error_msg}"}), 400

    # 2. Create the internal order record
    internal_order_id = create_order_record(signal_data, trade_params)
    if not internal_order_id:
         return jsonify({"status": "error", "message": "Failed to create internal order record."}), 500

    # 3. Route the order to the broker
    try:
        order_type = trade_params.get("order_type")
        instrument = trade_params.get("instrument")
        units = trade_params.get("units")
        price = trade_params.get("price")
        stop_loss = trade_params.get("stop_loss")
        take_profit = trade_params.get("take_profit")

        if order_type == "MARKET":
            broker_response, broker_error = broker.place_market_order(instrument, units, stop_loss, take_profit)
        elif order_type == "LIMIT":
            broker_response, broker_error = broker.place_limit_order(instrument, units, price, stop_loss, take_profit)
        elif order_type == "STOP":
            broker_response, broker_error = broker.place_stop_order(instrument, units, price, stop_loss, take_profit)
        else:
            broker_error = f"Unknown order type '{order_type}'"
            broker_response = None

        update_order_with_submission_response(internal_order_id, broker_response, broker_error)

        if broker_error:
            return jsonify({"status": "error", "message": "Broker error", "broker_error": broker_error, "broker_response": broker_response}), 400

        return jsonify({"status": "success", "message": "Order submitted successfully.", "internal_order_id": internal_order_id, "broker_response": broker_response}), 201 # 201 Created

    except Exception as e:
        logger.critical(f"Unexpected error during manual order execution for ID {internal_order_id}: {e}", exc_info=True)
        update_order_with_submission_response(internal_order_id, oanda_error=str(e)) # Note: key is 'oanda_error'
        return jsonify({"status": "error", "message": "An unexpected server error occurred"}), 500



# The health check can stay, it's a simple route.
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Webhook server is running."}), 200

# The orders routes can also stay.
@app.route('/orders', methods=['GET'])
def list_orders():
    return jsonify({"status": "success", "orders": get_all_orders()}), 200

@app.route('/orders/<string:order_id>', methods=['GET'])
def get_specific_order(order_id):
    order = get_order_by_id(order_id)
    if order:
        return jsonify({"status": "success", "order": order}), 200
    else:
        return jsonify({"status": "error", "message": "Order not found"}), 404

@app.route('/orders/<string:internal_order_id>/cancel', methods=['POST'])
def cancel_specific_order(internal_order_id):
    """
    API endpoint to cancel a specific pending order.
    """
    logger.info(f"Received request to cancel order with internal ID: {internal_order_id}")

    if not broker:
        logger.error("CRITICAL: Broker is not initialized. Cannot process cancellation.")
        return jsonify({"status": "error", "message": "Critical Server Error: Broker not initialized"}), 500

    # 1. Fetch our internal record of the order
    order_to_cancel = get_order_by_id(internal_order_id)
    if not order_to_cancel:
        logger.warning(f"Cancellation failed: No order found with internal ID {internal_order_id}")
        return jsonify({"status": "error", "message": "Order not found"}), 404

    # 2. Validate that the order can be cancelled
    oanda_order_id = order_to_cancel.get("oanda_order_id")
    if not oanda_order_id:
        msg = "Cancellation failed: Order has no broker-assigned ID (it may have failed on initial submission)."
        logger.error(msg)
        return jsonify({"status": "error", "message": msg}), 400

    cancelable_stuses = ["ORDER_ACCEPTED", "PENDING_FILL"] # Define states that can be cancelled
    if order_to_cancel.get("status") not in cancelable_stuses:
        msg = f"Cancellation failed: Order is not in a cancelable state. Current status: {order_to_cancel.get('status')}"
        logger.warning(msg)
        return jsonify({"status": "error", "message": msg}), 400 # 400 Bad Request or 409 Conflict

    # 3. Call the broker to cancel the order
    cancellation_response, broker_error = broker.cancel_order(oanda_order_id)

    # 4. Update our internal record with the result
    # The update_order_with_submission_response function already knows how to handle
    # an orderCancelTransaction from the broker, so we can reuse it.
    update_order_with_submission_response(internal_order_id, cancellation_response, broker_error)

    if broker_error:
        logger.error(f"Broker failed to cancel order {oanda_order_id}: {broker_error}")
        return jsonify({
            "status": "error",
            "message": "Broker returned an error during cancellation.",
            "broker_error": broker_error
        }), 500

    logger.info(f"Successfully processed cancellation for order {internal_order_id}")
    return jsonify({
        "status": "success",
        "message": f"Cancellation request for order {internal_order_id} processed.",
        "broker_response": cancellation_response
    }), 200

@app.route('/positions', methods=['GET'])
def list_all_positions():
    """
    API endpoint to retrieve all non-flat portfolio positions.
    """
    logger.info("Request to list all current positions.")
    try:
        all_positions = get_all_positions()
        return jsonify({
            "status": "success",
            "positions": all_positions
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving all positions: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An error occurred while retrieving positions."}), 500


@app.route('/positions/<string:instrument_name>', methods=['GET'])
def get_instrument_position(instrument_name):
    """
    API endpoint to retrieve the net position for a specific instrument.
    """
    # Instrument names can contain underscores, so they are valid URL parts.
    # We'll sanitize it by converting to uppercase to match our internal format.
    instrument_sanitized = instrument_name.upper()
    logger.info(f"Request for position of instrument: {instrument_sanitized}")

    try:
        net_position = get_position(instrument_sanitized)
        return jsonify({
            "status": "success",
            "instrument": instrument_sanitized,
            "net_position": net_position
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving position for {instrument_sanitized}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An error occurred while retrieving position."}), 500



@app.route('/config', methods=['GET'])
def get_config():
    """API endpoint to fetch the current application configuration."""
    logger.info("Request to fetch configuration.")
    try:
        # We use the config_get from our loader, which holds the loaded config in memory.
        # This is safer than reading the file directly each time.
        # The loader's internal '_config' variable holds the YAML part.
        from config.loader import _config as current_config
        if current_config:
            return jsonify({"status": "success", "config": current_config}), 200
        else:
            return jsonify({"status": "error", "message": "Configuration not loaded."}), 500
    except Exception as e:
        logger.error(f"Error fetching configuration: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An error occurred while fetching configuration."}), 500


@app.route('/config', methods=['POST'])
def update_config():
    """API endpoint to update and save the application configuration."""
    logger.info("Request to update configuration.")

    new_config_data = request.get_json()
    if not new_config_data:
        return jsonify({"status": "error", "message": "No JSON payload received."}), 400

    try:
        # IMPORTANT: In a real production app, you would add extensive validation here
        # to ensure the new configuration is valid before saving. For now, we'll save it directly.

        # Get the path to config.yaml from our config loader
        from config.loader import CONFIG_FILE_PATH

        # Write the new configuration to the config.yaml file
        with open(CONFIG_FILE_PATH, 'w') as f:
            yaml.dump(new_config_data, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Configuration successfully saved to {CONFIG_FILE_PATH}")

        # Now, tell the running application to reload its configuration
        from config.loader import initialize_config
        initialize_config(force_reload=True) # We need to add 'force_reload' to our loader

        # You might need to re-initialize other components that depend on config at startup,
        # like the broker instance. This is an advanced topic (service reloading).
        # For now, we will notify the user that a restart might be needed for some changes.

        return jsonify({
            "status": "success",
            "message": "Configuration saved. Some changes may require a server restart to take full effect."
        }), 200

    except Exception as e:
        logger.error(f"Error updating configuration: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An error occurred while updating configuration."}), 500


# --- Main Execution Block ---

if __name__ == '__main__':
    initialize_order_db()
    
    # Instantiate the REAL broker only when running the server directly.
    try:
        # This assignment correctly modifies the module-level 'broker' variable
        broker = get_broker() 
        if broker.check_connection()[0]:
            logger.info("Initial broker connection check successful.")
        else:
            logger.warning("Initial broker connection check FAILED.")
    except Exception as e:
        logger.critical(f"CRITICAL: Could not start application. Failed to initialize broker: {e}", exc_info=True)
        sys.exit(1)

    # Run the Flask app
    server_host = config_get('webhook_server.host', '0.0.0.0')
    server_port = config_get('webhook_server.port', 5000)
    app.run(host=server_host, port=server_port, debug=True)