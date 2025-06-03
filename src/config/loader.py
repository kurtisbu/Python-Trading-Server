# src/config/loader.py
import yaml
import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# --- Determine Project Root and Paths ---
# This assumes loader.py is in src/config/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT_DIR = os.path.dirname(SRC_DIR)

DEFAULT_CONFIG_FILENAME = "config.yaml"
ENV_FILENAME = ".env"

CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT_DIR, DEFAULT_CONFIG_FILENAME)
ENV_FILE_PATH = os.path.join(PROJECT_ROOT_DIR, ENV_FILENAME)
# --- End Path Definitions ---

_config = None
_env_vars = {}

def _load_yaml_config(config_path):
    """Loads the YAML configuration file."""
    try:
        with open(config_path, 'r') as stream:
            return yaml.safe_load(stream)
    except FileNotFoundError:
        logger.warning(f"YAML configuration file not found at: {config_path}. Using defaults or .env only.")
        return {}
    except yaml.YAMLError as exc:
        logger.error(f"Error parsing YAML configuration file {config_path}: {exc}", exc_info=True)
        # Depending on strictness, you might want to raise an exception here
        # or return an empty dict / fallback to defaults.
        return {} # Or raise

def _load_env_vars(env_path):
    """
    Loads .env file and returns a dictionary of relevant environment variables.
    We use override=True to ensure .env takes precedence over system-set vars for consistency.
    """
    original_env = dict(os.environ) # Store original system env
    load_dotenv(dotenv_path=env_path, override=True)

    loaded_vars = {}
    # Explicitly list the .env variables we care about for our app config
    # This helps avoid polluting the config with all system env vars.
    # And ensures secrets are handled intentionally.
    env_keys_to_capture = [
        "OANDA_API_KEY", 
        "OANDA_ACCOUNT_ID",
        "WEBHOOK_SHARED_SECRET",
        "OANDA_API_URL" # If you decide to keep this in .env for easy override
    ]
    for key in env_keys_to_capture:
        value = os.getenv(key)
        if value is not None:
            loaded_vars[key] = value

    # Restore original environment if you want to strictly isolate .env loading
    # For most cases this isn't strictly necessary if override=True is used carefully.
    # os.environ.clear()
    # os.environ.update(original_env)
    return loaded_vars

def _merge_configs(yaml_conf, env_conf):
    """
    Merges configurations. For simplicity, env_conf can provide values 
    that might be referenced or directly used.
    A more sophisticated merge might place .env vars under specific keys in the config.
    For now, we'll keep them separate and access them distinctly or through helper methods.
    Let's design the get() method to be smart.
    """
    # For now, we're not deeply merging. _config holds YAML, _env_vars holds .env
    # The get() method will decide where to look.
    return yaml_conf # Keep _config as the primarily YAML-loaded structure

def initialize_config(config_path=None, env_path=None):
    """
    Initializes the configuration by loading YAML and .env files.
    This should be called once at application startup.
    """
    global _config, _env_vars

    cfg_path = config_path or CONFIG_FILE_PATH
    e_path = env_path or ENV_FILE_PATH

    if _config is None: # Load only once
        logger.info(f"Initializing configuration from YAML: {cfg_path} and .env: {e_path}")
        _env_vars = _load_env_vars(e_path) # Load .env first
        yaml_data = _load_yaml_config(cfg_path)
        _config = _merge_configs(yaml_data, _env_vars) # For now, merge is just assigning yaml_data

        # Example: If OANDA_API_URL from .env should override one in YAML
        # This shows a more direct merge strategy for specific keys if needed.
        if "oanda" not in _config and "OANDA_API_URL" in _env_vars:
             _config["oanda"] = {} # Ensure section exists
        if "OANDA_API_URL" in _env_vars and _config.get("oanda", {}).get("base_url") != _env_vars["OANDA_API_URL"]:
            logger.info(f"Overriding oanda.base_url from YAML with OANDA_API_URL from .env: '{_env_vars['OANDA_API_URL']}'")
            _config["oanda"]["base_url"] = _env_vars["OANDA_API_URL"]
        elif "oanda" in _config and "base_url" not in _config["oanda"] and "OANDA_API_URL" in _env_vars:
            _config["oanda"]["base_url"] = _env_vars["OANDA_API_URL"]


        logger.info("Configuration initialized.")
        # logger.debug(f"Final effective config (YAML part): {_config}")
        # logger.debug(f"Final effective .env vars captured: {_env_vars}")

    return _config

