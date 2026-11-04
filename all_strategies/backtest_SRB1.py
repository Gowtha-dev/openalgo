#!/usr/bin/env python3
"""
Backtest Engine for SRB1EquityNifty50Stocks5Min
Simulates the exact rules on historical 5-minute candle data:
- Supertrend (10, 3)
- RSI (14) > 70
- Prev Day R1 Pivot Breakout
- Upper Bollinger Band (20, 2) Breakout
- 1.5 x ATR Initial Stop
- Trailing Supertrend (never moves down)
- Breakeven at +1R
- Supertrend Flip Exit
- Intraday Square-off at 15:15
- Daily max 2 trades, -2R loss cut-off
"""

import os
import sys
import argparse
from datetime import datetime, time as dtime, timedelta
import pandas as pd
import numpy as np

# Try importing OpenAlgo client
try:
    from openalgo import api
    HAS_OPENALGO = True
except ImportError:
    HAS_OPENALGO = False

# Strategy Constants
CAPITAL_PER_TRADE = 50000.0
ENTRY_START_TIME = dtime(9, 30)
ENTRY_END_TIME = dtime(14, 30)
SQUARE_OFF_TIME = dtime(15, 15)

SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0
RSI_PERIOD = 14
RSI_BUY_THRESHOLD = 70.0
BB_PERIOD = 20
BB_STD = 2.0
ATR_PERIOD = 10
ATR_STOP_MULT = 1.5
MIN_CANDLE_HISTORY = 60
SLIPPAGE_PCT = 0.0005  # 0.05% slippage

# ==============================================================================
# INDICATORS
# ==============================================================================
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    high, low, close = df['high'], df['low'], df['close']

    # True Range & ATR
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / ATR_PERIOD, adjust=False).mean()
    df['atr'] = atr

    # Supertrend
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + (SUPERTREND_MULTIPLIER * atr)
    basic_lower = hl2 - (SUPERTREND_MULTIPLIER * atr)

    upper_band = basic_upper.copy()
    lower_band = basic_lower.copy()
    trend = pd.Series(1, index=df.index)
    supertrend = pd.Series(np.nan, index=df.index)

    close_arr = close.values
    bu_arr = basic_upper.values
    bl_arr = basic_lower.values
    ub_arr = upper_band.values
    lb_arr = lower_band.values
    tr_arr = trend.values
    st_arr = supertrend.values

    for i in range(1, len(df)):
        if bl_arr[i] > lb_arr[i - 1] or close_arr[i - 1] < lb_arr[i - 1]:
            lb_arr[i] = bl_arr[i]
        else:
            lb_arr[i] = lb_arr[i - 1]

        if bu_arr[i] < ub_arr[i - 1] or close_arr[i - 1] > ub_arr[i - 1]:
            ub_arr[i] = bu_arr[i]
        else:
            ub_arr[i] = ub_arr[i - 1]

        prev_trend = tr_arr[i - 1]
        if prev_trend == 1:
            if close_arr[i] < lb_arr[i]:
                tr_arr[i] = -1
                st_arr[i] = ub_arr[i]
            else:
                tr_arr[i] = 1
                st_arr[i] = lb_arr[i]
        else:
            if close_arr[i] > ub_arr[i]:
                tr_arr[i] = 1
                st_arr[i] = lb_arr[i]
            else:
                tr_arr[i] = -1
                st_arr[i] = ub_arr[i]

    df['supertrend'] = st_arr
    df['supertrend_dir'] = tr_arr

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

    # Bollinger Bands
    sma = close.rolling(window=BB_PERIOD).mean()
    std = close.rolling(window=BB_PERIOD).std()
    df['bb_upper'] = sma + (BB_STD * std)
    df['bb_lower'] = sma - (BB_STD * std)

    return df


def compute_daily_pivots(df: pd.DataFrame) -> dict:
    """Pre-computes previous day R1 pivot for every date."""
    df['date'] = df['timestamp'].dt.date
    daily = df.groupby('date').agg({'high': 'max', 'low': 'min', 'close': 'last'})
    
    # Shift daily to get previous day values
    daily['pivot'] = (daily['high'] + daily['low'] + daily['close']) / 3.0
    daily['r1'] = (2.0 * daily['pivot']) - daily['low']
    daily['prev_r1'] = daily['r1'].shift(1)
    
    return daily['prev_r1'].to_dict()


