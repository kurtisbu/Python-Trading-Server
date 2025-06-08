# pages/1_⚙️_Settings.py
import streamlit as st
import requests
import yaml # We need yaml to display the config nicely
import os
import json

# --- Configuration and Helper Functions ---
TRADING_SERVER_URL = os.getenv("API_URL", "http://localhost:5000")

def fetch_config():
    """Fetches the current config from the server."""
    try:
        response = requests.get(f"{TRADING_SERVER_URL}/config")
        response.raise_for_status()
        return response.json().get("config", {})
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching config: {e}")
        return None

def update_config(new_config_data: dict):
    """Sends the updated config to the server."""
    try:
        response = requests.post(f"{TRADING_SERVER_URL}/config", json=new_config_data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"Error saving config: {e}"}

# --- Page Rendering ---
st.set_page_config(page_title="Server Settings", layout="wide")
st.title("⚙️ Server Settings")

st.info("Changes to some settings (like the active broker) may require a server restart to take full effect.", icon="ℹ️")

# Load the config into session state to preserve edits across interactions
if 'config' not in st.session_state:
    st.session_state.config = fetch_config()

config = st.session_state.config

if not config:
    st.error("Could not load configuration from the server. Is it running?")
else:
    # Create a form to group all inputs and have a single save button
    with st.form("settings_form"):

        # --- Broker Settings ---
        with st.expander("Broker Configuration", expanded=True):
            # Get the current active broker name
            active_broker = config.get("broker", {}).get("name", "oanda")

            # Get a list of available brokers from the config structure
            available_brokers = list(config.get("brokers", {}).keys())

            # Find the index of the current active broker for the selectbox default
            try:
                active_broker_index = available_brokers.index(active_broker)
            except ValueError:
                active_broker_index = 0

            # Use a selectbox to choose the active broker
            new_active_broker = st.selectbox(
                "Active Broker",
                options=available_brokers,
                index=active_broker_index,
                help="Select the broker to use for trading. Requires server restart."
            )
            config["broker"]["name"] = new_active_broker

        # --- Trading Settings ---
        with st.expander("Trading Defaults"):
            st.write("These settings control default trade parameters.")

            trading_config = config.get("trading", {})

            # Edit allowed instruments
            # Easiest way in UI is a text area, one instrument per line
            allowed_instruments_list = trading_config.get("allowed_instruments", [])
            allowed_instruments_str = "\n".join(allowed_instruments_list)

            new_allowed_instruments_str = st.text_area(
                "Allowed Instruments (one per line)",
                value=allowed_instruments_str,
                height=150
            )
            # Convert back to list, removing empty lines
            config["trading"]["allowed_instruments"] = [
                line.strip() for line in new_allowed_instruments_str.split("\n") if line.strip()
            ]

            # Edit default quantity
            default_qty = trading_config.get("defaults", {}).get("quantity", 1)
            config["trading"]["defaults"]["quantity"] = st.number_input(
                "Default Trade Quantity",
                min_value=1,
                value=default_qty
            )

        # --- Save Button ---
        submitted = st.form_submit_button("Save Configuration")
        if submitted:
            st.write("Saving configuration...")
            save_response = update_config(config)

            if save_response and save_response.get("status") == "success":
                st.success(f"✅ Configuration saved! {save_response.get('message')}")
                # Clear the cached config in session state to force a re-fetch on rerun
                del st.session_state.config
                st.rerun()
            else:
                error_msg = save_response.get("message", "Unknown error")
                st.error(f"❌ Failed to save configuration: {error_msg}")

# Add a section to view the raw YAML for verification
st.subheader("Raw `config.yaml` Content")
with st.expander("Click to view raw file"):
    # Use st.code to display the config dictionary as nicely formatted YAML
    st.code(yaml.dump(config), language='yaml')