#!/usr/bin/env python3
"""
Backtest Engine: Strategy 1 (Overnight Gap Mean Reversion) - TWO-SIDED OPTION BUYING (Buy CE & Buy PE)
Evaluates buying:
  1. ATM Call Options (CE) on Bullish Gap Down Reversals
  2. ATM Put Options (PE) on Bearish Gap Up Reversals
Timeframe: 1-Hour Candles (250 Trading Days)
Universe: 50 NIFTY Stocks
"""

import os
import sys
import time
import math
import sqlite3
from datetime import datetime, time as dtime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf

MAX_PORTFOLIO_POSITIONS = 10
MAX_TRADES_PER_STOCK = 1
PREMIUM_STOP_LOSS_PCT = 0.30  # 30% option stop loss
TARGET_R_MULT = 1.5

MARKET_OPEN_TIME = dtime(9, 15)
FIRST_1H_END_TIME = dtime(10, 15)
ENTRY_END_TIME = dtime(14, 30)
SQUARE_OFF_TIME = dtime(15, 15)
MIN_GAP_PCT = 0.5
MAX_GAP_PCT = 2.0
SLIPPAGE_PCT = 0.01  # 1% option slippage

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

def get_lot_sizes():
    db_path = "db/openalgo.db"
    lot_map = {}
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name, lotsize FROM symtoken WHERE exchange='NFO' AND instrumenttype IN ('OPTSTK', 'CE', 'PE') GROUP BY name;")
        for name, sz in cur.fetchall():
            if sz:
                lot_map[name] = int(sz)
        conn.close()

    defaults = {
        'RELIANCE': 500, 'TCS': 175, 'INFY': 400, 'HDFCBANK': 550, 'ICICIBANK': 700,
        'SBIN': 750, 'BHARTIARTL': 475, 'ITC': 1600, 'LT': 150, 'AXISBANK': 625,
        'KOTAKBANK': 400, 'WIPRO': 1500, 'TATACONSUM': 900, 'TATASTEEL': 5500,
        'MARUTI': 50, 'BAJFINANCE': 125, 'HCLTECH': 350, 'SUNPHARMA': 350
    }
    for k, v in defaults.items():
        lot_map.setdefault(k, v)
    return lot_map


def calculate_fno_charges(premium_entry, premium_exit, qty):
    turnover = (premium_entry + premium_exit) * qty
    brokerage = 40.0
    stt = (premium_exit * qty) * 0.001  # STT is on Sell side
    exchange_txn = turnover * 0.0005
    sebi_fee = turnover * 0.000001
    stamp_duty = (premium_entry * qty) * 0.00003  # Stamp duty on Buy side
    gst = (brokerage + exchange_txn + sebi_fee) * 0.18
    return round(brokerage + stt + exchange_txn + sebi_fee + stamp_duty + gst, 2)


def estimate_atm_option_premium(spot_price, iv=0.25, dte=15):
    time_to_exp = max(dte, 1) / 365.0
    return max(1.0, 0.40 * spot_price * iv * math.sqrt(time_to_exp))