# ==============================================================================
# BACKTEST ENGINE
# ==============================================================================
def run_backtest(df: pd.DataFrame, symbol: str = "STOCK") -> pd.DataFrame:
    # Ensure correct columns and datetime sorting
    df.columns = [c.lower() for c in df.columns]
    if 'timestamp' not in df.columns:
        if 'date' in df.columns:
            df['timestamp'] = pd.to_datetime(df['date'])
        else:
            df['timestamp'] = pd.to_datetime(df.index)
    else:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    df = df.sort_values('timestamp').reset_index(drop=True)

    print(f"Calculating technical indicators for {len(df)} candles...")
    df = calculate_indicators(df)
    prev_r1_map = compute_daily_pivots(df)

    trades = []
    position = None  # None or dict
    current_day = None
    trades_today = 0
    total_r_today = 0.0

    print(f"Simulating trades for {symbol}...")

    # Iterate bar by bar (starting after warm-up)
    for i in range(MIN_CANDLE_HISTORY, len(df)):
        bar = df.iloc[i]
        bar_time = bar['timestamp']
        bar_date = bar_time.date()
        bar_t = bar_time.time()

        # Day reset
        if bar_date != current_day:
            current_day = bar_date
            trades_today = 0
            total_r_today = 0.0

        prev_bar = df.iloc[i - 1]
        prev_r1 = prev_r1_map.get(bar_date, 0.0)

        # -------------------------------------------------------------
        # 1. POSITION MANAGEMENT / EXIT CHECKS
        # -------------------------------------------------------------
        if position is not None:
            entry_price = position['entry_price']
            stop_price = position['stop']
            init_risk = position['initial_risk']
            qty = position['quantity']

            exit_price = None
            exit_reason = None

            # A. Check Stop Hit inside the bar (Low <= Stop)
            if bar['low'] <= stop_price:
                # Fill at open if gap down below stop, otherwise stop level
                exit_price = min(bar['open'], stop_price) * (1.0 - SLIPPAGE_PCT)
                exit_reason = "Stop Loss Hit"

            # B. Check Supertrend Flip on previous closed bar
            elif prev_bar['supertrend_dir'] == -1:
                exit_price = bar['open'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "Supertrend Flipped Down"

            # C. Check Square-off at 15:15
            elif bar_t >= SQUARE_OFF_TIME:
                exit_price = bar['open'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "Square-off 15:15"

            if exit_price is not None:
                pnl = (exit_price - entry_price) * qty
                r_multiple = (exit_price - entry_price) / init_risk
                total_r_today += r_multiple

                trades.append({
                    'symbol': symbol,
                    'entry_time': position['entry_time'],
                    'entry_price': round(entry_price, 2),
                    'exit_time': bar_time,
                    'exit_price': round(exit_price, 2),
                    'quantity': qty,
                    'pnl': round(pnl, 2),
                    'r_multiple': round(r_multiple, 2),
                    'reason': exit_reason
                })
                position = None
            else:
                # Trailing stop update on previous closed bar
                if prev_bar['supertrend_dir'] == 1 and prev_bar['supertrend'] > position['stop']:
                    position['stop'] = float(prev_bar['supertrend'])

                # Breakeven update: check if High reached Entry + 1R
                if not position['breakeven_activated']:
                    if bar['high'] >= (entry_price + init_risk):
                        position['stop'] = max(position['stop'], entry_price)
                        position['breakeven_activated'] = True

        # -------------------------------------------------------------
        # 2. ENTRY LOGIC (Evaluated on previous closed candle: prev_bar)
        # -------------------------------------------------------------
        if position is None:
            # Check entry window: 09:30 to 14:30
            if ENTRY_START_TIME <= bar_t <= ENTRY_END_TIME:
                # Daily stock limits: 2 trades, or -2R loss
                if trades_today < 2 and total_r_today > -2.0:
                    c_price = prev_bar['close']
                    
                    # 5 Criteria:
                    # 1. Supertrend up & Close > Supertrend
                    c1 = (prev_bar['supertrend_dir'] == 1) and (c_price > prev_bar['supertrend'])
                    # 2. RSI > 70
                    c2 = prev_bar['rsi'] > RSI_BUY_THRESHOLD
                    # 3. Close > Previous Day R1
                    c3 = (prev_r1 > 0) and (c_price > prev_r1)
                    # 4. Close > Upper Bollinger Band
                    c4 = c_price > prev_bar['bb_upper']

                    if c1 and c2 and c3 and c4:
                        # Enter at open of current candle + slippage
                        fill_price = bar['open'] * (1.0 + SLIPPAGE_PCT)
                        initial_stop = max(float(prev_bar['supertrend']), fill_price - (ATR_STOP_MULT * float(prev_bar['atr'])))
                        init_risk = max(fill_price - initial_stop, 0.05)
                        qty = max(1, int(CAPITAL_PER_TRADE / fill_price))

                        position = {
                            'entry_time': bar_time,
                            'entry_price': fill_price,
                            'quantity': qty,
                            'stop': initial_stop,
                            'initial_risk': init_risk,
                            'breakeven_activated': False
                        }
                        trades_today += 1

    return pd.DataFrame(trades)


def display_results(trades_df: pd.DataFrame, symbol: str):
    print("\n" + "=" * 65)
    print(f" BACKTEST SUMMARY: {symbol}")
    print("=" * 65)

    if trades_df.empty:
        print("No trades generated during the test period.")
        print("=" * 65)
        return

    total_trades = len(trades_df)
    wins = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] < 0]

    win_rate = (len(wins) / total_trades) * 100.0
    total_pnl = trades_df['pnl'].sum()
    total_r = trades_df['r_multiple'].sum()
    avg_trade_pnl = trades_df['pnl'].mean()

    gross_profit = wins['pnl'].sum() if not wins.empty else 0.0
    gross_loss = abs(losses['pnl'].sum()) if not losses.empty else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else np.nan

    print(f"Total Trades     : {total_trades}")
    print(f"Win Rate         : {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"Total Net P&L    : Rs {total_pnl:,.2f}")
    print(f"Total R Return   : {total_r:+.2f} R")
    print(f"Average Trade PnL: Rs {avg_trade_pnl:,.2f}")
    if not np.isnan(profit_factor):
        print(f"Profit Factor    : {profit_factor:.2f}")

    print("-" * 65)
    print("Recent Trades:")
    cols_to_show = ['entry_time', 'exit_time', 'entry_price', 'exit_price', 'pnl', 'r_multiple', 'reason']
    print(trades_df[cols_to_show].tail(10).to_string(index=False))
    print("=" * 65)


# ==============================================================================
# MAIN / CLI
# ==============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest SRB1 Strategy on a Single Stock")
    parser.add_argument("--symbol", default="RELIANCE", help="Stock symbol (e.g. RELIANCE, TCS, INFY)")
    parser.add_argument("--days", type=int, default=30, help="Number of historical days to fetch (via OpenAlgo API)")
    parser.add_argument("--csv", help="Path to local 5-min CSV candle file (with timestamp, open, high, low, close)")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    df = None

    if args.csv and os.path.exists(args.csv):
        print(f"Loading data from local CSV: {args.csv}")
        df = pd.read_csv(args.csv)
    else:
        # Fetch from OpenAlgo API
        api_key = os.getenv('OPENALGO_API_KEY')
        host = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')

        if not HAS_OPENALGO or not api_key:
            print("Note: OPENALGO_API_KEY environment variable not set, or reading from local sample.")
            print("To fetch live broker candles via OpenAlgo:")
            print("   export OPENALGO_API_KEY='your_api_key'")
            print("   python openalgo/strategies/scripts/backtest_SRB1.py --symbol RELIANCE --days 30\n")
            print("Alternatively, pass a CSV file: --csv path/to/candles.csv")
            sys.exit(0)

        client = api(api_key=api_key, host=host)
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

        print(f"Fetching 5-minute candles for {symbol} ({start_date} to {end_date}) from OpenAlgo...")
        df = client.history(
            symbol=symbol,
            exchange="NSE",
            interval="5m",
            start_date=start_date,
            end_date=end_date
        )

    if df is None or df.empty:
        print("Error: Could not retrieve candle data.")
        sys.exit(1)

    trades = run_backtest(df, symbol=symbol)
    display_results(trades, symbol=symbol)

    # Save results
    output_dir = "openalgo/workspace/backtests"
    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, f"backtest_{symbol}.csv")
    trades.to_csv(out_file, index=False)
    print(f"Full trade report saved to: {out_file}\n")
