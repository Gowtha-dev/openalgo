#!/usr/bin/env python3
"""
================================================================================
BACKTEST ENGINE: SUPERTREND (10, 3) + 50 EMA TREND FILTER STRATEGY
Timeframes Tested: 5-Minute, 15-Minute, 1-Hour Candles
Universe: Liquid NSE NIFTY 50 Equities
Period: Past 250 Trading Days (or max available intraday data)
Capital per Trade: ₹50,000 | Slippage: 0.05% | Brokerage: ₹20/order
================================================================================

RULES:
------
BUY SIGNAL:
  1. Supertrend (10, 3) flips from bearish to bullish.
  2. Candle Close > 50 EMA.
  3. RSI(14) > 50.
  4. Enter at the NEXT candle's Open.

SELL / EXIT SIGNAL:
  1. Supertrend flips from bullish to bearish.
  2. OR Price closes below 20-period Low.
  3. Optional Trailing Stop: 2x ATR below highest close since entry.
================================================================================
"""

import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, time as dtime

NSE_LIQUID_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL", "SBIN",
    "ITC", "HINDUNILVR", "LT", "BAJFINANCE", "HCLTECH", "MARUTI", "SUNPHARMA",
    "ADANIENT", "KOTAKBANK", "TITAN", "ONGC", "NTPC", "AXISBANK",
    "ADANIPORTS", "COALINDIA", "POWERGRID", "M&M", "BAJAJFINSV", "ULTRACEMCO",
    "TATASTEEL", "ASIANPAINT", "JSWSTEEL", "GRASIM", "TECHM",
    "HINDALCO", "NESTLEIND", "DRREDDY", "WIPRO", "BPCL", "CIPLA", "EICHERMOT",
    "BRITANNIA", "BAJAJ-AUTO", "APOLLOHOSP", "SHRIRAMFIN", "BEL", "TRENT",
    "TATACONSUM", "SBILIFE", "HDFCLIFE"
]

CAPITAL_PER_TRADE = 50000.0
SLIPPAGE_PCT = 0.0005
COMMISSION_PER_ORDER = 20.0

def calculate_supertrend(df, period=10, multiplier=3.0):
    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values
    n = len(df)
    
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
        
    atr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
    
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)
    
    final_upper = np.zeros(n)
    final_lower = np.zeros(n)
    supertrend = np.zeros(n)
    trend = np.zeros(n, dtype=int)
    
    for i in range(1, n):
        if basic_lower[i] > final_lower[i-1] or close[i-1] < final_lower[i-1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i-1]
            
        if basic_upper[i] < final_upper[i-1] or close[i-1] > final_upper[i-1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i-1]
            
        if i == 1:
            trend[i] = 1 if close[i] > final_upper[i] else -1
            supertrend[i] = final_lower[i] if trend[i] == 1 else final_upper[i]
            continue
            
        if trend[i-1] == 1:
            if close[i] < final_lower[i]:
                trend[i] = -1
                supertrend[i] = final_upper[i]
            else:
                trend[i] = 1
                supertrend[i] = final_lower[i]
        else:
            if close[i] > final_upper[i]:
                trend[i] = 1
                supertrend[i] = final_lower[i]
            else:
                trend[i] = -1
                supertrend[i] = final_upper[i]
                
    df['supertrend'] = supertrend
    df['trend'] = trend
    df['atr'] = atr
    return df

def compute_indicators(df):
    df = df.copy()
    df = calculate_supertrend(df, period=10, multiplier=3.0)
    df['ema50'] = df['Close'].ewm(span=50, adjust=False).mean()
    delta = df['Close'].diff()
    gain = delta.clip(lower=0); loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    df['low20'] = df['Low'].shift(1).rolling(window=20).min()
    return df

