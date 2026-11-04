#!/usr/bin/env python3
"""
Multi-Timeframe Comparison Backtest Engine
Strategy 1: Overnight Gap Mean Reversion (Intraday Long/Short)
Capital: Rs 10,000 per trade
Universe: 50 Nifty Stocks
Timeframes Tested:
  - 1 Hour (Tested across 250 days, and common 58 days)
  - 15 Min (Tested across available 58 days)
  - 5 Min  (Tested across available 58 days)
Outputs side-by-side comparison tables.
"""

import os
import sys
import time
from datetime import datetime, time as dtime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf

CAPITAL_PER_TRADE = 10000.0  # Rs 10,000 per trade
MAX_PORTFOLIO_POSITIONS = 10
MAX_TRADES_PER_STOCK = 2
MIN_GAP_PCT = 0.5
MAX_GAP_PCT = 2.0
TARGET_R_MULT = 1.5

MARKET_OPEN_TIME = dtime(9, 15)
ENTRY_END_TIME = dtime(14, 30)
SQUARE_OFF_TIME = dtime(15, 15)
SLIPPAGE_PCT = 0.0005  # 0.05% slippage

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

def calculate_mis_charges(entry_val, exit_val):
    turnover = entry_val + exit_val
    buy_brok = min(20.0, entry_val * 0.0003)
    sell_brok = min(20.0, exit_val * 0.0003)
    total_brok = buy_brok + sell_brok
    stt = exit_val * 0.00025
    exchange_txn = turnover * 0.0000297
    sebi_fee = turnover * 0.000001
    stamp_duty = entry_val * 0.00003
    gst = (total_brok + exchange_txn + sebi_fee) * 0.18
    return round(total_brok + stt + exchange_txn + sebi_fee + stamp_duty + gst, 2)


def fetch_interval_data(symbols, interval, period):
    print(f"Downloading {interval} data (period={period})...")
    tickers = [f"{s}.NS" for s in symbols]
    raw = yf.download(tickers, period=period, interval=interval, group_by='ticker', progress=False)

    stock_dfs = {}
    for sym in symbols:
        ticker = f"{sym}.NS"
        try:
            if ticker in raw.columns.levels[0]:
                df = raw[ticker].dropna(how='all').copy()
                if df.empty or len(df) < 50:
                    continue
                df.columns = [c.lower() for c in df.columns]
                df['timestamp'] = pd.to_datetime(df.index)
                if df['timestamp'].dt.tz is not None:
                    df['timestamp'] = df['timestamp'].dt.tz_localize(None)
                df = df.sort_values('timestamp').reset_index(drop=True)
                stock_dfs[sym] = df
        except Exception:
            continue
    print(f"Loaded {len(stock_dfs)} stocks for {interval}.")
    return stock_dfs


