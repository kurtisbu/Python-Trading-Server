# src/webhook_server/server.py
from flask import Flask, request, jsonify
import logging
import os
import sys
import json # Ensure json is imported if not already for json.loads

# --- Python Path Adjustment ---
# ... (as before) ...
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)
project_root_dir = os.path.dirname(src_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
if project_root_dir not in sys.path:
    sys.path.insert(0, project_root_dir)
# --- End Path Adjustment ---

from config.loader import initialize_config, get as config_get
initialize_config() 

from signal_processor.processor import process_signal
from broker_interface.oanda_client import place_market_order, check_oanda_connection
from order_management.manager import (
    create_order_record, 
    update_order_with_submission_response,
    get_order_by_id,
    get_all_orders,
    initialize_database as initialize_order_db
)

# Remove HMAC specific imports if you are not keeping that code path
# import hmac 
# import hashlib

LOGGING_LEVEL = config_get('logging.level', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOGGING_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

WEBHOOK_SHARED_SECRET = config_get("WEBHOOK_SHARED_SECRET") 

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    logger.info("Webhook endpoint hit.")
    internal_order_id = None 

    # --- Shared Secret in Payload Verification ---
    # Ensure this check happens before extensive processing
    if not request.is_json:
        raw_data = request.get_data(as_text=True) # Get raw data for logging if not JSON
        logger.warning(f"Received non-JSON data: {raw_data}")
        return jsonify({"status": "error", "message": "Request was not JSON"}), 400

    signal_data = request.get_json() # Parse JSON payload

    if WEBHOOK_SHARED_SECRET: # Only check if a secret is configured on the server
        received_payload_secret = signal_data.get("webhook_secret")
        if received_payload_secret != WEBHOOK_SHARED_SECRET:
            logger.warning(f"Invalid or missing webhook_secret in payload. Expected: '{WEBHOOK_SHARED_SECRET[:4]}...', Received: {received_payload_secret}")
            return jsonify({"status": "error", "message": "Unauthorized: Invalid webhook secret in payload"}), 403 # Forbidden
        logger.info("Webhook secret in payload verified successfully.")
    elif not WEBHOOK_SHARED_SECRET:
        logger.info("No WEBHOOK_SHARED_SECRET configured on server, proceeding without payload secret check.")
    # --- End Shared Secret in Payload Verification ---

    logger.info(f"Received authenticated JSON signal: {signal_data}")

    # ... (rest of your signal processing, order creation, and Oanda interaction logic) ...
    # This part remains the same as your last fully working version:
    trade_params, signal_proc_error_msg = process_signal(signal_data)

    if signal_proc_error_msg:
        logger.error(f"Signal processing failed: {signal_proc_error_msg}")
        return jsonify({
            "status": "error", 
            "message": f"Signal processing error: {signal_proc_error_msg}", 
            "signal_data": signal_data
        }), 400

    if not trade_params:
        logger.error("Signal processing returned no parameters and no error message.")
        return jsonify({"status": "error", "message": "Internal error in signal processing.", "signal_data": signal_data}), 500

    logger.info(f"Signal processed successfully. Trade parameters: {trade_params}")

    try:
        internal_order_id = create_order_record(signal_data, trade_params)
        logger.info(f"Created initial order record with ID: {internal_order_id}")
    except Exception as e:
        logger.critical(f"Failed to create order record: {e}", exc_info=True)
        return jsonify({
            "status": "error", 
            "message": "Failed to create internal order record.", "details": str(e),
            "signal_data": signal_data, "trade_parameters": trade_params
        }), 500

    oanda_response = None
    oanda_error_msg = None
    try:
        instrument = trade_params.get("instrument")
        units = trade_params.get("units")

        if not instrument or units is None:
            err_msg = "Internal error: Missing instrument or units after processing."
            logger.error(f"{err_msg} Params: {trade_params}")
            if internal_order_id: update_order_with_submission_response(internal_order_id, oanda_error=err_msg)
            return jsonify({"status": "error", "message": err_msg, "internal_order_id": internal_order_id}), 500

        oanda_response, oanda_error_msg = place_market_order(instrument=instrument, units=units)
        if internal_order_id: update_order_with_submission_response(internal_order_id, oanda_response, oanda_error_msg)

        if oanda_error_msg:
            logger.error(f"Oanda order placement failed for internal ID {internal_order_id}: {oanda_error_msg}")
            return jsonify({
                "status": "error", "message": "Oanda order placement failed.",
                "oanda_error": oanda_error_msg, "internal_order_id": internal_order_id,
                "broker_response": oanda_response 
            }), 500 

        logger.info(f"Oanda order placed/attempted successfully for internal ID {internal_order_id}. Response: {oanda_response}")
        return jsonify({
            "status": "success", "message": "Trade signal processed and order submitted to Oanda.",
            "internal_order_id": internal_order_id, "oanda_response": oanda_response 
        }), 200

    except Exception as e:
        critical_err_msg = f"Unexpected error during trade execution or final update for internal ID {internal_order_id}: {e}"
        logger.critical(critical_err_msg, exc_info=True)
        if internal_order_id: update_order_with_submission_response(internal_order_id, oanda_error=critical_err_msg)
        return jsonify({"status": "error", "message": "An unexpected server error occurred.", "internal_order_id": internal_order_id}), 500

# ... (rest of server.py: /health, /orders, if __name__ == '__main__') ...
# Ensure if __name__ == '__main__' block calls initialize_order_db() and check_oanda_connection()
# and app.run() using config_get for host and port as before.
@app.route('/health', methods=['GET'])
def health_check():
    logger.info("Health check endpoint hit.")
    return jsonify({"status": "ok", "message": "Webhook server is running."}), 200

@app.route('/orders', methods=['GET'])
def list_orders():
    logger.info("Request to list all orders.")
    all_orders_data = get_all_orders()
    return jsonify({"status": "success", "orders": all_orders_data}), 200

@app.route('/orders/<string:order_id>', methods=['GET'])
def get_specific_order(order_id):
    logger.info(f"Request to get order with ID: {order_id}")
    order_data = get_order_by_id(order_id)
    if order_data:
        return jsonify({"status": "success", "order": order_data}), 200
    else:
        return jsonify({"status": "error", "message": "Order not found", "internal_order_id": order_id}), 404

if __name__ == '__main__':
    try:
        logger.info("Initializing Order Management Database...")
        initialize_order_db()
        logger.info("Order Management Database initialized successfully.")
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to initialize Order Management Database: {e}. Server might not function correctly.", exc_info=True)

    if check_oanda_connection():
        logger.info("Initial Oanda connection check successful (using config for URL).")
    else:
        logger.warning("Initial Oanda connection check FAILED.")

    server_host = config_get('webhook_server.host', '0.0.0.0')
    server_port = config_get('webhook_server.port', 5000)
    logger.info(f"Starting Flask development server for webhook on host {server_host} port {server_port}...")
    # For production, debug should be False and use a proper WSGI server.
    app.run(host=server_host, port=server_port, debug=True)