def backtest_single_stock(df, symbol, use_trail_stop=True):
    n = len(df)
    if n < 60: return []
    trades = []
    in_pos = False
    cur_trade = None
    times = df.index
    
    for i in range(55, n - 1):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        next_row = df.iloc[i+1]
        
        if in_pos:
            highest_close = max(cur_trade['highest_close'], row['Close'])
            cur_trade['highest_close'] = highest_close
            trail_stop = highest_close - (2.0 * row['atr'])
            
            exit_price = None
            exit_reason = None
            
            # Exit 1: Supertrend flips bearish
            if row['trend'] == -1 and prev_row['trend'] == 1:
                exit_price = next_row['Open'] * (1 - SLIPPAGE_PCT)
                exit_reason = 'SUPERTREND_FLIP_BEAR'
            # Exit 2: Price closes below 20-period low
            elif row['Close'] < row['low20']:
                exit_price = next_row['Open'] * (1 - SLIPPAGE_PCT)
                exit_reason = 'BREAK_20_LOW'
            # Exit 3: Price hits trailing stop (2x ATR) if enabled
            elif use_trail_stop and row['Low'] <= trail_stop:
                exit_price = trail_stop * (1 - SLIPPAGE_PCT)
                exit_reason = 'TRAIL_STOP_2ATR'
                
            if exit_price is not None:
                ep = cur_trade['entry_price']
                sh = cur_trade['shares']
                pnl = (exit_price - ep) * sh - (2 * COMMISSION_PER_ORDER)
                r_pnl = (exit_price - ep) / cur_trade['initial_risk_per_share']
                cur_trade.update({
                    'exit_time': times[i+1],
                    'exit_price': exit_price,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'r_pnl': r_pnl,
                    'holding_candles': (i + 1) - cur_trade['entry_idx']
                })
                trades.append(cur_trade)
                in_pos = False; cur_trade = None
            if in_pos: continue
            
        st_flipped_bull = (row['trend'] == 1 and prev_row['trend'] == -1)
        if st_flipped_bull and (row['Close'] > row['ema50']) and (row['rsi'] > 50):
            ep = next_row['Open'] * (1 + SLIPPAGE_PCT)
            initial_sl = min(row['supertrend'], ep - (2.0 * row['atr']))
            initial_risk = ep - initial_sl
            if initial_risk > ep * 0.002 and initial_risk < ep * 0.06:
                sh = int(CAPITAL_PER_TRADE / ep)
                if sh > 0:
                    in_pos = True
                    cur_trade = {
                        'symbol': symbol,
                        'direction': 'LONG',
                        'entry_time': times[i+1],
                        'entry_idx': i + 1,
                        'entry_price': ep,
                        'initial_sl': initial_sl,
                        'initial_risk_per_share': initial_risk,
                        'highest_close': row['Close'],
                        'shares': sh,
                        'capital': sh * ep
                    }
    return trades

def run_evaluation():
    print("=" * 80)
    print("SUPERTREND + 50 EMA TREND FILTER MULTI-TIMEFRAME EVALUATION (5M, 15M, 1H)")
    print("=" * 80)
    
    configs = [
        ("1-Hour (Standard 2x ATR Trail)", "1h", "730d", True),
        ("1-Hour (Pure Trend: ST Flip & 20-Low Exit)", "1h", "730d", False),
        ("15-Minute (Standard 2x ATR Trail)", "15m", "60d", True),
        ("15-Minute (Pure Trend: ST Flip & 20-Low Exit)", "15m", "60d", False),
        ("5-Minute (Standard 2x ATR Trail)", "5m", "60d", True),
        ("5-Minute (Pure Trend: ST Flip & 20-Low Exit)", "5m", "60d", False),
    ]
    
    summary = []
    
    for label, interval, period, use_trail in configs:
        print(f"\nProcessing: {label}...")
        all_trades = []
        for sym in NSE_LIQUID_STOCKS:
            try:
                df = yf.download(f"{sym}.NS", period=period, interval=interval, progress=False)
                if df.empty or len(df) < 80: continue
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
                if interval == '1h' and len(df) > 1750: df = df.iloc[-1750:].copy()
                df = compute_indicators(df)
                t = backtest_single_stock(df, sym, use_trail_stop=use_trail)
                if t: all_trades.extend(t)
            except Exception:
                continue
                
        if not all_trades: continue
        tdf = pd.DataFrame(all_trades)
        total = len(tdf)
        wins = (tdf['pnl'] > 0).sum()
        wr = wins / total * 100
        pnl = tdf['pnl'].sum()
        r = tdf['r_pnl'].sum()
        gp = tdf[tdf['pnl'] > 0]['pnl'].sum()
        gl = abs(tdf[tdf['pnl'] < 0]['pnl'].sum())
        pf = gp / gl if gl > 0 else 0
        avg_w = tdf[tdf['pnl'] > 0]['pnl'].mean() if wins > 0 else 0
        avg_l = tdf[tdf['pnl'] < 0]['pnl'].mean() if (total - wins) > 0 else 0
        
        tdf['cum_pnl'] = tdf['pnl'].cumsum()
        tdf['peak'] = tdf['cum_pnl'].cummax()
        max_dd = (tdf['cum_pnl'] - tdf['peak']).min()
        
        summary.append({
            'Configuration': label,
            'Timeframe': interval.upper(),
            'Trades': total,
            'Win Rate': f"{wr:.2f}%",
            'Profit Factor': f"{pf:.2f}",
            'Net P&L (₹)': f"₹{pnl:,.2f}",
            'Total R': f"{r:+.2f} R",
            'Max Drawdown': f"₹{max_dd:,.2f}",
            'Avg Win / Loss': f"₹{avg_w:,.0f} / ₹{avg_l:,.0f}",
            'Avg Holding': f"{tdf['holding_candles'].mean():.1f} bars"
        })
        
    res_df = pd.DataFrame(summary)
    print("\n" + "=" * 90)
    print("FINAL MULTI-TIMEFRAME PERFORMANCE MATRIX (PAST 250 TRADING DAYS)")
    print("=" * 90)
    print(res_df.to_string(index=False))
    print("=" * 90)

if __name__ == '__main__':
    run_evaluation()
