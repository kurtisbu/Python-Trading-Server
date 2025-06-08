# src/position_management/manager.py
import logging
import sqlite3
import os

logger = logging.getLogger(__name__)

# --- Database Path ---
# This logic ensures the manager can find the database file in the project root.
# It assumes this file is in src/position_management/
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATABASE_NAME = "trading_orders.db"
DATABASE_PATH = os.path.join(PROJECT_ROOT_DIR, DATABASE_NAME)

def _get_db_connection():
    """Establishes a connection to the SQLite database."""
    # This is a helper function specific to this manager for now.
    # In a larger app, DB connection logic might be further centralized.
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row # Access columns by name
    return conn

def get_position(instrument: str) -> float:
    """
    Calculates the net position for a single instrument by summing all filled trades.

    Args:
        instrument (str): The instrument to calculate the position for (e.g., "EUR_USD").

    Returns:
        float: The net position. Positive for long, negative for short, 0 for flat.
    """
    net_position = 0.0
    conn = None
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()

        # Sum the 'fill_quantity' for all filled orders of the given instrument.
        # 'fill_quantity' is positive for buys and negative for sells.
        sql = """
            SELECT SUM(fill_quantity) AS net_position
            FROM orders
            WHERE instrument = ? AND status = 'FILLED';
        """
        cursor.execute(sql, (instrument,))
        result = cursor.fetchone()

        if result and result['net_position'] is not None:
            net_position = float(result['net_position'])

        logger.info(f"Calculated net position for {instrument}: {net_position}")
        return net_position

    except sqlite3.Error as e:
        logger.error(f"Database error while calculating position for {instrument}: {e}", exc_info=True)
        return 0.0 # Return a neutral position on DB error
    finally:
        if conn:
            conn.close()

def get_all_positions() -> dict:
    """
    Calculates all current non-zero net positions by grouping by instrument.

    Returns:
        dict: A dictionary where keys are instruments and values are their net positions.
              e.g., {"EUR_USD": 150.0, "USD_JPY": -500.0}
    """
    all_positions = {}
    conn = None
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()

        # Group by instrument and sum the quantities of all filled orders.
        sql = """
            SELECT instrument, SUM(fill_quantity) AS net_position
            FROM orders
            WHERE status = 'FILLED'
            GROUP BY instrument;
        """
        cursor.execute(sql)
        results = cursor.fetchall()

        for row in results:
            # Only include positions that are not flat (net_position is not 0)
            if row['net_position'] != 0:
                all_positions[row['instrument']] = float(row['net_position'])

        logger.info(f"Calculated all open positions: {all_positions}")
        return all_positions

    except sqlite3.Error as e:
        logger.error(f"Database error while calculating all positions: {e}", exc_info=True)
        return {} # Return an empty dict on DB error
    finally:
        if conn:
            conn.close()