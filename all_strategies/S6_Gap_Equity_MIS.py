#!/usr/bin/env python3
"""
OvernightGapMeanReversion.py - Strategy 1: Overnight Gap Mean Reversion
Intraday Long/Short strategy for Nifty 50 stocks (MIS).

Logic:
------
Long Signal (Gap Down Reversal):
1. Previous day's close > 20-day EMA (trend filter).
2. Stock opens with a gap down of 0.5% - 2.0% relative to prev close.
3. Price shows recovery and breaks above the First 15-minute candle High.
4. Current price > VWAP.
Long Exit:
- Target: Earlier of (Previous Day's Close) or (Entry + 1.5 * Risk).
- Stop Loss: Below the opening low (Day's low formed during opening window).
- Market close square-off at 15:15 if neither target nor stop is hit.

Short Signal (Gap Up Reversal):
1. Previous day's close < 20-day EMA.
2. Stock opens with a gap up of 0.5% - 2.0% relative to prev close.
3. Price reverses and breaks below the First 15-minute candle Low.
4. Current price < VWAP.
Short Exit:
- Target: Earlier of (Previous Day's Close) or (Entry - 1.5 * Risk).
- Stop Loss: Above the opening high.
- Market close square-off at 15:15 if neither target nor stop is hit.
"""

import os
import sys
import time
from datetime import datetime, time as dtime, timedelta
import pandas as pd
import numpy as np

try:
    from openalgo import api
except ImportError:
    print("Error: 'openalgo' package is required. Install via 'pip install openalgo'.")
    sys.exit(1)

# ==============================================================================
# SETTINGS & CONSTANTS
# ==============================================================================
STRATEGY_NAME = "OvernightGapMeanReversion"
EXCHANGE = "NSE"
PRODUCT = "MIS"            # Intraday MIS allows both Long and Short
PRICE_TYPE = "MARKET"

CAPITAL_PER_TRADE = 50000.0  # Rs 50,000 per trade
MAX_OPEN_POSITIONS = 10
MAX_TRADES_PER_STOCK = 2

# Gap thresholds
MIN_GAP_PCT = 0.5   # 0.5%
MAX_GAP_PCT = 2.0   # 2.0%
TARGET_R_MULT = 1.5

# Trading session times (IST)
MARKET_OPEN_TIME = dtime(9, 15)
FIRST_15M_END_TIME = dtime(9, 30)
ENTRY_END_TIME = dtime(14, 30)
SQUARE_OFF_TIME = dtime(15, 15)

EMA_20_DAYS = 20
CHECK_INTERVAL_SECONDS = 15

# NIFTY 50 Universe
NIFTY_50_STOCKS = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BPCL",
    "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN",
    "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO"
]

# ==============================================================================
# TECHNICAL CALCULATIONS
# ==============================================================================
def calculate_vwap(df_today: pd.DataFrame) -> float:
    """Computes intraday VWAP for today's session."""
    if df_today.empty or 'volume' not in df_today.columns:
        return 0.0
    typical_price = (df_today['high'] + df_today['low'] + df_today['close']) / 3.0
    cum_vol_price = (typical_price * df_today['volume']).cumsum()
    cum_vol = df_today['volume'].cumsum()
    vwap = cum_vol_price / cum_vol.replace(0, np.nan)
    return float(vwap.iloc[-1]) if not vwap.empty else 0.0


def calculate_daily_trend_and_gap(df_history: pd.DataFrame):
    """
    Computes:
    - 20-day EMA of daily closes
    - Previous day's close
    - Today's open price and gap percentage
    """
    df = df_history.copy()
    if 'timestamp' not in df.columns:
        df['timestamp'] = pd.to_datetime(df.index)
    else:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    df['session_date'] = df['timestamp'].dt.date
    daily = df.groupby('session_date').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).sort_index()

    if len(daily) < 21:
        return None

    # Calculate 20-day EMA on daily close
    daily['ema20'] = daily['close'].ewm(span=EMA_20_DAYS, adjust=False).mean()

    # Previous completed day
    prev_day = daily.iloc[-2]
    today = daily.iloc[-1]

    prev_close = float(prev_day['close'])
    prev_ema20 = float(prev_day['ema20'])
    today_open = float(today['open'])

    gap_pct = ((today_open - prev_close) / prev_close) * 100.0

    return {
        "prev_close": prev_close,
        "prev_ema20": prev_ema20,
        "today_open": today_open,
        "gap_pct": gap_pct
    }