def run_simulation(stock_dfs, interval_name):
    # Daily statistics & VWAP computation
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

        # Cumulative intraday VWAP
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3.0
        df['cum_pv'] = df.groupby('date')['typical_price'].transform(lambda x: (x * df.loc[x.index, 'volume']).cumsum())
        df['cum_v'] = df.groupby('date')['volume'].cumsum()
        df['vwap'] = df['cum_pv'] / df['cum_v'].replace(0, np.nan)

    # Master timeline
    all_timestamps = sorted(list(set(
        ts for df in stock_dfs.values() for ts in df['timestamp']
    )))

    data_by_stock = {sym: df.set_index('timestamp') for sym, df in stock_dfs.items()}
    open_positions = {}
    stock_trade_count = {sym: 0 for sym in stock_dfs.keys()}
    current_day = None

    trade_logs = []
    order_id = 1

    for ts in all_timestamps:
        bar_date = ts.date()
        bar_t = ts.time()

        if bar_date != current_day:
            current_day = bar_date
            stock_trade_count = {sym: 0 for sym in stock_dfs.keys()}

        # 1. Manage Exits
        closed_symbols = []
        for sym, pos in list(open_positions.items()):
            df_stock = data_by_stock.get(sym)
            if df_stock is None or ts not in df_stock.index:
                continue

            bar = df_stock.loc[ts]
            action = pos['action']
            entry_price = pos['entry_price']
            stop_price = pos['stop_loss']
            target_price = pos['target']
            qty = pos['quantity']

            exit_price = None
            exit_reason = None

            if action == "BUY":
                if bar['low'] <= stop_price:
                    exit_price = min(bar['open'], stop_price) * (1.0 - SLIPPAGE_PCT)
                    exit_reason = "Stop Loss"
                elif bar['high'] >= target_price:
                    exit_price = max(bar['open'], target_price) * (1.0 - SLIPPAGE_PCT)
                    exit_reason = "Target Hit"
                elif bar_t >= SQUARE_OFF_TIME:
                    exit_price = bar['close'] * (1.0 - SLIPPAGE_PCT)
                    exit_reason = "Square-off 15:15"

            elif action == "SELL":
                if bar['high'] >= stop_price:
                    exit_price = max(bar['open'], stop_price) * (1.0 + SLIPPAGE_PCT)
                    exit_reason = "Stop Loss"
                elif bar['low'] <= target_price:
                    exit_price = min(bar['open'], target_price) * (1.0 + SLIPPAGE_PCT)
                    exit_reason = "Target Hit"
                elif bar_t >= SQUARE_OFF_TIME:
                    exit_price = bar['close'] * (1.0 + SLIPPAGE_PCT)
                    exit_reason = "Square-off 15:15"

            if exit_price is not None:
                entry_val = entry_price * qty
                exit_val = exit_price * qty
                gross_pnl = (exit_price - entry_price) * qty if action == "BUY" else (entry_price - exit_price) * qty
                charges = calculate_mis_charges(entry_val, exit_val)
                net_pnl = gross_pnl - charges
                r_mult = gross_pnl / (pos['initial_risk'] * qty) if pos['initial_risk'] > 0 else 0.0

                trade_logs.append({
                    "symbol": sym,
                    "direction": action,
                    "entry_time": pos['entry_time'],
                    "entry_price": round(entry_price, 2),
                    "exit_time": ts,
                    "exit_price": round(exit_price, 2),
                    "quantity": qty,
                    "trade_value": round(entry_val, 2),
                    "gross_pnl": round(gross_pnl, 2),
                    "charges": charges,
                    "net_pnl": round(net_pnl, 2),
                    "r_multiple": round(r_mult, 2),
                    "reason": exit_reason
                })
                closed_symbols.append(sym)

        for sym in closed_symbols:
            del open_positions[sym]

        # 2. Evaluate Entries
        # First candle cutoff: 09:30 for 5m/15m, 10:15 for 1h
        first_candle_cutoff = dtime(10, 15) if interval_name == "1h" else dtime(9, 30)

        if first_candle_cutoff <= bar_t <= ENTRY_END_TIME:
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

                    # Filter opening candle
                    df_day = df_stock[df_stock['date'] == bar_date]
                    df_opening = df_day[df_day.index.time < first_candle_cutoff]
                    if df_opening.empty:
                        continue

                    first_high = df_opening['high'].max()
                    first_low = df_opening['low'].min()
                    opening_low = df_opening['low'].min()
                    opening_high = df_opening['high'].max()

                    bar = df_stock.loc[ts]
                    cur_price = bar['close']
                    cur_vwap = bar['vwap'] if not pd.isna(bar['vwap']) else cur_price

                    qty = max(1, int(CAPITAL_PER_TRADE / cur_price))

                    # Long (Gap Down Reversion)
                    if (prev_close > prev_ema20) and (-MAX_GAP_PCT <= gap_pct <= -MIN_GAP_PCT):
                        if (cur_price > first_high) and (cur_price >= cur_vwap):
                            stop_loss = opening_low * 0.9995
                            risk = cur_price - stop_loss
                            if risk > 0:
                                target = min(prev_close, cur_price + (TARGET_R_MULT * risk))
                                fill_price = bar['open'] * (1.0 + SLIPPAGE_PCT)
                                open_positions[sym] = {
                                    "action": "BUY",
                                    "entry_time": ts,
                                    "entry_price": fill_price,
                                    "quantity": qty,
                                    "stop_loss": stop_loss,
                                    "target": target,
                                    "initial_risk": risk
                                }
                                stock_trade_count[sym] += 1
                                available_slots -= 1
                                continue

                    # Short (Gap Up Reversion)
                    if (prev_close < prev_ema20) and (MIN_GAP_PCT <= gap_pct <= MAX_GAP_PCT):
                        if (cur_price < first_low) and (cur_price <= cur_vwap):
                            stop_loss = opening_high * 1.0005
                            risk = stop_loss - cur_price
                            if risk > 0:
                                target = max(prev_close, cur_price - (TARGET_R_MULT * risk))
                                fill_price = bar['open'] * (1.0 - SLIPPAGE_PCT)
                                open_positions[sym] = {
                                    "action": "SELL",
                                    "entry_time": ts,
                                    "entry_price": fill_price,
                                    "quantity": qty,
                                    "stop_loss": stop_loss,
                                    "target": target,
                                    "initial_risk": risk
                                }
                                stock_trade_count[sym] += 1
                                available_slots -= 1
                                continue

    return pd.DataFrame(trade_logs)


