# tests/test_config_loader.py
import pytest
import os
import sys
import yaml # For creating dummy yaml content

# --- Add src directory to Python path for imports ---
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# --- End Path Adjustment ---

# We need to import the module we are testing
from config import loader 

# --- Helper Fixture to Reset Loader State ---
@pytest.fixture(autouse=True) # This fixture will run automatically for every test in this file
def reset_config_loader_state():
    """Resets the internal state of the config loader before each test."""
    loader._config = None
    loader._env_vars = {}
    # If os.environ was modified by _load_env_vars and not restored, 
    # this might be a place to ensure it's clean for tests, but 
    # _load_env_vars as written should be mostly okay.
    # A more robust way for _load_env_vars would be to use monkeypatch for os.getenv

# --- Test Cases ---

def test_load_yaml_config_valid_file(tmp_path):
    """Tests loading a valid YAML file."""
    dummy_yaml_content = {
        "webhook_server": {"port": 5001},
        "trading": {"defaults": {"quantity": 75}}
    }
    config_file = tmp_path / "test_config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(dummy_yaml_content, f)

    loaded_data = loader._load_yaml_config(str(config_file))
    assert loaded_data["webhook_server"]["port"] == 5001
    assert loaded_data["trading"]["defaults"]["quantity"] == 75

def test_load_yaml_config_file_not_found(tmp_path):
    """Tests behavior when YAML file is not found."""
    # tmp_path provides an empty directory, so a non-existent file path
    non_existent_file = tmp_path / "non_existent.yaml"
    loaded_data = loader._load_yaml_config(str(non_existent_file))
    assert loaded_data == {} # Expect an empty dict as per loader logic

def test_load_yaml_config_invalid_yaml(tmp_path, caplog):
    """Tests behavior with an invalid YAML file."""
    config_file = tmp_path / "invalid_config.yaml"
    config_file.write_text("webhook_server: port: 5000\n  trading: default_quantity: 100") # Invalid indent

    loaded_data = loader._load_yaml_config(str(config_file))
    assert loaded_data == {} # Expect empty dict on error
    assert "Error parsing YAML configuration file" in caplog.text # Check for error log

def test_load_env_vars_file(tmp_path, monkeypatch):
    """Tests loading variables from a .env file."""
    dummy_env_content = (
        'OANDA_API_KEY="testkey_from_file"\n'
        'OANDA_ACCOUNT_ID="testacc_from_file"\n'
        'UNRELATED_VAR="should_not_be_loaded_directly_by_loader"\n'
        'WEBHOOK_SHARED_SECRET="test_secret_from_file"'
    )
    env_file = tmp_path / ".env"
    env_file.write_text(dummy_env_content)

    # Monkeypatch os.getenv so we are sure only .env file values are considered
    # and not actual environment variables from the test runner's environment.
    # This also means _load_env_vars must rely on python-dotenv's population of os.environ
    # or we directly mock os.getenv calls within _load_env_vars.
    # For this test, we'll assume python-dotenv correctly populates os.environ from the dummy file.

    # Clear relevant os.environ keys that might be set by the test environment
    # to ensure we're testing the file loading.
    # A better approach for _load_env_vars would be to not read os.getenv globally
    # but pass the dict from dotenv.dotenv_values()
    keys_to_clear = ["OANDA_API_KEY", "OANDA_ACCOUNT_ID", "WEBHOOK_SHARED_SECRET", "OANDA_API_URL"]
    original_values = {k: os.environ.get(k) for k in keys_to_clear}
    for k in keys_to_clear:
        if k in os.environ:
            monkeypatch.delenv(k, raising=False)

    env_vars = loader._load_env_vars(str(env_file))

    assert env_vars.get("OANDA_API_KEY") == "testkey_from_file"
    assert env_vars.get("OANDA_ACCOUNT_ID") == "testacc_from_file"
    assert env_vars.get("WEBHOOK_SHARED_SECRET") == "test_secret_from_file"
    assert "UNRELATED_VAR" not in env_vars # Because it's not in env_keys_to_capture

    # Restore original environment values (important if tests run in parallel or affect global state)
    for k, v in original_values.items():
        if v is not None:
            monkeypatch.setenv(k, v)
        elif k in os.environ: # If it was not set before, ensure it's not set now from the dummy file
             monkeypatch.delenv(k, raising=False)


def test_initialize_config_and_get(tmp_path, monkeypatch):
    """Tests the full initialize_config and get functionality."""
    dummy_yaml_content = {
        "app_name": "TradingApp",
        "logging": {"level": "DEBUG"},
        "trading": {
            "defaults": {"quantity": 10},
            "allowed_instruments": ["EUR_USD", "USD_JPY"]
        },
        "oanda": {"base_url": "https://yaml-url.com"} # This will be overridden by .env
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(dummy_yaml_content, f)

    dummy_env_content = (
        'OANDA_API_KEY="env_api_key"\n'
        'OANDA_ACCOUNT_ID="env_account_id"\n'
        'WEBHOOK_SHARED_SECRET="env_webhook_secret"\n'
        'OANDA_API_URL="https://env-api-url.com" # This should override YAML'
    )
    env_file = tmp_path / ".env"
    env_file.write_text(dummy_env_content)

    # Ensure relevant os.environ variables are clean before test
    keys_to_clear = ["OANDA_API_KEY", "OANDA_ACCOUNT_ID", "WEBHOOK_SHARED_SECRET", "OANDA_API_URL"]
    for k in keys_to_clear:
        monkeypatch.delenv(k, raising=False)

    # Initialize config using the temporary files
    loader.initialize_config(config_path=str(config_file), env_path=str(env_file))

    # Test getting values
    assert loader.get("app_name") == "TradingApp"
    assert loader.get("logging.level") == "DEBUG"
    assert loader.get("trading.defaults.quantity") == 10
    assert loader.get("trading.allowed_instruments") == ["EUR_USD", "USD_JPY"]

    # Test .env secrets
    assert loader.get("OANDA_API_KEY") == "env_api_key"
    assert loader.get("OANDA_ACCOUNT_ID") == "env_account_id"
    assert loader.get("WEBHOOK_SHARED_SECRET") == "env_webhook_secret"

    # Test .env override for OANDA_API_URL (which becomes oanda.base_url)
    assert loader.get("oanda.base_url") == "https://env-api-url.com"
    assert loader.get("OANDA_API_URL") == "https://env-api-url.com" # Also directly accessible

    # Test non-existent key with default
    assert loader.get("non.existent.key", "default_value") == "default_value"
    # Test non-existent key without default
    assert loader.get("another.non.existent.key") is None

def test_get_before_initialize(caplog):
    """Tests that get() initializes config if called first (though not ideal)."""
    # _config and _env_vars are reset by the reset_config_loader_state fixture
    assert loader._config is None 

    # This call to get() should trigger internal initialization
    # It will try to load default config.yaml and .env, which might not exist or be empty
    # in a clean test environment without specific tmp_path setup for *this* test.
    # So we check if a warning is logged.
    loader.get("some.key")
    assert "Config not initialized. Call initialize_config() first." in caplog.text
    # And also check that _config is no longer None
    assert loader._config is not None # Should be at least {} if files not found