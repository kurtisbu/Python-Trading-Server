# dashboard.py
import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- Configuration ---
TRADING_SERVER_URL = "http://localhost:5000"

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

def post_data(endpoint: str):
    """Sends a POST request to a given API endpoint."""
    try:
        response = requests.post(f"{TRADING_SERVER_URL}/{endpoint}")
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


# --- NEW: Section for Pending Orders with Cancel Buttons ---
st.subheader("🔔 Pending Orders")

# Fetch all orders to find the pending ones
orders_data = fetch_data("orders")
if orders_data and orders_data.get("status") == "success":
    all_orders = pd.DataFrame(orders_data.get("orders", []))
    
    if not all_orders.empty:
        # Filter for orders that can be cancelled (e.g., status is 'ORDER_ACCEPTED')
        cancelable_stuses = ["ORDER_ACCEPTED"] # You can add other statuses here if needed
        pending_orders = all_orders[all_orders['status'].isin(cancelable_stuses)]

        if not pending_orders.empty:
            # Display each pending order with a cancel button
            for index, order in pending_orders.iterrows():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
                with col1:
                    st.text(
                        f"{order.get('instrument', 'N/A')} "
                        f"({order.get('processed_params', {}).get('units', 'N/A')})"
                    )
                with col2:
                    st.text(f"Type: {order.get('processed_params', {}).get('order_type', 'N/A')}")
                with col3:
                    limit_price = order.get('processed_params', {}).get('price', 'N/A')
                    st.text(f"Price: {limit_price}")
                with col4:
                    # The 'key' is CRITICAL. It must be unique for each button.
                    if st.button("Cancel Order", key=order['internal_order_id']):
                        st.write(f"Cancelling order {order['internal_order_id']}...")
                        
                        # Make the API call to our server's cancel endpoint
                        cancel_response = post_data(f"orders/{order['internal_order_id']}/cancel")
                        
                        if cancel_response and cancel_response.get("status") == "success":
                            st.success("✅ Order cancelled successfully!")
                        else:
                            error_msg = cancel_response.get("message", "Unknown error")
                            st.error(f"❌ Failed to cancel order: {error_msg}")
                        
                        # Clear cache and rerun the script to see the updated status
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