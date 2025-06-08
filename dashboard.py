import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import os # <-- Add this import

# --- Configuration ---
# Define the base URL of your trading server's API
# It will use the API_URL from the environment (set in docker-compose)
# and fall back to localhost if it's not set (for local development).
TRADING_SERVER_URL = os.getenv("API_URL", "http://localhost:5000") # <-- Change this line

# --- Page Setup ---
st.set_page_config(
    page_title="Trading Server Dashboard",
    page_icon="🤖",
    layout="wide"
)

# --- Data Fetching Functions ---
# Use Streamlit's cache to avoid re-fetching data on every single interaction
@st.cache_data(ttl=10)
def fetch_data(endpoint: str):
    """Fetches data from a given API endpoint."""
    try:
        response = requests.get(f"{TRADING_SERVER_URL}/{endpoint}")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        # We'll display errors in the main app body, so just return None here
        return None

def post_data(endpoint: str, payload: dict = None):
    """Sends a POST request to a given API endpoint, with an optional JSON payload."""
    try:
        # Use the json parameter to send a payload
        response = requests.post(f"{TRADING_SERVER_URL}/{endpoint}", json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"Error connecting to server: {e}"}


# --- Main Application ---
st.title("📈 Trading Server Dashboard")

# A button to force a refresh of all data on the page
if st.button("Force Refresh All Data"):
    st.cache_data.clear()
    st.rerun()

st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.divider()


st.subheader("Manual Order Placement")

# This is a placeholder for instrument choices. We could fetch these from config later.
instrument_choices = ["EUR_USD", "USD_JPY", "GBP_USD", "AAPL", "TSLA", "GOOGL"]

with st.form("new_order_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        instrument = st.selectbox("Instrument", options=instrument_choices)
        action = st.selectbox("Action", options=["buy", "sell"])
    with col2:
        quantity = st.number_input("Quantity", min_value=0.0, step=1.0, format="%.2f")
        order_type = st.selectbox("Order Type", options=["MARKET", "LIMIT", "STOP"])
    with col3:
        # Conditionally show the price input only for LIMIT or STOP orders
        price = 0.0
        if order_type in ["LIMIT", "STOP"]:
            price = st.number_input(f"{order_type} Price", min_value=0.0, step=0.0001, format="%.4f")

    # A submit button for the form
    submitted = st.form_submit_button("Place Order")

    if submitted:
        if quantity <= 0:
            st.error("Quantity must be greater than zero.")
        else:
            st.write(f"Submitting {action} {quantity} of {instrument}...")

            # Construct the payload for the new /orders endpoint
            order_payload = {
                "instrument": instrument,
                "action": action,
                "quantity": quantity,
                "type": order_type.lower() # API expects lowercase
            }
            if order_type in ["LIMIT", "STOP"]:
                order_payload["price"] = price

            # Send the data to the new endpoint
            response = post_data("orders", payload=order_payload)

            if response and response.get("status") == "success":
                st.success(f"✅ Order submitted successfully! Internal ID: {response.get('internal_order_id')}")
                # Clear the data cache to force a refresh on the tables below
                st.cache_data.clear()
            else:
                error_msg = response.get("broker_error") or response.get("message", "Unknown error")
                st.error(f"❌ Failed to place order: {error_msg}")

st.divider()

# --- NEW: Section for Pending Orders with Cancel Buttons ---
st.subheader("🔔 Pending Orders")

# Fetch all orders to find the pending ones
orders_data = fetch_data("orders")
if orders_data and orders_data.get("status") == "success":
    all_orders = pd.DataFrame(orders_data.get("orders", []))

    if not all_orders.empty:
        # Filter for orders that can be cancelled (e.g., status is 'ORDER_ACCEPTED')
        cancelable_statuses = ["ORDER_ACCEPTED"] 
        pending_orders = all_orders[all_orders['status'].isin(cancelable_statuses)]

        if not pending_orders.empty:
            # Display each pending order with a cancel button
            for index, order in pending_orders.iterrows():
                # --- THIS IS THE CORRECTED LOGIC ---
                processed_params = order.get('processed_params', {})
                instrument = processed_params.get('instrument', 'N/A')
                units = processed_params.get('units', 'N/A')
                order_type = processed_params.get('order_type', 'N/A')
                price = processed_params.get('price', 'N/A')
                # --- END OF CORRECTION ---

                col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
                with col1:
                    st.text(f"{instrument} ({units})") # This will now show the correct info
                with col2:
                    st.text(f"Type: {order_type}")
                with col3:
                    st.text(f"Price: {price}") # This will now show the correct info
                with col4:
                    if st.button("Cancel Order", key=order['internal_order_id']):
                        st.write(f"Cancelling order {order['internal_order_id']}...")
                        cancel_response = post_data(f"orders/{order['internal_order_id']}/cancel")

                        if cancel_response and cancel_response.get("status") == "success":
                            st.success("✅ Order cancelled successfully!")
                        else:
                            error_msg = cancel_response.get("message", "Unknown error")
                            st.error(f"❌ Failed to cancel order: {error_msg}")

                        st.cache_data.clear()
                        st.rerun()
        else:
            st.info("No pending orders to cancel.")
    else:
        st.info("No orders found in history.")
else:
    st.warning("Could not fetch order data. Is the trading server running?")

st.divider()


# --- Combined Display for Positions and Order History ---
pos_col, ord_col = st.columns(2)

with pos_col:
    st.subheader("📊 Positions")
    positions_data = fetch_data("positions")
    if positions_data and positions_data.get("status") == "success":
        positions = positions_data.get("positions", {})
        if positions:
            position_df = pd.DataFrame(list(positions.items()), columns=['Instrument', 'Net Position'])
            st.dataframe(position_df, use_container_width=True)
        else:
            st.info("No open positions.")
    else:
        st.warning("Could not fetch position data.")

with ord_col:
    st.subheader("📋 Full Order History")
    # We already fetched this data for the pending orders section, so it's cached
    if orders_data and orders_data.get("status") == "success" and not all_orders.empty:
        display_columns = [
            "timestamp_created", "instrument", "status",
            "processed_params", "fill_price", "fill_quantity",
            "error_message", "internal_order_id",
        ]
        existing_display_columns = [col for col in display_columns if col in all_orders.columns]
        st.dataframe(all_orders[existing_display_columns], use_container_width=True, height=400)
    else:
        st.info("No orders found in history.")