def get(key_path: str, default=None):
    """
    Retrieves a configuration value using a dot-separated key path.
    e.g., get('trading.defaults.quantity')
    It can also retrieve directly from the loaded .env vars if the key matches.
    """
    if _config is None:
        logger.warning("Config not initialized. Call initialize_config() first.")
        # Initialize on first get() call if not done, for convenience, but explicit init is better.
        initialize_config() 

    # Priority 1: Check if it's a known .env variable (secrets)
    if key_path in _env_vars:
        return _env_vars[key_path]

    # Priority 2: Check in the YAML-loaded config using dot notation
    parts = key_path.split('.')
    value = _config
    try:
        for part in parts:
            if value is None or not isinstance(value, dict): # Check if value is None or not a dict before accessing
                # logger.debug(f"Path '{key_path}' not found, part '{part}' failed. Current value type: {type(value)}")
                return default
            value = value.get(part)

        if value is None: # If the path resolved but the final value is None (explicitly set in YAML)
            # logger.debug(f"Path '{key_path}' resolved to None in YAML.")
            return default if default is not None else None # Return None if explicitly set, unless default is provided
        return value
    except (TypeError, AttributeError) as e: # Should be caught by the isinstance check mostly
        # logger.debug(f"Error accessing config key '{key_path}': {e}. Returning default.")
        return default


# --- Test / Example Usage ---
if __name__ == "__main__":
    # Basic logging for direct script run
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Create a dummy config.yaml for testing in the project root if it doesn't exist
    # Assumes project root is one level up from src/
    test_yaml_path = os.path.join(PROJECT_ROOT_DIR, "config.yaml")
    if not os.path.exists(test_yaml_path):
        logger.info(f"Creating dummy {test_yaml_path} for testing loader.py")
        dummy_yaml_content = """
        test_section:
          greeting: "Hello from YAML!"
          nested:
            value: 123
        trading:
          defaults:
            quantity: 50
        oanda:
          base_url: "https://api.example-yaml.com" # Will be overridden by .env if OANDA_API_URL is set
        """
        with open(test_yaml_path, "w") as f:
            f.write(dummy_yaml_content)

    # Create a dummy .env for testing if it doesn't exist
    test_env_path = os.path.join(PROJECT_ROOT_DIR, ".env")
    if not os.path.exists(test_env_path):
        logger.info(f"Creating dummy {test_env_path} for testing loader.py")
        dummy_env_content = """
        OANDA_API_KEY="yaml_test_api_key_from_env"
        OANDA_ACCOUNT_ID="yaml_test_account_id_from_env"
        WEBHOOK_SHARED_SECRET="yaml_test_webhook_secret_from_env"
        OANDA_API_URL="https://api-fxpractice.oanda.com" # From .env
        OTHER_ENV_VAR="This should not be automatically picked up unless specified"
        """
        with open(test_env_path, "w") as f:
            f.write(dummy_env_content)

    # Initialize (or re-initialize if already called by another module test)
    # For standalone testing, ensure a clean slate for _config and _env_vars
    _config = None
    _env_vars = {}
    initialize_config(config_path=test_yaml_path, env_path=test_env_path)

    print(f"--- Testing Config Loader ---")
    print(f"Greeting: {get('test_section.greeting', 'Default Greeting')}")
    print(f"Nested Value: {get('test_section.nested.value', 0)}")
    print(f"NonExistent: {get('test_section.non_existent.key', 'Not Found')}")
    print(f"Default Quantity (from YAML): {get('trading.defaults.quantity')}")

    print(f"OANDA API Key (from .env): {get('OANDA_API_KEY')}")
    print(f"OANDA Account ID (from .env): {get('OANDA_ACCOUNT_ID')}")
    print(f"Webhook Secret (from .env): {get('WEBHOOK_SHARED_SECRET')}")
    print(f"Oanda Base URL (expect .env override): {get('oanda.base_url')}") # Test .env override

    print(f"Allowed Instruments (from YAML if in dummy config): {get('trading.allowed_instruments', [])}")

    # Test accessing a section
    # trading_config = get('trading')
    # print(f"Full Trading Config Section: {trading_config}")

    # Test that unspecified .env vars are not loaded into general config
    print(f"Other .env var (should be None or default): {get('OTHER_ENV_VAR', 'Not directly accessible via get unless specified in env_keys_to_capture')}")

    # Clean up dummy files if you want
    # os.remove(test_yaml_path)
    # os.remove(test_env_path)