# ==============================================================================
# STRATEGY MANAGER
# ==============================================================================
class OvernightGapMeanReversionStrategy:
    def __init__(self, client):
        self.client = client
        # Active positions: symbol -> dict
        self.open_positions = {}
        # Stock stats: symbol -> dict(trades_today, total_pnl)
        self.stock_stats = {sym: {"trades_today": 0} for sym in NIFTY_50_STOCKS}
        self.current_day = datetime.now().date()
        # Cache for daily levels: symbol -> dict
        self.daily_cache = {}

    def reset_daily_stats_if_new_day(self):
        today = datetime.now().date()
        if today != self.current_day:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] New Trading Day: {today}. Resetting session cache.")
            self.current_day = today
            self.stock_stats = {sym: {"trades_today": 0} for sym in NIFTY_50_STOCKS}
            self.daily_cache.clear()
            self.open_positions.clear()

    def fetch_intraday_data(self, symbol: str) -> pd.DataFrame:
        """Fetches 5-minute historical data for recent days."""
        try:
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")

            df = self.client.history(
                symbol=symbol,
                exchange=EXCHANGE,
                interval="5m",
                start_date=start_date,
                end_date=end_date
            )
            if df is None or df.empty:
                return None

            df.columns = [col.lower() for col in df.columns]
            if 'timestamp' not in df.columns:
                df['timestamp'] = pd.to_datetime(df.index)
            else:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df.sort_values('timestamp').reset_index(drop=True)
        except Exception:
            return None

    def execute_entry(self, symbol: str, action: str, price: float, stop_loss: float, target: float, qty: int):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{action} SIGNAL] {symbol} @ {price:.2f} | Qty: {qty} | Stop: {stop_loss:.2f} | Target: {target:.2f}")
        try:
            position_size = qty if action == "BUY" else -qty
            resp = self.client.placesmartorder(
                strategy=STRATEGY_NAME,
                symbol=symbol,
                action=action,
                exchange=EXCHANGE,
                price_type=PRICE_TYPE,
                product=PRODUCT,
                quantity=qty,
                position_size=position_size
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Order Response for {symbol}: {resp}")

            self.open_positions[symbol] = {
                "action": action,
                "entry_price": price,
                "quantity": qty,
                "stop_loss": stop_loss,
                "target": target,
                "initial_risk": abs(price - stop_loss)
            }
            self.stock_stats[symbol]["trades_today"] += 1
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing {action} for {symbol}: {e}")

    def execute_exit(self, symbol: str, exit_price: float, reason: str):
        pos = self.open_positions.get(symbol)
        if not pos:
            return

        qty = pos["quantity"]
        exit_action = "SELL" if pos["action"] == "BUY" else "BUY"

        print(f"[{datetime.now().strftime('%H:%M:%S')}] [EXIT] {symbol} ({pos['action']}) @ {exit_price:.2f} | Reason: {reason}")
        try:
            resp = self.client.placesmartorder(
                strategy=STRATEGY_NAME,
                symbol=symbol,
                action=exit_action,
                exchange=EXCHANGE,
                price_type=PRICE_TYPE,
                product=PRODUCT,
                quantity=qty,
                position_size=0
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Exit Order Response for {symbol}: {resp}")

            pnl = (exit_price - pos["entry_price"]) * qty if pos["action"] == "BUY" else (pos["entry_price"] - exit_price) * qty
            print(f"[{datetime.now().strftime('%H:%M:%S')}] PnL for {symbol}: Rs {pnl:+,.2f}")

            del self.open_positions[symbol]
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing exit for {symbol}: {e}")

    def manage_open_positions(self):
        """Checks open positions every 15s for Target, Stop Loss, or Square-off."""
        symbols_to_check = list(self.open_positions.keys())
        for symbol in symbols_to_check:
            pos = self.open_positions.get(symbol)
            if not pos:
                continue

            df = self.fetch_intraday_data(symbol)
            if df is None or df.empty:
                continue

            current_price = float(df['close'].iloc[-1])
            action = pos["action"]
            sl = pos["stop_loss"]
            tgt = pos["target"]

            if action == "BUY":
                # Stop loss hit
                if current_price <= sl:
                    self.execute_exit(symbol, current_price, f"Stop Loss Hit ({current_price:.2f} <= {sl:.2f})")
                # Target hit
                elif current_price >= tgt:
                    self.execute_exit(symbol, current_price, f"Target Reached ({current_price:.2f} >= {tgt:.2f})")
            elif action == "SELL":
                # Stop loss hit
                if current_price >= sl:
                    self.execute_exit(symbol, current_price, f"Stop Loss Hit ({current_price:.2f} >= {sl:.2f})")
                # Target hit
                elif current_price <= tgt:
                    self.execute_exit(symbol, current_price, f"Target Reached ({current_price:.2f} <= {tgt:.2f})")

    def square_off_all(self):
        """Intraday square-off at 15:15."""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Square-off time reached. Closing all active positions...")
        for symbol in list(self.open_positions.keys()):
            df = self.fetch_intraday_data(symbol)
            current_price = float(df['close'].iloc[-1]) if df is not None and not df.empty else self.open_positions[symbol]["entry_price"]
            self.execute_exit(symbol, current_price, "Intraday Square-off (15:15)")

    def evaluate_entries(self):
        """Evaluates Long & Short Gap Mean Reversion entry conditions."""
        now_time = datetime.now().time()
        # Entries only allowed after the first 15m candle (09:30) and up to 14:30
        if not (FIRST_15M_END_TIME <= now_time <= ENTRY_END_TIME):
            return

        if len(self.open_positions) >= MAX_OPEN_POSITIONS:
            return

        today_date = datetime.now().date()

        for symbol in NIFTY_50_STOCKS:
            if len(self.open_positions) >= MAX_OPEN_POSITIONS:
                break
            if symbol in self.open_positions:
                continue
            if self.stock_stats[symbol]["trades_today"] >= MAX_TRADES_PER_STOCK:
                continue

            df = self.fetch_intraday_data(symbol)
            if df is None or len(df) < 50:
                continue

            # Separate today's candles
            df['date'] = df['timestamp'].dt.date
            df_today = df[df['date'] == today_date].copy()
            if df_today.empty:
                continue

            # Filter first 15 minutes (09:15 to 09:30)
            df_first_15m = df_today[(df_today['timestamp'].dt.time >= MARKET_OPEN_TIME) & 
                                    (df_today['timestamp'].dt.time < FIRST_15M_END_TIME)]
            if df_first_15m.empty:
                continue

            first_15m_high = float(df_first_15m['high'].max())
            first_15m_low = float(df_first_15m['low'].min())
            opening_low = float(df_first_15m['low'].min())
            opening_high = float(df_first_15m['high'].max())

            # Daily levels and gap
            levels = calculate_daily_trend_and_gap(df)
            if levels is None:
                continue

            prev_close = levels["prev_close"]
            prev_ema20 = levels["prev_ema20"]
            gap_pct = levels["gap_pct"]

            # Compute current VWAP & LTP
            current_price = float(df_today['close'].iloc[-1])
            vwap = calculate_vwap(df_today)

            qty = max(1, int(CAPITAL_PER_TRADE / current_price))

            # ------------------------------------------------------------------
            # 1. BUY SIGNAL (GAP DOWN REVERSAL)
            # ------------------------------------------------------------------
            # Rule 1: Prev Close > 20-day EMA
            # Rule 2: Gap down between 0.5% and 2.0%
            # Rule 3 & 4: Price breaks above first 15m high
            # Rule 5: Price > VWAP
            if (prev_close > prev_ema20) and (-MAX_GAP_PCT <= gap_pct <= -MIN_GAP_PCT):
                if (current_price > first_15m_high) and (current_price > vwap):
                    stop_loss = opening_low * 0.9995  # Slightly below opening low
                    risk = current_price - stop_loss
                    if risk > 0:
                        # Target: Earlier/tighter of (Prev Day Close) or (Entry + 1.5R)
                        target = min(prev_close, current_price + (TARGET_R_MULT * risk))
                        self.execute_entry(symbol, "BUY", current_price, stop_loss, target, qty)
                        continue

            # ------------------------------------------------------------------
            # 2. SHORT SIGNAL (GAP UP REVERSAL)
            # ------------------------------------------------------------------
            # Rule 1: Prev Close < 20-day EMA
            # Rule 2: Gap up between 0.5% and 2.0%
            # Rule 3 & 4: Price breaks below first 15m low
            # Rule 5: Price < VWAP
            if (prev_close < prev_ema20) and (MIN_GAP_PCT <= gap_pct <= MAX_GAP_PCT):
                if (current_price < first_15m_low) and (current_price < vwap):
                    stop_loss = opening_high * 1.0005  # Slightly above opening high
                    risk = stop_loss - current_price
                    if risk > 0:
                        # Target: Earlier/tighter of (Prev Day Close) or (Entry - 1.5R)
                        target = max(prev_close, current_price - (TARGET_R_MULT * risk))
                        self.execute_entry(symbol, "SELL", current_price, stop_loss, target, qty)
                        continue

    def run(self):
        print("=" * 75)
        print(f"Starting {STRATEGY_NAME}")
        print(f"Universe: {len(NIFTY_50_STOCKS)} Stocks | Product: {PRODUCT} | Trade Size: Rs {CAPITAL_PER_TRADE:,.0f}")
        print(f"Gap Range: {MIN_GAP_PCT}% to {MAX_GAP_PCT}% | Target: Prev Close or 1.5R | Max Open: {MAX_OPEN_POSITIONS}")
        print("=" * 75)

        while True:
            try:
                now_time = datetime.now().time()
                self.reset_daily_stats_if_new_day()

                # Square-off at 15:15
                if now_time >= SQUARE_OFF_TIME:
                    if len(self.open_positions) > 0:
                        self.square_off_all()
                    time.sleep(60)
                    continue

                # 1. Manage Exits on existing positions
                if len(self.open_positions) > 0:
                    self.manage_open_positions()

                # 2. Evaluate Entries
                if FIRST_15M_END_TIME <= now_time <= ENTRY_END_TIME:
                    self.evaluate_entries()

                time.sleep(CHECK_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                print("\nStrategy stopped by user.")
                break
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected error: {e}")
                time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    api_key = os.getenv('OPENALGO_API_KEY')
    host = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
    ws_url = os.getenv('WEBSOCKET_URL', 'ws://127.0.0.1:8765')

    if not api_key:
        print("Error: OPENALGO_API_KEY environment variable not set.")
        sys.exit(1)

    client = api(api_key=api_key, host=host, ws_url=ws_url)
    strategy = OvernightGapMeanReversionStrategy(client=client)
    strategy.run()
