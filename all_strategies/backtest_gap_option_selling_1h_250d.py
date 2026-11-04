#!/usr/bin/env python3
"""
Backtest Engine: Strategy 1 (Overnight Gap Mean Reversion) - OPTION SELLING (Theta Decay)
Capitalizes on Mean Reversion + Time Decay (Theta).

Logic:
------
1. GAP DOWN REVERSAL (Bullish Setup):
   - Stock opens gap down 0.5% - 2.0% while daily trend is UP (Prev Close > 20 EMA).
   - Price breaks above first 1-hour candle high and stays above VWAP.
   - Action: SELL At-The-Money (ATM) PUT Option (PE).
   - Why it works: As stock recovers, PE Delta falls AND Theta decays -> DOUBLE PROFIT.
   - Stop Loss: 30% increase in PE premium OR Spot breaks opening low.
   - Target: Spot fills gap OR 50% decay in PE premium.

2. GAP UP REVERSAL (Bearish Setup):
   - Stock opens gap up 0.5% - 2.0% while daily trend is DOWN (Prev Close < 20 EMA).
   - Price breaks below first 1-hour candle low and stays below VWAP.
   - Action: SELL At-The-Money (ATM) CALL Option (CE).
   - Why it works: As stock reverses downwards, CE Delta falls AND Theta decays -> DOUBLE PROFIT.
   - Stop Loss: 30% increase in CE premium OR Spot breaks opening high.
   - Target: Spot fills gap OR 50% decay in CE premium.

Exit Rules:
- Intraday square-off at 15:15 (captures maximum intraday theta decay).
- F&O transaction charges & brokerages deducted.
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
PREMIUM_STOP_LOSS_PCT = 0.30  # Stop loss at 30% adverse premium move
PREMIUM_TARGET_PROFIT_PCT = 0.50  # Take profit at 50% premium decay
TARGET_R_MULT = 1.5

MARKET_OPEN_TIME = dtime(9, 15)
FIRST_1H_END_TIME = dtime(10, 15)
ENTRY_END_TIME = dtime(14, 30)
SQUARE_OFF_TIME = dtime(15, 15)
MIN_GAP_PCT = 0.5
MAX_GAP_PCT = 2.0
SLIPPAGE_PCT = 0.01

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
    stt = (premium_entry * qty) * 0.001  # STT is on Sell side
    exchange_txn = turnover * 0.0005
    sebi_fee = turnover * 0.000001
    stamp_duty = (premium_exit * qty) * 0.00003  # Stamp duty on Buy side
    gst = (brokerage + exchange_txn + sebi_fee) * 0.18
    return round(brokerage + stt + exchange_txn + sebi_fee + stamp_duty + gst, 2)


def estimate_atm_option_premium(spot_price, iv=0.25, dte=15):
    time_to_exp = max(dte, 1) / 365.0
    return max(1.0, 0.40 * spot_price * iv * math.sqrt(time_to_exp))


def run_option_selling_backtest(stock_dfs):
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
        # 1. MANAGE OPEN SHORT OPTION POSITIONS
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
            contract_type = pos['contract_type']  # 'PE' or 'CE'

            # Intraday Theta Decay (~3% to 5% across holding hours)
            hours_held = max(1, (ts - pos['entry_time']).seconds // 3600)
            theta_decay = opt_entry_prem * (0.007 * hours_held)

            # Option price dynamics:
            # If we sold PE (bullish): Spot rising -> PE price drops (profit)
            # If we sold CE (bearish): Spot dropping -> CE price drops (profit)
            delta = 0.50
            if contract_type == 'PE':
                spot_diff = spot_cur - spot_entry
                cur_option_prem = max(0.05, opt_entry_prem - (spot_diff * delta) - theta_decay)
            else:
                spot_diff = spot_entry - spot_cur
                cur_option_prem = max(0.05, opt_entry_prem - (spot_diff * delta) - theta_decay)

            exit_prem = None
            exit_reason = None

            # As an Option Seller: We want the premium to DECREASE
            # Stop loss triggers if option premium expands by +30%
            if cur_option_prem >= (opt_entry_prem * (1.0 + PREMIUM_STOP_LOSS_PCT)):
                exit_prem = opt_entry_prem * (1.0 + PREMIUM_STOP_LOSS_PCT) * (1.0 + SLIPPAGE_PCT)
                exit_reason = "Option 30% Premium Stop Loss Hit"

            # Spot Target Reached (Gap filled)
            elif (contract_type == 'PE' and bar['high'] >= pos['spot_target']) or \
                 (contract_type == 'CE' and bar['low'] <= pos['spot_target']):
                # Spot reached target, premium decayed significantly
                favorable_move = abs(pos['spot_target'] - spot_entry)
                exit_prem = max(0.05, (opt_entry_prem - (favorable_move * delta) - theta_decay)) * (1.0 + SLIPPAGE_PCT)
                exit_reason = "Spot Target Reached (Gap Fill)"

            # Target 50% Theta Decay Reached
            elif cur_option_prem <= (opt_entry_prem * (1.0 - PREMIUM_TARGET_PROFIT_PCT)):
                exit_prem = opt_entry_prem * (1.0 - PREMIUM_TARGET_PROFIT_PCT) * (1.0 + SLIPPAGE_PCT)
                exit_reason = "50% Theta Decay Target Hit"

            # Spot Stop Hit
            elif (contract_type == 'PE' and bar['low'] <= pos['spot_stop']) or \
                 (contract_type == 'CE' and bar['high'] >= pos['spot_stop']):
                adverse_move = abs(pos['spot_stop'] - spot_entry)
                exit_prem = (opt_entry_prem + (adverse_move * delta) - theta_decay) * (1.0 + SLIPPAGE_PCT)
                exit_reason = "Spot Stop Level Hit"

            # Intraday Square-off at 15:15
            elif bar_t >= SQUARE_OFF_TIME:
                exit_prem = cur_option_prem * (1.0 + SLIPPAGE_PCT)
                exit_reason = "Square-off at 15:15 (Max Theta Decay Captured)"

            if exit_prem is not None:
                # Order Book: BUY back the short option
                order_book.append({
                    "order_id": order_id,
                    "timestamp": ts,
                    "symbol": sym,
                    "contract": pos['option_symbol'],
                    "action": "BUY",
                    "quantity": lot_size,
                    "premium": round(exit_prem, 2),
                    "status": "FILLED",
                    "reason": exit_reason
                })
                order_id += 1

                # Profit for Option Seller = (Sell Price - Buy Price) * Qty
                gross_pnl = (opt_entry_prem - exit_prem) * lot_size
                charges = calculate_fno_charges(opt_entry_prem, exit_prem, lot_size)
                net_pnl = gross_pnl - charges
                risk_amt = opt_entry_prem * PREMIUM_STOP_LOSS_PCT * lot_size
                r_mult = gross_pnl / risk_amt if risk_amt > 0 else 0.0

                # Margin requirement for selling 1 lot of stock option in India is approx Rs 1.2 Lakhs
                margin_used = 120000.0

                trade_logs.append({
                    "trade_id": len(trade_logs) + 1,
                    "symbol": sym,
                    "contract": pos['option_symbol'],
                    "type": f"SELL {contract_type}",
                    "entry_time": pos['entry_time'],
                    "opt_sell_premium": round(opt_entry_prem, 2),
                    "exit_time": ts,
                    "opt_buy_premium": round(exit_prem, 2),
                    "lot_size": lot_size,
                    "margin_required": margin_used,
                    "gross_pnl": round(gross_pnl, 2),
                    "charges": charges,
                    "net_pnl": round(net_pnl, 2),
                    "r_multiple": round(r_mult, 2),
                    "reason": exit_reason
                })
                closed_symbols.append(sym)

        for sym in closed_symbols:
            del open_positions[sym]

        # -------------------------------------------------------------
        # 2. EVALUATE SHORT OPTION ENTRIES (10:15 to 14:30)
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
                    # Setup 1: SELL ATM PUT (PE) on Gap Down Reversal
                    # ---------------------------------------------------------
                    if (prev_close > prev_ema20) and (-MAX_GAP_PCT <= gap_pct <= -MIN_GAP_PCT):
                        if (cur_price > first_1h_high) and (cur_price >= cur_vwap):
                            spot_stop = opening_low * 0.9995
                            spot_risk = cur_price - spot_stop
                            if spot_risk > 0:
                                spot_target = min(prev_close, cur_price + (TARGET_R_MULT * spot_risk))
                                atm_strike = round(cur_price / 10.0) * 10.0
                                opt_symbol = f"{sym}_ATM_{int(atm_strike)}_PE"
                                opt_entry_prem = estimate_atm_option_premium(cur_price) * (1.0 - SLIPPAGE_PCT)

                                # Record SELL in Order Book
                                order_book.append({
                                    "order_id": order_id,
                                    "timestamp": ts,
                                    "symbol": sym,
                                    "contract": opt_symbol,
                                    "action": "SELL",
                                    "quantity": lot_size,
                                    "premium": round(opt_entry_prem, 2),
                                    "status": "FILLED",
                                    "reason": f"Sell PE on Gap Down Reversal ({gap_pct:.2f}%)"
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

                    # ---------------------------------------------------------
                    # Setup 2: SELL ATM CALL (CE) on Gap Up Reversal
                    # ---------------------------------------------------------
                    if (prev_close < prev_ema20) and (MIN_GAP_PCT <= gap_pct <= MAX_GAP_PCT):
                        if (cur_price < first_1h_low) and (cur_price <= cur_vwap):
                            spot_stop = opening_high * 1.0005
                            spot_risk = spot_stop - cur_price
                            if spot_risk > 0:
                                spot_target = max(prev_close, cur_price - (TARGET_R_MULT * spot_risk))
                                atm_strike = round(cur_price / 10.0) * 10.0
                                opt_symbol = f"{sym}_ATM_{int(atm_strike)}_CE"
                                opt_entry_prem = estimate_atm_option_premium(cur_price) * (1.0 - SLIPPAGE_PCT)

                                # Record SELL in Order Book
                                order_book.append({
                                    "order_id": order_id,
                                    "timestamp": ts,
                                    "symbol": sym,
                                    "contract": opt_symbol,
                                    "action": "SELL",
                                    "quantity": lot_size,
                                    "premium": round(opt_entry_prem, 2),
                                    "status": "FILLED",
                                    "reason": f"Sell CE on Gap Up Reversal (+{gap_pct:.2f}%)"
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
    order_book_df, trade_logs_df = run_option_selling_backtest(stock_dfs)

    out_dir = "openalgo/workspace/backtests"
    os.makedirs(out_dir, exist_ok=True)

    ob_path = os.path.join(out_dir, "order_book_gap_option_selling_1h_250d.csv")
    tl_path = os.path.join(out_dir, "trade_logs_gap_option_selling_1h_250d.csv")
    np_path = os.path.join(out_dir, "net_positions_gap_option_selling_1h_250d.csv")

    order_book_df.to_csv(ob_path, index=False)
    trade_logs_df.to_csv(tl_path, index=False)

    if not trade_logs_df.empty:
        summary = trade_logs_df.groupby("symbol").agg(
            trades=('net_pnl', 'count'),
            wins=('net_pnl', lambda x: (x > 0).sum()),
            losses=('net_pnl', lambda x: (x <= 0).sum()),
            gross_pnl=('gross_pnl', 'sum'),
            charges=('charges', 'sum'),
            net_pnl=('net_pnl', 'sum'),
            total_r=('r_multiple', 'sum'),
            avg_pnl=('net_pnl', 'mean')
        ).reset_index()
        summary['win_rate_%'] = round((summary['wins'] / summary['trades']) * 100.0, 1)
        summary = summary.round(2)
        summary.to_csv(np_path, index=False)

    print("\n" + "=" * 75)
    print(" STRATEGY 1: GAP REVERSION - OPTION SELLER (THETA DECAY) (1H, 250 DAYS)")
    print("=" * 75)
    print(f"Total Orders Executed : {len(order_book_df)}")
    print(f"Total Completed Trades: {len(trade_logs_df)}")

    if not trade_logs_df.empty:
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

        print("\nTop 5 Performing Stocks (Option Selling):")
        print(summary.sort_values(by="net_pnl", ascending=False).head(5).to_string(index=False))

        print("\nBottom 5 Performing Stocks (Option Selling):")
        print(summary.sort_values(by="net_pnl", ascending=True).head(5).to_string(index=False))

    print("\n" + "=" * 75)
    print(f" 1. Order Book   : {ob_path}")
    print(f" 2. Trade Log    : {tl_path}")
    print(f" 3. Net Positions: {np_path}")
    print("=" * 75)
    print(f"Completed in {round(time.time() - t0, 1)}s")