def run_twoside_option_buying_backtest(stock_dfs):
    print("Pre-calculating Daily Trend, 20-day EMA, and Gaps...")
    lot_map = get_lot_sizes()

    daily_stats = {}
    for sym, df in stock_dfs.items():
        df['date'] = df['timestamp'].dt.date
        daily = df.groupby('date').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last'
        }).sort_index()

        daily['ema20'] = daily['close'].ewm(span=20, adjust=False).mean()
        daily['prev_close'] = daily['close'].shift(1)
        daily['prev_ema20'] = daily['ema20'].shift(1)
        daily['gap_pct'] = ((daily['open'] - daily['prev_close']) / daily['prev_close']) * 100.0
        daily_stats[sym] = daily

        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3.0
        df['cum_pv'] = df.groupby('date')['typical_price'].transform(lambda x: (x * df.loc[x.index, 'volume']).cumsum())
        df['cum_v'] = df.groupby('date')['volume'].cumsum()
        df['vwap'] = df['cum_pv'] / df['cum_v'].replace(0, np.nan)

    all_timestamps = sorted(list(set(
        ts for df in stock_dfs.values() for ts in df['timestamp']
    )))

    data_by_stock = {sym: df.set_index('timestamp') for sym, df in stock_dfs.items()}
    open_positions = {}
    stock_trade_count = {sym: 0 for sym in stock_dfs.keys()}
    current_day = None

    order_book = []
    trade_logs = []
    order_id = 1

    for ts in all_timestamps:
        bar_date = ts.date()
        bar_t = ts.time()

        if bar_date != current_day:
            current_day = bar_date
            stock_trade_count = {sym: 0 for sym in stock_dfs.keys()}

        # -------------------------------------------------------------
        # 1. MANAGE OPEN OPTION BUYING POSITIONS (LONG CE or LONG PE)
        # -------------------------------------------------------------
        closed_symbols = []
        for sym, pos in list(open_positions.items()):
            df_stock = data_by_stock.get(sym)
            if df_stock is None or ts not in df_stock.index:
                continue

            bar = df_stock.loc[ts]
            spot_cur = bar['close']
            spot_entry = pos['spot_entry']
            opt_entry_prem = pos['opt_entry_premium']
            lot_size = pos['lot_size']
            contract_type = pos['contract_type']  # 'CE' or 'PE'
            delta = 0.50

            # Intraday Theta Decay (~0.7% per hour)
            hours_held = max(1, (ts - pos['entry_time']).seconds // 3600)
            theta_decay = opt_entry_prem * (0.007 * hours_held)

            # Option buyer price tracking:
            # Long CE: Spot rising -> CE rises (profit), Spot falling -> CE drops (loss)
            # Long PE: Spot falling -> PE rises (profit), Spot rising -> PE drops (loss)
            if contract_type == 'CE':
                spot_diff = spot_cur - spot_entry
            else:
                spot_diff = spot_entry - spot_cur

            cur_option_prem = max(0.05, opt_entry_prem + (spot_diff * delta) - theta_decay)

            exit_prem = None
            exit_reason = None

            # A. Option 30% Hard Stop Loss
            if cur_option_prem <= (opt_entry_prem * (1.0 - PREMIUM_STOP_LOSS_PCT)):
                exit_prem = opt_entry_prem * (1.0 - PREMIUM_STOP_LOSS_PCT) * (1.0 - SLIPPAGE_PCT)
                exit_reason = "Option 30% Stop Loss Hit"

            # B. Spot Stop Level Hit (breaks opening extreme)
            elif (contract_type == 'CE' and bar['low'] <= pos['spot_stop']) or \
                 (contract_type == 'PE' and bar['high'] >= pos['spot_stop']):
                adverse = abs(pos['spot_stop'] - spot_entry)
                exit_prem = max(0.05, (opt_entry_prem - (adverse * delta) - theta_decay)) * (1.0 - SLIPPAGE_PCT)
                exit_reason = "Spot Opening Extreme Stop"

            # C. Spot Target Hit (reaches Prev Day Close / 1.5R)
            elif (contract_type == 'CE' and bar['high'] >= pos['spot_target']) or \
                 (contract_type == 'PE' and bar['low'] <= pos['spot_target']):
                favorable = abs(pos['spot_target'] - spot_entry)
                exit_prem = (opt_entry_prem + (favorable * delta) - theta_decay) * (1.0 - SLIPPAGE_PCT)
                exit_reason = "Spot Target Reached (Gap Fill)"

            # D. Intraday Square-off at 15:15
            elif bar_t >= SQUARE_OFF_TIME:
                exit_prem = cur_option_prem * (1.0 - SLIPPAGE_PCT)
                exit_reason = "Square-off at 15:15"

            if exit_prem is not None:
                # Order Book: SELL the long option to close
                order_book.append({
                    "order_id": order_id,
                    "timestamp": ts,
                    "symbol": sym,
                    "contract": pos['option_symbol'],
                    "action": "SELL",
                    "quantity": lot_size,
                    "premium": round(exit_prem, 2),
                    "status": "FILLED",
                    "reason": exit_reason
                })
                order_id += 1

                premium_invested = opt_entry_prem * lot_size
                premium_recovered = exit_prem * lot_size
                gross_pnl = premium_recovered - premium_invested
                charges = calculate_fno_charges(opt_entry_prem, exit_prem, lot_size)
                net_pnl = gross_pnl - charges
                r_mult = gross_pnl / (opt_entry_prem * PREMIUM_STOP_LOSS_PCT * lot_size)

                trade_logs.append({
                    "trade_id": len(trade_logs) + 1,
                    "symbol": sym,
                    "contract": pos['option_symbol'],
                    "type": f"BUY {contract_type}",
                    "entry_time": pos['entry_time'],
                    "opt_entry_premium": round(opt_entry_prem, 2),
                    "exit_time": ts,
                    "opt_exit_premium": round(exit_prem, 2),
                    "lot_size": lot_size,
                    "capital_invested": round(premium_invested, 2),
                    "gross_pnl": round(gross_pnl, 2),
                    "charges": charges,
                    "net_pnl": round(net_pnl, 2),
                    "pnl_pct": round(((exit_prem - opt_entry_prem) / opt_entry_prem) * 100.0, 2),
                    "r_multiple": round(r_mult, 2),
                    "reason": exit_reason
                })
                closed_symbols.append(sym)

        for sym in closed_symbols:
            del open_positions[sym]

        # -------------------------------------------------------------
        # 2. EVALUATE OPTION BUYING ENTRIES (10:15 to 14:30)
        # -------------------------------------------------------------
        if FIRST_1H_END_TIME <= bar_t <= ENTRY_END_TIME:
            available_slots = MAX_PORTFOLIO_POSITIONS - len(open_positions)
            if available_slots > 0:
                for sym, df_stock in data_by_stock.items():
                    if available_slots <= 0:
                        break
                    if sym in open_positions:
                        continue
                    if stock_trade_count[sym] >= MAX_TRADES_PER_STOCK:
                        continue
                    if ts not in df_stock.index:
                        continue

                    daily = daily_stats.get(sym)
                    if daily is None or bar_date not in daily.index:
                        continue

                    d_row = daily.loc[bar_date]
                    prev_close = d_row['prev_close']
                    prev_ema20 = d_row['prev_ema20']
                    gap_pct = d_row['gap_pct']

                    if pd.isna(prev_close) or pd.isna(prev_ema20):
                        continue

                    df_day = df_stock[df_stock['date'] == bar_date]
                    df_opening = df_day[df_day.index.time < FIRST_1H_END_TIME]
                    if df_opening.empty:
                        continue

                    first_1h_high = df_opening['high'].max()
                    first_1h_low = df_opening['low'].min()
                    opening_low = df_opening['low'].min()
                    opening_high = df_opening['high'].max()

                    bar = df_stock.loc[ts]
                    cur_price = bar['close']
                    cur_vwap = bar['vwap'] if not pd.isna(bar['vwap']) else cur_price
                    lot_size = lot_map.get(sym, 500)

                    # ---------------------------------------------------------
                    # Signal 1: BUY ATM CALL (CE) on Gap Down Reversal
                    # ---------------------------------------------------------
                    if (prev_close > prev_ema20) and (-MAX_GAP_PCT <= gap_pct <= -MIN_GAP_PCT):
                        if (cur_price > first_1h_high) and (cur_price >= cur_vwap):
                            spot_stop = opening_low * 0.9995
                            spot_risk = cur_price - spot_stop
                            if spot_risk > 0:
                                spot_target = min(prev_close, cur_price + (TARGET_R_MULT * spot_risk))
                                atm_strike = round(cur_price / 10.0) * 10.0
                                opt_symbol = f"{sym}_ATM_{int(atm_strike)}_CE"
                                opt_entry_prem = estimate_atm_option_premium(cur_price) * (1.0 + SLIPPAGE_PCT)

                                order_book.append({
                                    "order_id": order_id,
                                    "timestamp": ts,
                                    "symbol": sym,
                                    "contract": opt_symbol,
                                    "action": "BUY",
                                    "quantity": lot_size,
                                    "premium": round(opt_entry_prem, 2),
                                    "status": "FILLED",
                                    "reason": f"Buy CE on Gap Down Reversal ({gap_pct:.2f}%)"
                                })
                                order_id += 1

                                open_positions[sym] = {
                                    "option_symbol": opt_symbol,
                                    "contract_type": "CE",
                                    "entry_time": ts,
                                    "spot_entry": cur_price,
                                    "spot_stop": spot_stop,
                                    "spot_target": spot_target,
                                    "opt_entry_premium": opt_entry_prem,
                                    "lot_size": lot_size
                                }
                                stock_trade_count[sym] += 1
                                available_slots -= 1
                                continue

                    # ---------------------------------------------------------
                    # Signal 2: BUY ATM PUT (PE) on Gap Up Reversal
                    # ---------------------------------------------------------
                    if (prev_close < prev_ema20) and (MIN_GAP_PCT <= gap_pct <= MAX_GAP_PCT):
                        if (cur_price < first_1h_low) and (cur_price <= cur_vwap):
                            spot_stop = opening_high * 1.0005
                            spot_risk = spot_stop - cur_price
                            if spot_risk > 0:
                                spot_target = max(prev_close, cur_price - (TARGET_R_MULT * spot_risk))
                                atm_strike = round(cur_price / 10.0) * 10.0
                                opt_symbol = f"{sym}_ATM_{int(atm_strike)}_PE"
                                opt_entry_prem = estimate_atm_option_premium(cur_price) * (1.0 + SLIPPAGE_PCT)

                                order_book.append({
                                    "order_id": order_id,
                                    "timestamp": ts,
                                    "symbol": sym,
                                    "contract": opt_symbol,
                                    "action": "BUY",
                                    "quantity": lot_size,
                                    "premium": round(opt_entry_prem, 2),
                                    "status": "FILLED",
                                    "reason": f"Buy PE on Gap Up Reversal (+{gap_pct:.2f}%)"
                                })
                                order_id += 1

                                open_positions[sym] = {
                                    "option_symbol": opt_symbol,
                                    "contract_type": "PE",
                                    "entry_time": ts,
                                    "spot_entry": cur_price,
                                    "spot_stop": spot_stop,
                                    "spot_target": spot_target,
                                    "opt_entry_premium": opt_entry_prem,
                                    "lot_size": lot_size
                                }
                                stock_trade_count[sym] += 1
                                available_slots -= 1
                                continue

    return pd.DataFrame(order_book), pd.DataFrame(trade_logs)


if __name__ == "__main__":
    t0 = time.time()
    print("Downloading 1-hour candles for 250 trading days...")
    tickers = [f"{s}.NS" for s in NIFTY_50_STOCKS]
    raw = yf.download(tickers, period="250d", interval="1h", group_by="ticker", progress=False)

    stock_dfs = {}
    for sym in NIFTY_50_STOCKS:
        tk = f"{sym}.NS"
        if tk in raw.columns.levels[0]:
            df = raw[tk].dropna(how='all').copy()
            if df.empty or len(df) < 50:
                continue
            df.columns = [c.lower() for c in df.columns]
            df['timestamp'] = pd.to_datetime(df.index)
            if df['timestamp'].dt.tz is not None:
                df['timestamp'] = df['timestamp'].dt.tz_localize(None)
            stock_dfs[sym] = df.sort_values('timestamp').reset_index(drop=True)

    print(f"Loaded {len(stock_dfs)} stocks.")
    order_book_df, trade_logs_df = run_twoside_option_buying_backtest(stock_dfs)

    out_dir = "openalgo/workspace/backtests"
    os.makedirs(out_dir, exist_ok=True)

    ob_path = os.path.join(out_dir, "order_book_gap_options_twoside_1h_250d.csv")
    tl_path = os.path.join(out_dir, "trade_logs_gap_options_twoside_1h_250d.csv")
    np_path = os.path.join(out_dir, "net_positions_gap_options_twoside_1h_250d.csv")

    order_book_df.to_csv(ob_path, index=False)
    trade_logs_df.to_csv(tl_path, index=False)

    total_trades = len(trade_logs_df)
    print("\n" + "=" * 75)
    print(" STRATEGY 1: TWO-SIDED OPTION BUYING (BUY CE & BUY PE) - 1H, 250 DAYS")
    print("=" * 75)
    print(f"Total Orders Executed : {len(order_book_df)}")
    print(f"Total Completed Trades: {total_trades}")

    if not trade_logs_df.empty:
        print("\nBreakdown by Type:")
        print(trade_logs_df['type'].value_counts().to_string())

        total_gross = trade_logs_df['gross_pnl'].sum()
        total_charges = trade_logs_df['charges'].sum()
        total_net = trade_logs_df['net_pnl'].sum()
        total_r = trade_logs_df['r_multiple'].sum()
        avg_r = trade_logs_df['r_multiple'].mean()
        wins = trade_logs_df[trade_logs_df['net_pnl'] > 0]
        losses = trade_logs_df[trade_logs_df['net_pnl'] <= 0]
        win_rate = (len(wins) / len(trade_logs_df)) * 100.0

        gp = wins['net_pnl'].sum() if not wins.empty else 0.0
        gl = abs(losses['net_pnl'].sum()) if not losses.empty else 0.0
        pf = (gp / gl) if gl > 0 else np.nan

        avg_capital = trade_logs_df['capital_invested'].mean()

        print(f"\nAverage Option Premium Paid/Trade: Rs {avg_capital:,.2f}")
        print(f"Win Rate (Net)                  : {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
        print(f"Gross P&L                       : Rs {total_gross:,.2f}")
        print(f"Total Brokerage & F&O Taxes     : Rs {total_charges:,.2f} (~Rs {trade_logs_df['charges'].mean():.2f}/trade)")
        print(f"Net P&L (After All Taxes)       : Rs {total_net:,.2f}")
        print(f"Total Return (R)                : {total_r:+.2f} R")
        print(f"Average R / Trade               : {avg_r:+.3f} R")
        if not np.isnan(pf):
            print(f"Net Profit Factor               : {pf:.2f}")

        print("\nExit Triggers Breakdown:")
        print(trade_logs_df['reason'].value_counts().to_string())

    print("\n" + "=" * 75)
    print(f" 1. Order Book   : {ob_path}")
    print(f" 2. Trade Log    : {tl_path}")
    print("=" * 75)
    print(f"Completed in {round(time.time() - t0, 1)}s")