def summarize(df_trades, label):
    if df_trades.empty:
        return {
            "Timeframe": label, "Trades": 0, "Win Rate %": "0.0%", "Gross PnL": 0,
            "Taxes/Brok": 0, "Net PnL": 0, "Profit Factor": "0.0", "Total R": "0.0"
        }
    wins = df_trades[df_trades['net_pnl'] > 0]
    losses = df_trades[df_trades['net_pnl'] <= 0]
    win_rate = (len(wins) / len(df_trades)) * 100.0
    gross_pnl = df_trades['gross_pnl'].sum()
    charges = df_trades['charges'].sum()
    net_pnl = df_trades['net_pnl'].sum()
    total_r = df_trades['r_multiple'].sum()
    gp = wins['net_pnl'].sum() if not wins.empty else 0.0
    gl = abs(losses['net_pnl'].sum()) if not losses.empty else 0.0
    pf = (gp / gl) if gl > 0 else np.nan

    return {
        "Timeframe": label,
        "Trades": len(df_trades),
        "Win Rate %": f"{win_rate:.1f}%",
        "Gross PnL": round(gross_pnl, 2),
        "Taxes/Brok": round(charges, 2),
        "Net PnL": round(net_pnl, 2),
        "Profit Factor": f"{pf:.2f}" if not np.isnan(pf) else "Inf",
        "Total R": f"{total_r:+.2f} R"
    }


if __name__ == "__main__":
    t0 = time.time()
    results = []

    out_dir = "openalgo/workspace/backtests"
    os.makedirs(out_dir, exist_ok=True)

    # 1. Test 1-Hour across 250 Days
    print("\n" + "=" * 60)
    print(" 1. TESTING 1-HOUR (250 DAYS)")
    print("=" * 60)
    dfs_1h_250d = fetch_interval_data(NIFTY_50_STOCKS, interval="1h", period="250d")
    trades_1h_250d = run_simulation(dfs_1h_250d, "1h")
    trades_1h_250d.to_csv(os.path.join(out_dir, "trades_gap_1h_250d.csv"), index=False)
    results.append(summarize(trades_1h_250d, "1-Hour (250 Days)"))

    # 2. Test 1-Hour across Common 58 Days
    dfs_1h_58d = fetch_interval_data(NIFTY_50_STOCKS, interval="1h", period="58d")
    trades_1h_58d = run_simulation(dfs_1h_58d, "1h")
    trades_1h_58d.to_csv(os.path.join(out_dir, "trades_gap_1h_58d.csv"), index=False)
    results.append(summarize(trades_1h_58d, "1-Hour (Common 58d)"))

    # 3. Test 15-Min across 58 Days
    print("\n" + "=" * 60)
    print(" 2. TESTING 15-MINUTE (58 DAYS)")
    print("=" * 60)
    dfs_15m_58d = fetch_interval_data(NIFTY_50_STOCKS, interval="15m", period="58d")
    trades_15m_58d = run_simulation(dfs_15m_58d, "15m")
    trades_15m_58d.to_csv(os.path.join(out_dir, "trades_gap_15m_58d.csv"), index=False)
    results.append(summarize(trades_15m_58d, "15-Min (58 Days)"))

    # 4. Test 5-Min across 58 Days
    print("\n" + "=" * 60)
    print(" 3. TESTING 5-MINUTE (58 DAYS)")
    print("=" * 60)
    dfs_5m_58d = fetch_interval_data(NIFTY_50_STOCKS, interval="5m", period="58d")
    trades_5m_58d = run_simulation(dfs_5m_58d, "5m")
    trades_5m_58d.to_csv(os.path.join(out_dir, "trades_gap_5m_58d.csv"), index=False)
    results.append(summarize(trades_5m_58d, "5-Min (58 Days)"))

    # Output Summary Table
    df_res = pd.DataFrame(results)
    df_res.to_csv(os.path.join(out_dir, "comparison_gap_mean_reversion_timeframes.csv"), index=False)

    print("\n" + "=" * 80)
    print(" STRATEGY 1 (GAP REVERSION) TIMEFRAME COMPARISON TABLE (Trade Size = Rs 10,000)")
    print("=" * 80)
    print(df_res.to_string(index=False))
    print("=" * 80)
    print(f"Total time elapsed: {round(time.time() - t0, 1)}s")
