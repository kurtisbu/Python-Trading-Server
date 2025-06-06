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

# --- Imports ---
from config.loader import initialize_config, get as config_get
from broker_interface import get_broker
from signal_processor.processor import process_signal
from order_management.manager import (
    create_order_record, update_order_with_submission_response,
    get_order_by_id, get_all_orders, initialize_database as initialize_order_db
)

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
    try:
        order_type = trade_params.get("order_type")
        instrument = trade_params.get("instrument")
        units = trade_params.get("units")
        if order_type == "MARKET":
            broker_response, broker_error = broker.place_market_order(instrument=instrument, units=units)
        elif order_type == "LIMIT":
            price = trade_params.get("price")
            broker_response, broker_error = broker.place_limit_order(instrument=instrument, units=units, price=price)
        else:
            broker_error = f"Unknown order type '{order_type}'"
            broker_response = None
        update_order_with_submission_response(internal_order_id, broker_response, broker_error)
        if broker_error:
            return jsonify({"status": "error", "message": "Broker error", "broker_error": broker_error}), 500
        return jsonify({"status": "success", "internal_order_id": internal_order_id, "broker_response": broker_response}), 200
    except Exception as e:
        logger.critical(f"Unexpected error during trade execution for ID {internal_order_id}: {e}", exc_info=True)
        update_order_with_submission_response(internal_order_id, oanda_error=str(e))
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