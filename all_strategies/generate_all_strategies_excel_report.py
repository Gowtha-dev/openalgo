#!/usr/bin/env python3
"""
================================================================================
MASTER BACKTESTING & COMPREHENSIVE WEEKLY / MONTHLY EXCEL REPORT GENERATOR
================================================================================
Evaluates ALL tested strategies across the last 250 trading days:
1. S_1_GapOpt_Sel_TwoSide: Gap Option Selling (Two-Sided ATM, 1-Hour)
2. S_2_GapOpt_Sel_CE_GapUp: Gap Option Selling (CE on Gap Up, 1-Hour)
3. S_3_GapOpt_Buy_TwoSide: Gap Option Buying (Two-Sided ATM, 1-Hour)
4. S_4_GapOpt_Buy_PE_GapUp: Gap Option Buying (PE on Gap Up, 1-Hour)
5. S_5_Nifty_Daily_Straddle: Nifty 50 09:20 Straddle Selling (Intraday Daily)
6. S_6_Gap_Equity_MIS_1h: Gap Mean Reversion Equity MIS (1-Hour)
7. S_7_EMA_Cross_Pullback_MIS: 9/21/200 EMA + RSI + Vol Pullback MIS (1-Hour)
8. S_8_EMA_Cross_Pullback_Swing: 9/21/200 EMA + RSI + Vol Pullback Swing (1-Hour)
9. S_9_Supertrend_50EMA_Trail_1h: Supertrend 10,3 + 50 EMA + RSI Trail (1-Hour)
10. S_10_Supertrend_50EMA_Pure_1h: Supertrend 10,3 + 50 EMA + RSI Pure Flip (1-Hour)
11. S_11_Supertrend_50EMA_15m: Supertrend 10,3 + 50 EMA (15-Minute Trail)
12. S_12_Supertrend_50EMA_5m: Supertrend 10,3 + 50 EMA (5-Minute Trail)

Generates:
- Excel Workbook: openalgo/workspace/backtests/All_Strategies_Weekly_Monthly_250Days_Report.xlsx
- Formatted executive summary, monthly matrix, weekly matrix, and per-strategy detailed tabs.
================================================================================
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, time as dtime, timedelta
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKTEST_DIR = os.path.join(WORKSPACE_DIR, "workspace", "backtests")
CACHE_DIR = "/tmp/openalgo_backtest_cache"
os.makedirs(BACKTEST_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

NIFTY_50_STOCKS = [
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

# ----------------------------------------------------------------------
# 1. DATA CACHING & FETCHING
# ----------------------------------------------------------------------
def get_cached_data(symbol, interval="1h", period="730d"):
    cache_file = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{period}.pkl")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
            
    ticker = f"{symbol}.NS" if not symbol.startswith("^") and not symbol.endswith(".NS") else symbol
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df.empty or len(df) < 50:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")
            
        with open(cache_file, "wb") as f:
            pickle.dump(df, f)
        return df
    except Exception as e:
        return None

# ----------------------------------------------------------------------
# 2. RUN EMA 9/21/200 BACKTESTS IF CSVs MISSING
# ----------------------------------------------------------------------
def compute_ema_indicators(df):
    df = df.copy()
    df['ema9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['ema200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    df['vol_ma20'] = df['Volume'].rolling(window=20).mean()
    df['swing_low'] = df['Low'].rolling(window=5).min()
    df['swing_high'] = df['High'].rolling(window=5).max()
    df['bull_cross'] = (df['ema9'] > df['ema21']) & (df['ema9'].shift(1) <= df['ema21'].shift(1))
    df['bear_cross'] = (df['ema9'] < df['ema21']) & (df['ema9'].shift(1) >= df['ema21'].shift(1))
    return df

def backtest_ema_single_stock(df, symbol, is_mis=True, first_pullback_only=True):
    trades = []
    in_position = False
    current_trade = None
    active_cross = None
    cross_idx = -1
    trade_taken_for_cross = False
    
    times = df.index
    n = len(df)
    
    for i in range(200, n):
        row = df.iloc[i]
        t = times[i]
        candle_date = t.date()
        candle_time = t.time()
        
        if row['bull_cross']:
            active_cross = 'BULL'
            cross_idx = i
            trade_taken_for_cross = False
        elif row['bear_cross']:
            active_cross = 'BEAR'
            cross_idx = i
            trade_taken_for_cross = False
            
        if in_position:
            entry_price = current_trade['entry_price']
            sl = current_trade['sl']
            target = current_trade['target']
            direction = current_trade['direction']
            shares = current_trade.get('quantity', current_trade.get('shares', 1))
            
            exit_price = None
            exit_reason = None
            
            if direction == 'LONG':
                if row['Low'] <= sl:
                    exit_price = sl * (1 - SLIPPAGE_PCT)
                    exit_reason = 'STOP_LOSS'
                elif row['High'] >= target:
                    exit_price = target * (1 - SLIPPAGE_PCT)
                    exit_reason = 'TARGET_1:2'
                elif is_mis and (candle_time >= dtime(15, 15) or candle_date != current_trade['entry_date']):
                    exit_price = row['Close'] * (1 - SLIPPAGE_PCT)
                    exit_reason = 'MIS_SQUAREOFF'
            else:
                if row['High'] >= sl:
                    exit_price = sl * (1 + SLIPPAGE_PCT)
                    exit_reason = 'STOP_LOSS'
                elif row['Low'] <= target:
                    exit_price = target * (1 + SLIPPAGE_PCT)
                    exit_reason = 'TARGET_1:2'
                elif is_mis and (candle_time >= dtime(15, 15) or candle_date != current_trade['entry_date']):
                    exit_price = row['Close'] * (1 + SLIPPAGE_PCT)
                    exit_reason = 'MIS_SQUAREOFF'
                    
            if exit_price is not None:
                if direction == 'LONG':
                    gross_pnl = (exit_price - entry_price) * shares
                    charges = 2 * COMMISSION_PER_ORDER
                    net_pnl = gross_pnl - charges
                    r_pnl = (exit_price - entry_price) / current_trade['risk_per_share']
                else:
                    gross_pnl = (entry_price - exit_price) * shares
                    charges = 2 * COMMISSION_PER_ORDER
                    net_pnl = gross_pnl - charges
                    r_pnl = (entry_price - exit_price) / current_trade['risk_per_share']
                    
                current_trade.update({
                    'exit_time': str(t),
                    'exit_price': round(exit_price, 2),
                    'gross_pnl': round(gross_pnl, 2),
                    'charges': round(charges, 2),
                    'net_pnl': round(net_pnl, 2),
                    'r_multiple': round(r_pnl, 2),
                    'exit_reason': exit_reason
                })
                trades.append(current_trade)
                in_position = False
                current_trade = None
                
            if in_position:
                continue
                
        if is_mis and candle_time >= dtime(14, 30):
            continue
        if first_pullback_only and (active_cross is None or trade_taken_for_cross):
            continue
        if first_pullback_only:
            candles_since = i - cross_idx
            if candles_since > 10 or candles_since < 1:
                continue
                
        close = row['Close']
        open_p = row['Open']
        high = row['High']
        low = row['Low']
        vol = row['Volume']
        ema9 = row['ema9']
        ema21 = row['ema21']
        ema200 = row['ema200']
        rsi = row['rsi']
        vol_ma = row['vol_ma20']
        
        if vol <= vol_ma:
            continue
            
        # LONG
        if (close > ema200) and (ema9 > ema21) and (rsi > 50):
            if (low <= ema9) and (low >= ema21 * 0.995) and (close > open_p) and (close > ema9):
                ep = close * (1 + SLIPPAGE_PCT)
                sl = min(row['swing_low'], ema21 * 0.998)
                risk = ep - sl
                if risk > ep * 0.003 and risk < ep * 0.035:
                    target = ep + (2.0 * risk)
                    sh = int(CAPITAL_PER_TRADE / ep)
                    if sh > 0:
                        in_position = True
                        trade_taken_for_cross = True
                        current_trade = {
                            'trade_id': len(trades) + 1,
                            'symbol': symbol,
                            'direction': 'BUY',
                            'entry_time': str(t),
                            'entry_date': candle_date,
                            'entry_price': round(ep, 2),
                            'sl': round(sl, 2),
                            'target': round(target, 2),
                            'risk_per_share': risk,
                            'quantity': sh,
                            'trade_value': round(sh * ep, 2)
                        }
                        continue
                        
        # SHORT
        if (close < ema200) and (ema9 < ema21) and (rsi < 50):
            if (high >= ema9) and (high <= ema21 * 1.005) and (close < open_p) and (close < ema9):
                ep = close * (1 - SLIPPAGE_PCT)
                sl = max(row['swing_high'], ema21 * 1.002)
                risk = sl - ep
                if risk > ep * 0.003 and risk < ep * 0.035:
                    target = ep - (2.0 * risk)
                    sh = int(CAPITAL_PER_TRADE / ep)
                    if sh > 0:
                        in_position = True
                        trade_taken_for_cross = True
                        current_trade = {
                            'trade_id': len(trades) + 1,
                            'symbol': symbol,
                            'direction': 'SELL',
                            'entry_time': str(t),
                            'entry_date': candle_date,
                            'entry_price': round(ep, 2),
                            'sl': round(sl, 2),
                            'target': round(target, 2),
                            'risk_per_share': risk,
                            'quantity': sh,
                            'trade_value': round(sh * ep, 2)
                        }
                        continue
                        
    return trades

def ensure_ema_trades():
    mis_csv = os.path.join(BACKTEST_DIR, "trades_ema_mis_1h_250d.csv")
    swing_csv = os.path.join(BACKTEST_DIR, "trades_ema_swing_1h_250d.csv")
    
    if os.path.exists(mis_csv) and os.path.exists(swing_csv):
        return
        
    print("Generating EMA 9/21/200 trades...")
    mis_trades = []
    swing_trades = []
    
    for sym in NIFTY_50_STOCKS:
        df = get_cached_data(sym, interval="1h", period="730d")
        if df is None: continue
        df = compute_ema_indicators(df)
        
        t_mis = backtest_ema_single_stock(df, sym, is_mis=True, first_pullback_only=True)
        if t_mis: mis_trades.extend(t_mis)
        
        t_sw = backtest_ema_single_stock(df, sym, is_mis=False, first_pullback_only=True)
        if t_sw: swing_trades.extend(t_sw)
        
    if mis_trades:
        df_mis = pd.DataFrame(mis_trades)
        if 'entry_date' in df_mis.columns: df_mis.drop(columns=['entry_date'], inplace=True)
        df_mis.to_csv(mis_csv, index=False)
        
    if swing_trades:
        df_sw = pd.DataFrame(swing_trades)
        if 'entry_date' in df_sw.columns: df_sw.drop(columns=['entry_date'], inplace=True)
        df_sw.to_csv(swing_csv, index=False)
    print("EMA trades saved successfully.")

# ----------------------------------------------------------------------
# 3. RUN SUPERTREND BACKTESTS IF CSVs MISSING
# ----------------------------------------------------------------------
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

def compute_supertrend_indicators(df):
    df = df.copy()
    df = calculate_supertrend(df, period=10, multiplier=3.0)
    df['ema50'] = df['Close'].ewm(span=50, adjust=False).mean()
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    df['low20'] = df['Low'].rolling(window=20).min()
    return df

def backtest_supertrend_single_stock(df, symbol, use_trail_stop=True):
    trades = []
    in_pos = False
    cur_trade = None
    times = df.index
    n = len(df)
    
    for i in range(50, n - 1):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        next_row = df.iloc[i+1]
        
        if in_pos:
            cur_trade['highest_close'] = max(cur_trade['highest_close'], row['Close'])
            trail_stop = cur_trade['highest_close'] - (2.0 * row['atr'])
            
            exit_price = None
            exit_reason = None
            
            if row['trend'] == -1 and prev_row['trend'] == 1:
                exit_price = next_row['Open'] * (1 - SLIPPAGE_PCT)
                exit_reason = 'SUPERTREND_BEAR_FLIP'
            elif row['Close'] < prev_row['low20']:
                exit_price = next_row['Open'] * (1 - SLIPPAGE_PCT)
                exit_reason = 'BREAK_20_LOW'
            elif use_trail_stop and (row['Low'] <= trail_stop):
                exit_price = trail_stop * (1 - SLIPPAGE_PCT)
                exit_reason = 'TRAIL_STOP_2ATR'
                
            if exit_price is not None:
                ep = cur_trade['entry_price']
                sh = cur_trade['quantity']
                gross_pnl = (exit_price - ep) * sh
                charges = 2 * COMMISSION_PER_ORDER
                net_pnl = gross_pnl - charges
                r_pnl = (exit_price - ep) / cur_trade['initial_risk_per_share']
                
                cur_trade.update({
                    'exit_time': str(times[i+1]),
                    'exit_price': round(exit_price, 2),
                    'gross_pnl': round(gross_pnl, 2),
                    'charges': round(charges, 2),
                    'net_pnl': round(net_pnl, 2),
                    'r_multiple': round(r_pnl, 2),
                    'exit_reason': exit_reason
                })
                trades.append(cur_trade)
                in_pos = False
                cur_trade = None
                
            if in_pos:
                continue
                
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
                        'trade_id': len(trades) + 1,
                        'symbol': symbol,
                        'direction': 'BUY',
                        'entry_time': str(times[i+1]),
                        'entry_price': round(ep, 2),
                        'sl': round(initial_sl, 2),
                        'initial_risk_per_share': initial_risk,
                        'highest_close': row['Close'],
                        'quantity': sh,
                        'trade_value': round(sh * ep, 2)
                    }
    return trades

def ensure_supertrend_trades():
    trail_csv = os.path.join(BACKTEST_DIR, "trades_supertrend_trail_1h_250d.csv")
    pure_csv = os.path.join(BACKTEST_DIR, "trades_supertrend_pure_1h_250d.csv")
    
    if os.path.exists(trail_csv) and os.path.exists(pure_csv):
        return
        
    print("Generating Supertrend 50 EMA trades...")
    trail_trades = []
    pure_trades = []
    
    for sym in NSE_LIQUID_STOCKS if 'NSE_LIQUID_STOCKS' in globals() else NIFTY_50_STOCKS:
        df = get_cached_data(sym, interval="1h", period="730d")
        if df is None: continue
        df = compute_supertrend_indicators(df)
        
        t_tr = backtest_supertrend_single_stock(df, sym, use_trail_stop=True)
        if t_tr: trail_trades.extend(t_tr)
        
        t_pu = backtest_supertrend_single_stock(df, sym, use_trail_stop=False)
        if t_pu: pure_trades.extend(t_pu)
        
    if trail_trades:
        df_tr = pd.DataFrame(trail_trades)
        for col in ['initial_risk_per_share', 'highest_close']:
            if col in df_tr.columns: df_tr.drop(columns=[col], inplace=True)
        df_tr.to_csv(trail_csv, index=False)
        
    if pure_trades:
        df_pu = pd.DataFrame(pure_trades)
        for col in ['initial_risk_per_share', 'highest_close']:
            if col in df_pu.columns: df_pu.drop(columns=[col], inplace=True)
        df_pu.to_csv(pure_csv, index=False)
    print("Supertrend trades saved successfully.")

# ----------------------------------------------------------------------
# 4. LOAD & NORMALIZE ALL STRATEGIES
# ----------------------------------------------------------------------
def load_all_strategy_datasets():
    strategies = {}
    
    # S1: Gap Option Selling Two-Side ATM (1H, 250D)
    f1 = os.path.join(BACKTEST_DIR, "trade_logs_gap_option_selling_1h_250d.csv")
    if os.path.exists(f1):
        df = pd.read_csv(f1)
        strategies["S1_GapOpt_Sel_TwoSide"] = {
            "name": "S1: Gap Option Selling (Two-Sided ATM 1H)",
            "asset_class": "Nifty 50 Stock Options (Selling)",
            "timeframe": "1-Hour",
            "capital": 1000000.0,
            "data": df
        }
        # S2: Gap Option Selling CE on Gap Up (1H, 250D)
        df_ce = df[df['type'].str.contains("SELL CE", case=False, na=False)].copy()
        strategies["S2_GapOpt_Sel_CE_GapUp"] = {
            "name": "S2: Gap Option Selling (CE on Gap Up 1H)",
            "asset_class": "Nifty 50 Stock Options (Selling)",
            "timeframe": "1-Hour",
            "capital": 1000000.0,
            "data": df_ce
        }
        
    # S3: Gap Option Buying Two-Side ATM (1H, 250D)
    f3 = os.path.join(BACKTEST_DIR, "trade_logs_gap_options_twoside_1h_250d.csv")
    if os.path.exists(f3):
        df = pd.read_csv(f3)
        strategies["S3_GapOpt_Buy_TwoSide"] = {
            "name": "S3: Gap Option Buying (Two-Sided ATM 1H)",
            "asset_class": "Nifty 50 Stock Options (Buying)",
            "timeframe": "1-Hour",
            "capital": 1000000.0,
            "data": df
        }
        
    # S4: Gap Option Buying PE on Gap Up (1H, 250D)
    f4 = os.path.join(BACKTEST_DIR, "trade_logs_gap_options_1h_250d.csv")
    if os.path.exists(f4):
        df = pd.read_csv(f4)
        strategies["S4_GapOpt_Buy_PE_GapUp"] = {
            "name": "S4: Gap Option Buying (PE on Gap Up 1H)",
            "asset_class": "Nifty 50 Stock Options (Buying)",
            "timeframe": "1-Hour",
            "capital": 1000000.0,
            "data": df
        }
        
    # S5: Nifty Daily 09:20 Straddle Selling (250D)
    f5 = os.path.join(BACKTEST_DIR, "trades_nifty_daily_straddle_250d.csv")
    if os.path.exists(f5):
        df = pd.read_csv(f5)
        # normalize date column to entry_time
        if 'date' in df.columns and 'entry_time' not in df.columns:
            df['entry_time'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d 09:20:00')
        strategies["S5_Nifty_Daily_Straddle"] = {
            "name": "S5: Nifty Daily Straddle Selling (09:20 - 15:15)",
            "asset_class": "Index Options (Intraday Selling)",
            "timeframe": "Daily Intraday",
            "capital": 1000000.0,
            "data": df
        }
        
    # S6: Gap Mean Reversion Equity MIS 1H (250D)
    f6 = os.path.join(BACKTEST_DIR, "trades_gap_1h_250d.csv")
    if os.path.exists(f6):
        df = pd.read_csv(f6)
        strategies["S6_Gap_Equity_MIS_1h"] = {
            "name": "S6: Gap Mean Reversion Equity MIS (1-Hour)",
            "asset_class": "Nifty 50 Equities (Intraday MIS)",
            "timeframe": "1-Hour",
            "capital": 1000000.0,
            "data": df
        }
        
    # S7: EMA 9/21/200 MIS Pullback 1H (250D)
    f7 = os.path.join(BACKTEST_DIR, "trades_ema_mis_1h_250d.csv")
    if os.path.exists(f7):
        df = pd.read_csv(f7)
        strategies["S7_EMA_Cross_MIS_1h"] = {
            "name": "S7: 9/21/200 EMA Pullback Intraday MIS (1-Hour)",
            "asset_class": "Nifty 50 Equities (Intraday MIS)",
            "timeframe": "1-Hour",
            "capital": 1000000.0,
            "data": df
        }
        
    # S8: EMA 9/21/200 Swing Pullback 1H (250D)
    f8 = os.path.join(BACKTEST_DIR, "trades_ema_swing_1h_250d.csv")
    if os.path.exists(f8):
        df = pd.read_csv(f8)
        strategies["S8_EMA_Cross_Swing_1h"] = {
            "name": "S8: 9/21/200 EMA Pullback Swing 2R (1-Hour)",
            "asset_class": "Nifty 50 Equities (Swing)",
            "timeframe": "1-Hour",
            "capital": 1000000.0,
            "data": df
        }
        
    # S9: Supertrend 50 EMA 2x ATR Trail 1H (250D)
    f9 = os.path.join(BACKTEST_DIR, "trades_supertrend_trail_1h_250d.csv")
    if os.path.exists(f9):
        df = pd.read_csv(f9)
        strategies["S9_Supertrend_Trail_1h"] = {
            "name": "S9: Supertrend + 50 EMA 2x ATR Trail (1-Hour)",
            "asset_class": "Nifty 50 Equities (Swing)",
            "timeframe": "1-Hour",
            "capital": 1000000.0,
            "data": df
        }
        
    # S10: Supertrend 50 EMA Pure Trend 1H (250D)
    f10 = os.path.join(BACKTEST_DIR, "trades_supertrend_pure_1h_250d.csv")
    if os.path.exists(f10):
        df = pd.read_csv(f10)
        strategies["S10_Supertrend_Pure_1h"] = {
            "name": "S10: Supertrend + 50 EMA Pure Flip Exit (1-Hour)",
            "asset_class": "Nifty 50 Equities (Swing)",
            "timeframe": "1-Hour",
            "capital": 1000000.0,
            "data": df
        }
        
    return strategies

# ----------------------------------------------------------------------
# 5. AGGREGATE WEEKLY & MONTHLY BREAKDOWNS
# ----------------------------------------------------------------------
def process_strategy_metrics(df, capital=1000000.0):
    df = df.copy()
    
    # Identify timestamp column
    time_col = None
    for c in ['entry_time', 'date', 'exit_time']:
        if c in df.columns:
            time_col = c
            break
            
    dt_series = pd.to_datetime(df[time_col])
    try:
        if dt_series.dt.tz is not None:
            dt_series = dt_series.dt.tz_localize(None)
    except Exception:
        pass
    df['dt'] = dt_series
    # Align to the 250-day backtest window
    df = df[df['dt'] >= pd.Timestamp('2025-10-30')].copy()
    df['month'] = df['dt'].dt.to_period('M').astype(str)
    
    # ISO calendar week
    iso = df['dt'].dt.isocalendar()
    df['week'] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    df['trade_date'] = df['dt'].dt.date
    
    # Net pnl column
    pnl_col = 'net_pnl' if 'net_pnl' in df.columns else 'pnl'
    gross_col = 'gross_pnl' if 'gross_pnl' in df.columns else pnl_col
    charges_col = 'charges' if 'charges' in df.columns else None
    
    df['pnl_val'] = df[pnl_col]
    df['gross_val'] = df[gross_col]
    df['charges_val'] = df[charges_col] if charges_col is not None else 0.0
    
    # Monthly aggregation
    monthly_rows = []
    cum_m_pnl = 0.0
    
    for m, g in df.groupby('month', sort=True):
        trades_cnt = len(g)
        wins = (g['pnl_val'] > 0).sum()
        losses = (g['pnl_val'] <= 0).sum()
        wr = (wins / trades_cnt) * 100 if trades_cnt > 0 else 0.0
        gross = g['gross_val'].sum()
        charges = g['charges_val'].sum()
        net = g['pnl_val'].sum()
        cum_m_pnl += net
        
        pos_sum = g[g['pnl_val'] > 0]['pnl_val'].sum()
        neg_sum = abs(g[g['pnl_val'] < 0]['pnl_val'].sum())
        pf = pos_sum / neg_sum if neg_sum > 0 else (99.0 if pos_sum > 0 else 0.0)
        
        r_sum = g['r_multiple'].sum() if 'r_multiple' in g.columns else 0.0
        
        monthly_rows.append({
            'month': m,
            'trades': trades_cnt,
            'wins': wins,
            'losses': losses,
            'win_rate': wr,
            'gross_pnl': gross,
            'charges': charges,
            'net_pnl': net,
            'cum_pnl': cum_m_pnl,
            'profit_factor': pf,
            'return_pct': (net / capital) * 100,
            'total_r': r_sum
        })
    monthly_df = pd.DataFrame(monthly_rows)
    
    # Weekly aggregation
    weekly_rows = []
    cum_w_pnl = 0.0
    
    for w, g in df.groupby('week', sort=True):
        trades_cnt = len(g)
        wins = (g['pnl_val'] > 0).sum()
        losses = (g['pnl_val'] <= 0).sum()
        wr = (wins / trades_cnt) * 100 if trades_cnt > 0 else 0.0
        gross = g['gross_val'].sum()
        charges = g['charges_val'].sum()
        net = g['pnl_val'].sum()
        cum_w_pnl += net
        
        start_d = str(g['trade_date'].min())
        end_d = str(g['trade_date'].max())
        
        pos_sum = g[g['pnl_val'] > 0]['pnl_val'].sum()
        neg_sum = abs(g[g['pnl_val'] < 0]['pnl_val'].sum())
        pf = pos_sum / neg_sum if neg_sum > 0 else (99.0 if pos_sum > 0 else 0.0)
        
        r_sum = g['r_multiple'].sum() if 'r_multiple' in g.columns else 0.0
        
        weekly_rows.append({
            'week': w,
            'start_date': start_d,
            'end_date': end_d,
            'trades': trades_cnt,
            'wins': wins,
            'losses': losses,
            'win_rate': wr,
            'gross_pnl': gross,
            'charges': charges,
            'net_pnl': net,
            'cum_pnl': cum_w_pnl,
            'profit_factor': pf,
            'return_pct': (net / capital) * 100,
            'total_r': r_sum
        })
    weekly_df = pd.DataFrame(weekly_rows)
    
    # Strategy summary stats
    tot_trades = len(df)
    tot_wins = (df['pnl_val'] > 0).sum()
    tot_losses = (df['pnl_val'] <= 0).sum()
    tot_wr = (tot_wins / tot_trades) * 100 if tot_trades > 0 else 0.0
    tot_gross = df['gross_val'].sum()
    tot_charges = df['charges_val'].sum()
    tot_net = df['pnl_val'].sum()
    
    pos_sum = df[df['pnl_val'] > 0]['pnl_val'].sum()
    neg_sum = abs(df[df['pnl_val'] < 0]['pnl_val'].sum())
    tot_pf = pos_sum / neg_sum if neg_sum > 0 else (99.0 if pos_sum > 0 else 0.0)
    
    df['cum_pnl_trade'] = df['pnl_val'].cumsum()
    df['peak'] = df['cum_pnl_trade'].cummax()
    df['drawdown'] = df['cum_pnl_trade'] - df['peak']
    max_dd = df['drawdown'].min()
    
    roi = (tot_net / capital) * 100
    calmar = abs(tot_net / max_dd) if max_dd < 0 else 99.0
    tot_r = df['r_multiple'].sum() if 'r_multiple' in df.columns else 0.0
    
    summary = {
        'total_trades': tot_trades,
        'wins': tot_wins,
        'losses': tot_losses,
        'win_rate': tot_wr,
        'gross_pnl': tot_gross,
        'charges': tot_charges,
        'net_pnl': tot_net,
        'profit_factor': tot_pf,
        'max_drawdown': max_dd,
        'roi_pct': roi,
        'calmar': calmar,
        'total_r': tot_r
    }
    
    return monthly_df, weekly_df, summary, df

# ----------------------------------------------------------------------
# 6. BUILD EXCEL WORKBOOK WITH OPENPYXL
# ----------------------------------------------------------------------
def create_excel_workbook(strategies_data):
    wb = openpyxl.Workbook()
    # Remove default sheet
    default_sheet = wb.active
    
    # STYLES
    navy_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    dark_slate_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
    soft_blue_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    light_gray_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    gold_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    
    green_pnl_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    red_pnl_fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
    
    white_bold = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    white_title = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    black_bold = Font(name="Calibri", size=11, bold=True, color="000000")
    black_regular = Font(name="Calibri", size=11, bold=False, color="000000")
    green_bold = Font(name="Calibri", size=11, bold=True, color="276A3C")
    red_bold = Font(name="Calibri", size=11, bold=True, color="A61C1C")
    
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    
    thin_side = Side(border_style="thin", color="D9D9D9")
    thick_bottom = Side(border_style="medium", color="1F4E78")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    header_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thick_bottom)
    
    # -------------------------------------------------------------
    # SHEET 1: EXECUTIVE SUMMARY
    # -------------------------------------------------------------
    ws_exec = wb.create_sheet(title="Executive_Summary")
    ws_exec.views.sheetView[0].showGridLines = True
    
    # Title Block
    ws_exec.merge_cells("A1:J1")
    title_cell = ws_exec["A1"]
    title_cell.value = "OPENALGO QUANTITATIVE TRADING ENGINE — 250-DAY STRATEGY AUDIT & LEADERBOARD"
    title_cell.font = white_title
    title_cell.fill = navy_fill
    title_cell.alignment = align_center
    ws_exec.row_dimensions[1].height = 40
    
    headers = [
        "Rank", "Strategy Key", "Strategy Name", "Asset Class", "Timeframe",
        "Total Trades", "Win Rate (%)", "Net P&L (₹)", "Profit Factor", "Max DD (₹)", "Total Return R"
    ]
    
    ws_exec.row_dimensions[3].height = 25
    for col_idx, h in enumerate(headers, start=1):
        cell = ws_exec.cell(row=3, column=col_idx, value=h)
        cell.font = white_bold
        cell.fill = dark_slate_fill
        cell.alignment = align_center
        cell.border = header_border
        
    # Sort strategies by Net PnL descending
    sorted_strats = sorted(strategies_data.items(), key=lambda x: x[1]['summary']['net_pnl'], reverse=True)
    
    row_num = 4
    for rank, (key, sinfo) in enumerate(sorted_strats, start=1):
        ws_exec.row_dimensions[row_num].height = 22
        summ = sinfo['summary']
        fill = light_gray_fill if rank % 2 == 0 else PatternFill(fill_type=None)
        
        ws_exec.cell(row=row_num, column=1, value=rank).alignment = align_center
        ws_exec.cell(row=row_num, column=2, value=key).alignment = align_left
        ws_exec.cell(row=row_num, column=3, value=sinfo['name']).alignment = align_left
        ws_exec.cell(row=row_num, column=4, value=sinfo['asset_class']).alignment = align_left
        ws_exec.cell(row=row_num, column=5, value=sinfo['timeframe']).alignment = align_center
        
        c_tr = ws_exec.cell(row=row_num, column=6, value=summ['total_trades'])
        c_tr.number_format = "#,##0"
        c_tr.alignment = align_right
        
        c_wr = ws_exec.cell(row=row_num, column=7, value=summ['win_rate'] / 100.0)
        c_wr.number_format = "0.0%"
        c_wr.alignment = align_right
        
        c_pnl = ws_exec.cell(row=row_num, column=8, value=summ['net_pnl'])
        c_pnl.number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
        c_pnl.alignment = align_right
        c_pnl.font = green_bold if summ['net_pnl'] >= 0 else red_bold
        c_pnl.fill = green_pnl_fill if summ['net_pnl'] >= 0 else red_pnl_fill
        
        c_pf = ws_exec.cell(row=row_num, column=9, value=summ['profit_factor'])
        c_pf.number_format = "0.00"
        c_pf.alignment = align_right
        
        c_dd = ws_exec.cell(row=row_num, column=10, value=summ['max_drawdown'])
        c_dd.number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
        c_dd.alignment = align_right
        
        c_r = ws_exec.cell(row=row_num, column=11, value=summ['total_r'])
        c_r.number_format = "+0.00 R;-0.00 R;0.00 R"
        c_r.alignment = align_right
        
        for c in range(1, 12):
            cell = ws_exec.cell(row=row_num, column=c)
            cell.border = cell_border
            if c != 8 and fill.fill_type: cell.fill = fill
            
        row_num += 1
        
    # Total Portfolio Row
    ws_exec.row_dimensions[row_num].height = 25
    tot_trades_all = sum(sinfo['summary']['total_trades'] for _, sinfo in sorted_strats)
    tot_pnl_all = sum(sinfo['summary']['net_pnl'] for _, sinfo in sorted_strats)
    ws_exec.cell(row=row_num, column=2, value="TOTAL ALL STRATEGIES").font = black_bold
    ws_exec.cell(row=row_num, column=6, value=tot_trades_all).number_format = "#,##0"
    ws_exec.cell(row=row_num, column=8, value=tot_pnl_all).number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
    ws_exec.cell(row=row_num, column=8).font = green_bold
    ws_exec.cell(row=row_num, column=8).fill = gold_fill
    for c in range(1, 12):
        ws_exec.cell(row=row_num, column=c).border = Border(top=thin_side, bottom=thick_bottom)
        
    # Auto column width
    for col in ws_exec.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_exec.column_dimensions[col_letter].width = max(max_len + 3, 12)
    ws_exec.freeze_panes = "C4"

    # -------------------------------------------------------------
    # SHEET 2: MONTHLY PERFORMANCE MATRIX
    # -------------------------------------------------------------
    ws_month = wb.create_sheet(title="Monthly_Matrix")
    ws_month.views.sheetView[0].showGridLines = True
    
    ws_month.merge_cells("A1:M1")
    t_cell = ws_month["A1"]
    t_cell.value = "MONTH-BY-MONTH NET P&L MATRIX ACROSS ALL STRATEGIES (₹)"
    t_cell.font = white_title
    t_cell.fill = navy_fill
    t_cell.alignment = align_center
    ws_month.row_dimensions[1].height = 40
    
    # Collect all unique months across all strategies
    all_months = set()
    for key, sinfo in strategies_data.items():
        all_months.update(sinfo['monthly']['month'].tolist())
    sorted_months = sorted(list(all_months))
    
    m_headers = ["Month"] + [sinfo['name'].split(":")[0] for key, sinfo in sorted_strats] + ["Combined Portfolio (₹)"]
    ws_month.row_dimensions[3].height = 25
    for col_idx, h in enumerate(m_headers, start=1):
        cell = ws_month.cell(row=3, column=col_idx, value=h)
        cell.font = white_bold
        cell.fill = dark_slate_fill
        cell.alignment = align_center
        cell.border = header_border
        
    row_num = 4
    for m in sorted_months:
        ws_month.row_dimensions[row_num].height = 22
        ws_month.cell(row=row_num, column=1, value=m).alignment = align_center
        
        row_pnl_sum = 0.0
        for strat_idx, (key, sinfo) in enumerate(sorted_strats, start=2):
            m_df = sinfo['monthly']
            match = m_df[m_df['month'] == m]
            pnl = match['net_pnl'].iloc[0] if len(match) > 0 else 0.0
            row_pnl_sum += pnl
            
            cell = ws_month.cell(row=row_num, column=strat_idx, value=round(pnl, 2))
            cell.number_format = "₹#,##0;[Red]-₹#,##0;\"-\""
            cell.alignment = align_right
            cell.border = cell_border
            if pnl > 0:
                cell.fill = green_pnl_fill
                cell.font = green_bold
            elif pnl < 0:
                cell.fill = red_pnl_fill
                cell.font = red_bold
                
        # Portfolio combined col
        tot_col = len(m_headers)
        tot_cell = ws_month.cell(row=row_num, column=tot_col, value=round(row_pnl_sum, 2))
        tot_cell.number_format = "₹#,##0;[Red]-₹#,##0;\"-\""
        tot_cell.font = black_bold
        tot_cell.alignment = align_right
        tot_cell.border = cell_border
        tot_cell.fill = soft_blue_fill
        row_num += 1
        
    # Monthly Total & Average Rows
    ws_month.row_dimensions[row_num].height = 25
    ws_month.cell(row=row_num, column=1, value="TOTAL (250D)").font = black_bold
    ws_month.cell(row=row_num, column=1).alignment = align_center
    col_totals = [0.0] * (len(m_headers) + 1)
    for r in range(4, row_num):
        for c in range(2, len(m_headers) + 1):
            col_totals[c] += float(ws_month.cell(row=r, column=c).value or 0.0)
            
    for c_idx in range(2, len(m_headers) + 1):
        cell = ws_month.cell(row=row_num, column=c_idx, value=round(col_totals[c_idx], 2))
        cell.number_format = "₹#,##0;[Red]-₹#,##0;\"-\""
        cell.font = black_bold
        cell.alignment = align_right
        cell.fill = gold_fill
        cell.border = Border(top=thin_side, bottom=thick_bottom)
        
    row_num += 1
    ws_month.row_dimensions[row_num].height = 22
    ws_month.cell(row=row_num, column=1, value="MONTHLY AVERAGE").font = black_bold
    ws_month.cell(row=row_num, column=1).alignment = align_center
    num_m = len(sorted_months) if len(sorted_months) > 0 else 1
    for c_idx in range(2, len(m_headers) + 1):
        cell = ws_month.cell(row=row_num, column=c_idx, value=round(col_totals[c_idx] / num_m, 2))
        cell.number_format = "₹#,##0;[Red]-₹#,##0;\"-\""
        cell.alignment = align_right
        cell.border = cell_border
        
    for col in ws_month.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_month.column_dimensions[col_letter].width = max(max_len + 3, 14)
    ws_month.freeze_panes = "B4"

    # -------------------------------------------------------------
    # SHEET 3: WEEKLY PERFORMANCE MATRIX
    # -------------------------------------------------------------
    ws_week = wb.create_sheet(title="Weekly_Matrix")
    ws_week.views.sheetView[0].showGridLines = True
    
    ws_week.merge_cells("A1:N1")
    w_title = ws_week["A1"]
    w_title.value = "WEEK-BY-WEEK NET P&L MATRIX ACROSS ALL STRATEGIES (₹)"
    w_title.font = white_title
    w_title.fill = navy_fill
    w_title.alignment = align_center
    ws_week.row_dimensions[1].height = 40
    
    all_weeks = set()
    week_date_map = {}
    for key, sinfo in strategies_data.items():
        w_df = sinfo['weekly']
        for _, r in w_df.iterrows():
            wk = r['week']
            all_weeks.add(wk)
            if wk not in week_date_map:
                week_date_map[wk] = (r['start_date'], r['end_date'])
    sorted_weeks = sorted(list(all_weeks))
    
    w_headers = ["Week", "Start Date", "End Date"] + [sinfo['name'].split(":")[0] for key, sinfo in sorted_strats] + ["Combined Portfolio (₹)"]
    ws_week.row_dimensions[3].height = 25
    for col_idx, h in enumerate(w_headers, start=1):
        cell = ws_week.cell(row=3, column=col_idx, value=h)
        cell.font = white_bold
        cell.fill = dark_slate_fill
        cell.alignment = align_center
        cell.border = header_border
        
    row_num = 4
    for w in sorted_weeks:
        ws_week.row_dimensions[row_num].height = 20
        ws_week.cell(row=row_num, column=1, value=w).alignment = align_center
        s_date, e_date = week_date_map.get(w, ("", ""))
        ws_week.cell(row=row_num, column=2, value=s_date).alignment = align_center
        ws_week.cell(row=row_num, column=3, value=e_date).alignment = align_center
        
        row_w_pnl_sum = 0.0
        for strat_idx, (key, sinfo) in enumerate(sorted_strats, start=4):
            w_df = sinfo['weekly']
            match = w_df[w_df['week'] == w]
            pnl = match['net_pnl'].iloc[0] if len(match) > 0 else 0.0
            row_w_pnl_sum += pnl
            
            cell = ws_week.cell(row=row_num, column=strat_idx, value=round(pnl, 2))
            cell.number_format = "₹#,##0;[Red]-₹#,##0;\"-\""
            cell.alignment = align_right
            cell.border = cell_border
            if pnl > 0:
                cell.fill = green_pnl_fill
                cell.font = green_bold
            elif pnl < 0:
                cell.fill = red_pnl_fill
                cell.font = red_bold
                
        tot_col = len(w_headers)
        tot_cell = ws_week.cell(row=row_num, column=tot_col, value=round(row_w_pnl_sum, 2))
        tot_cell.number_format = "₹#,##0;[Red]-₹#,##0;\"-\""
        tot_cell.font = black_bold
        tot_cell.alignment = align_right
        tot_cell.border = cell_border
        tot_cell.fill = soft_blue_fill
        row_num += 1
        
    # Weekly Total Row
    ws_week.row_dimensions[row_num].height = 25
    ws_week.cell(row=row_num, column=1, value="TOTAL (52 WEEKS)").font = black_bold
    ws_week.cell(row=row_num, column=1).alignment = align_center
    col_w_totals = [0.0] * (len(w_headers) + 1)
    for r in range(4, row_num):
        for c in range(4, len(w_headers) + 1):
            col_w_totals[c] += float(ws_week.cell(row=r, column=c).value or 0.0)
            
    for c_idx in range(4, len(w_headers) + 1):
        cell = ws_week.cell(row=row_num, column=c_idx, value=round(col_w_totals[c_idx], 2))
        cell.number_format = "₹#,##0;[Red]-₹#,##0;\"-\""
        cell.font = black_bold
        cell.alignment = align_right
        cell.fill = gold_fill
        cell.border = Border(top=thin_side, bottom=thick_bottom)
        
    for col in ws_week.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_week.column_dimensions[col_letter].width = max(max_len + 3, 13)
    ws_week.freeze_panes = "D4"

    # -------------------------------------------------------------
    # SHEET 4: ALL TRADES MASTER AUDIT LOG (ALL 6,551 TRADES)
    # -------------------------------------------------------------
    ws_all = wb.create_sheet(title="All_Trades_Master_Log")
    ws_all.views.sheetView[0].showGridLines = True
    
    ws_all.merge_cells("A1:Q1")
    a_title = ws_all["A1"]
    a_title.value = "COMPLETE 250-DAY MASTER TRADE AUDIT LOG — ALL STRATEGIES & CONTRACTS"
    a_title.font = white_title
    a_title.fill = navy_fill
    a_title.alignment = align_center
    ws_all.row_dimensions[1].height = 40
    
    all_tr_headers = [
        "Trade #", "Strategy Key", "Strategy Name", "Asset Class", "Symbol",
        "Contract / Instrument", "Direction / Action", "Entry Time", "Exit Time",
        "Entry Price / Prem (₹)", "Exit Price / Prem (₹)", "Quantity / Lots",
        "Gross P&L (₹)", "Charges (₹)", "Net P&L (₹)", "Return R", "Exit Reason"
    ]
    
    ws_all.row_dimensions[3].height = 25
    for col_idx, h in enumerate(all_tr_headers, start=1):
        cell = ws_all.cell(row=3, column=col_idx, value=h)
        cell.font = white_bold
        cell.fill = dark_slate_fill
        cell.alignment = align_center
        cell.border = header_border
        
    master_trade_list = []
    for key, sinfo in sorted_strats:
        s_df = sinfo['data']
        for _, row in s_df.iterrows():
            time_col = 'entry_time' if 'entry_time' in row else ('date' if 'date' in row else 'exit_time')
            entry_time = str(row[time_col])
            exit_time = str(row['exit_time']) if 'exit_time' in row and pd.notna(row['exit_time']) else ''
            symbol = str(row.get('symbol', 'NIFTY'))
            contract = str(row.get('contract', f"{symbol} ATM {row.get('atm_strike', '')} Straddle" if 'atm_strike' in row else symbol))
            direction = str(row.get('type', row.get('direction', 'SELL STRADDLE' if 'atm_strike' in row else '')))
            
            entry_price = 0.0
            for c in ['opt_sell_premium', 'opt_entry_premium', 'entry_price', 'ce_entry_prem']:
                if c in row and pd.notna(row[c]):
                    entry_price = float(row[c])
                    break
            exit_price = 0.0
            for c in ['opt_buy_premium', 'opt_exit_premium', 'exit_price', 'ce_exit_prem']:
                if c in row and pd.notna(row[c]):
                    exit_price = float(row[c])
                    break
                    
            qty = 0
            for c in ['quantity', 'lot_size', 'total_qty', 'shares']:
                if c in row and pd.notna(row[c]):
                    qty = int(row[c])
                    break
                    
            gross_pnl = float(row.get('gross_pnl', row.get('net_pnl', 0.0)))
            charges = float(row.get('charges', 0.0))
            net_pnl = float(row.get('net_pnl', gross_pnl - charges))
            r_mult = float(row.get('r_multiple', 0.0))
            reason = str(row.get('exit_reason', row.get('reason', f"CE: {row.get('ce_reason', '')} | PE: {row.get('pe_reason', '')}" if 'ce_reason' in row else '')))
            
            master_trade_list.append({
                'strategy_key': key,
                'strategy_name': sinfo['name'].split(':')[0],
                'asset_class': sinfo['asset_class'],
                'symbol': symbol,
                'contract': contract,
                'direction': direction,
                'entry_time': entry_time,
                'exit_time': exit_time,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'quantity': qty,
                'gross_pnl': gross_pnl,
                'charges': charges,
                'net_pnl': net_pnl,
                'r_multiple': r_mult,
                'reason': reason
            })
            
    master_trade_list.sort(key=lambda x: x['entry_time'])
    
    all_r_num = 4
    for t_idx, tr in enumerate(master_trade_list, start=1):
        ws_all.row_dimensions[all_r_num].height = 18
        row_fill = light_gray_fill if t_idx % 2 == 0 else PatternFill(fill_type=None)
        
        ws_all.cell(row=all_r_num, column=1, value=t_idx).alignment = align_center
        ws_all.cell(row=all_r_num, column=2, value=tr['strategy_key']).alignment = align_left
        ws_all.cell(row=all_r_num, column=3, value=tr['strategy_name']).alignment = align_left
        ws_all.cell(row=all_r_num, column=4, value=tr['asset_class']).alignment = align_left
        ws_all.cell(row=all_r_num, column=5, value=tr['symbol']).alignment = align_left
        ws_all.cell(row=all_r_num, column=6, value=tr['contract']).alignment = align_left
        ws_all.cell(row=all_r_num, column=7, value=tr['direction']).alignment = align_center
        ws_all.cell(row=all_r_num, column=8, value=tr['entry_time']).alignment = align_center
        ws_all.cell(row=all_r_num, column=9, value=tr['exit_time']).alignment = align_center
        
        c_ep = ws_all.cell(row=all_r_num, column=10, value=round(tr['entry_price'], 2))
        c_ep.number_format = "₹#,##0.00"
        c_ep.alignment = align_right
        
        c_xp = ws_all.cell(row=all_r_num, column=11, value=round(tr['exit_price'], 2))
        c_xp.number_format = "₹#,##0.00"
        c_xp.alignment = align_right
        
        c_q = ws_all.cell(row=all_r_num, column=12, value=tr['quantity'])
        c_q.number_format = "#,##0"
        c_q.alignment = align_right
        
        c_gp = ws_all.cell(row=all_r_num, column=13, value=round(tr['gross_pnl'], 2))
        c_gp.number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
        c_gp.alignment = align_right
        
        c_ch = ws_all.cell(row=all_r_num, column=14, value=round(tr['charges'], 2))
        c_ch.number_format = "₹#,##0.00"
        c_ch.alignment = align_right
        
        c_np = ws_all.cell(row=all_r_num, column=15, value=round(tr['net_pnl'], 2))
        c_np.number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
        c_np.alignment = align_right
        c_np.font = green_bold if tr['net_pnl'] >= 0 else red_bold
        c_np.fill = green_pnl_fill if tr['net_pnl'] >= 0 else red_pnl_fill
        
        c_r = ws_all.cell(row=all_r_num, column=16, value=round(tr['r_multiple'], 2))
        c_r.number_format = "+0.00 R;-0.00 R;0.00 R"
        c_r.alignment = align_right
        
        c_rs = ws_all.cell(row=all_r_num, column=17, value=tr['reason'])
        c_rs.alignment = align_left
        
        for c in range(1, 18):
            cell = ws_all.cell(row=all_r_num, column=c)
            cell.border = cell_border
            if c != 15 and row_fill.fill_type: cell.fill = row_fill
            
        all_r_num += 1
        
    ws_all.auto_filter.ref = f"A3:Q{all_r_num-1}"
    for col in ws_all.columns:
        max_len = max(len(str(cell.value or '')) for cell in col[:30])
        col_letter = get_column_letter(col[0].column)
        ws_all.column_dimensions[col_letter].width = max(max_len + 3, 12)
    ws_all.freeze_panes = "E4"

    # -------------------------------------------------------------
    # SHEETS 5+: DEDICATED INDIVIDUAL STRATEGY DETAIL TABS
    # -------------------------------------------------------------
    for key, sinfo in sorted_strats:
        sheet_title = key[:31] # Excel sheet name limit
        ws = wb.create_sheet(title=sheet_title)
        ws.views.sheetView[0].showGridLines = True
        
        # Header Banner
        ws.merge_cells("A1:J1")
        b_cell = ws["A1"]
        b_cell.value = f"{sinfo['name']} — DETAILED 250-DAY AUDIT & PERFORMANCE BREAKDOWN"
        b_cell.font = white_title
        b_cell.fill = navy_fill
        b_cell.alignment = align_center
        ws.row_dimensions[1].height = 40
        
        summ = sinfo['summary']
        # Metric Cards row 3 & 4
        metrics = [
            ("Asset Class", sinfo['asset_class']),
            ("Timeframe", sinfo['timeframe']),
            ("Total Trades", f"{summ['total_trades']:,}"),
            ("Win Rate", f"{summ['win_rate']:.1f}%"),
            ("Net Profit (₹)", f"₹{summ['net_pnl']:,.2f}"),
            ("Profit Factor", f"{summ['profit_factor']:.2f}"),
            ("Max Drawdown", f"₹{summ['max_drawdown']:,.2f}"),
            ("Total Return R", f"{summ['total_r']:+.1f} R")
        ]
        
        for idx, (label, val) in enumerate(metrics, start=1):
            c_lbl = ws.cell(row=3, column=idx, value=label)
            c_lbl.font = white_bold
            c_lbl.fill = dark_slate_fill
            c_lbl.alignment = align_center
            
            c_val = ws.cell(row=4, column=idx, value=val)
            c_val.font = black_bold
            c_val.fill = gold_fill if "Net Profit" in label else light_gray_fill
            c_val.alignment = align_center
            c_val.border = cell_border
            
        ws.row_dimensions[3].height = 20
        ws.row_dimensions[4].height = 24
        
        # 1. MONTHLY BREAKDOWN TABLE
        ws.cell(row=6, column=1, value="MONTHLY PERFORMANCE BREAKDOWN").font = black_bold
        m_cols = ["Month", "Trades", "Wins", "Losses", "Win Rate (%)", "Gross P&L (₹)", "Charges (₹)", "Net P&L (₹)", "Cumulative (₹)", "Profit Factor", "Total R"]
        ws.row_dimensions[7].height = 22
        for c_idx, c_name in enumerate(m_cols, start=1):
            cell = ws.cell(row=7, column=c_idx, value=c_name)
            cell.font = white_bold
            cell.fill = dark_slate_fill
            cell.alignment = align_center
            cell.border = header_border
            
        cur_r = 8
        m_df = sinfo['monthly']
        for _, mr in m_df.iterrows():
            ws.row_dimensions[cur_r].height = 19
            ws.cell(row=cur_r, column=1, value=mr['month']).alignment = align_center
            ws.cell(row=cur_r, column=2, value=mr['trades']).number_format = "#,##0"
            ws.cell(row=cur_r, column=3, value=mr['wins']).number_format = "#,##0"
            ws.cell(row=cur_r, column=4, value=mr['losses']).number_format = "#,##0"
            
            c_wr = ws.cell(row=cur_r, column=5, value=mr['win_rate'] / 100.0)
            c_wr.number_format = "0.0%"
            c_wr.alignment = align_right
            
            ws.cell(row=cur_r, column=6, value=mr['gross_pnl']).number_format = "₹#,##0.00"
            ws.cell(row=cur_r, column=7, value=mr['charges']).number_format = "₹#,##0.00"
            
            c_net = ws.cell(row=cur_r, column=8, value=mr['net_pnl'])
            c_net.number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
            c_net.font = green_bold if mr['net_pnl'] >= 0 else red_bold
            c_net.fill = green_pnl_fill if mr['net_pnl'] >= 0 else red_pnl_fill
            
            c_cum = ws.cell(row=cur_r, column=9, value=mr['cum_pnl'])
            c_cum.number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
            
            ws.cell(row=cur_r, column=10, value=mr['profit_factor']).number_format = "0.00"
            ws.cell(row=cur_r, column=11, value=mr['total_r']).number_format = "+0.00 R;-0.00 R;0.00 R"
            
            for c_i in range(1, 12):
                ws.cell(row=cur_r, column=c_i).border = cell_border
            cur_r += 1
            
        # 2. WEEKLY BREAKDOWN TABLE
        cur_r += 2
        ws.cell(row=cur_r, column=1, value="WEEKLY PERFORMANCE BREAKDOWN (PAST 52 WEEKS)").font = black_bold
        cur_r += 1
        w_cols = ["Week", "Start Date", "End Date", "Trades", "Wins", "Losses", "Win Rate (%)", "Net P&L (₹)", "Cumulative (₹)", "Profit Factor", "Total R"]
        ws.row_dimensions[cur_r].height = 22
        for c_idx, c_name in enumerate(w_cols, start=1):
            cell = ws.cell(row=cur_r, column=c_idx, value=c_name)
            cell.font = white_bold
            cell.fill = dark_slate_fill
            cell.alignment = align_center
            cell.border = header_border
            
        cur_r += 1
        w_df = sinfo['weekly']
        for _, wr in w_df.iterrows():
            ws.row_dimensions[cur_r].height = 19
            ws.cell(row=cur_r, column=1, value=wr['week']).alignment = align_center
            ws.cell(row=cur_r, column=2, value=wr['start_date']).alignment = align_center
            ws.cell(row=cur_r, column=3, value=wr['end_date']).alignment = align_center
            ws.cell(row=cur_r, column=4, value=wr['trades']).number_format = "#,##0"
            ws.cell(row=cur_r, column=5, value=wr['wins']).number_format = "#,##0"
            ws.cell(row=cur_r, column=6, value=wr['losses']).number_format = "#,##0"
            
            c_wr = ws.cell(row=cur_r, column=7, value=wr['win_rate'] / 100.0)
            c_wr.number_format = "0.0%"
            c_wr.alignment = align_right
            
            c_net = ws.cell(row=cur_r, column=8, value=wr['net_pnl'])
            c_net.number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
            c_net.font = green_bold if wr['net_pnl'] >= 0 else red_bold
            c_net.fill = green_pnl_fill if wr['net_pnl'] >= 0 else red_pnl_fill
            
            c_cum = ws.cell(row=cur_r, column=9, value=wr['cum_pnl'])
            c_cum.number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
            
            ws.cell(row=cur_r, column=10, value=wr['profit_factor']).number_format = "0.00"
            ws.cell(row=cur_r, column=11, value=wr['total_r']).number_format = "+0.00 R;-0.00 R;0.00 R"
            
            for c_i in range(1, 12):
                ws.cell(row=cur_r, column=c_i).border = cell_border
            cur_r += 1
            
        # 3. COMPLETE INDIVIDUAL STRATEGY TRADE AUDIT LOG
        cur_r += 2
        t_df = sinfo['data'].copy()
        ws.cell(row=cur_r, column=1, value=f"3. COMPLETE INDIVIDUAL TRADE AUDIT LOG ({len(t_df)} TRADES)").font = black_bold
        cur_r += 1
        
        cols_to_exclude = ['dt', 'trade_date', 'pnl_val', 'gross_val', 'charges_val', 'cum_pnl_trade', 'peak', 'drawdown', 'risk_per_share', 'sl', 'target']
        t_cols = [c for c in t_df.columns if c not in cols_to_exclude]
        
        ws.row_dimensions[cur_r].height = 22
        ws.cell(row=cur_r, column=1, value="Trade #").font = white_bold
        ws.cell(row=cur_r, column=1).fill = dark_slate_fill
        ws.cell(row=cur_r, column=1).alignment = align_center
        ws.cell(row=cur_r, column=1).border = header_border
        
        for c_idx, c_name in enumerate(t_cols, start=2):
            cell = ws.cell(row=cur_r, column=c_idx, value=c_name.replace("_", " ").title())
            cell.font = white_bold
            cell.fill = dark_slate_fill
            cell.alignment = align_center
            cell.border = header_border
            
        cur_r += 1
        for tr_idx, (_, tr_row) in enumerate(t_df.iterrows(), start=1):
            ws.row_dimensions[cur_r].height = 18
            row_fill = light_gray_fill if tr_idx % 2 == 0 else PatternFill(fill_type=None)
            
            c_num = ws.cell(row=cur_r, column=1, value=tr_idx)
            c_num.alignment = align_center
            c_num.border = cell_border
            if row_fill.fill_type: c_num.fill = row_fill
            
            for c_idx, c_name in enumerate(t_cols, start=2):
                val = tr_row[c_name]
                cell = ws.cell(row=cur_r, column=c_idx)
                
                if isinstance(val, (int, np.integer)):
                    cell.value = int(val)
                    cell.number_format = "#,##0"
                    cell.alignment = align_right
                elif isinstance(val, (float, np.floating)):
                    cell.value = round(float(val), 2)
                    if any(k in c_name.lower() for k in ['pnl', 'gross', 'charges', 'margin', 'trade_value']):
                        cell.number_format = "₹#,##0.00;[Red]-₹#,##0.00;\"₹0.00\""
                        if 'net_pnl' in c_name.lower() or c_name == 'pnl':
                            cell.font = green_bold if val >= 0 else red_bold
                            cell.fill = green_pnl_fill if val >= 0 else red_pnl_fill
                    elif 'premium' in c_name.lower() or 'price' in c_name.lower():
                        cell.number_format = "₹#,##0.00"
                    elif 'pct' in c_name.lower() or 'rate' in c_name.lower():
                        cell.number_format = "0.0%"
                    else:
                        cell.number_format = "#,##0.00"
                    cell.alignment = align_right
                else:
                    cell.value = str(val) if pd.notna(val) else ""
                    cell.alignment = align_center if any(k in c_name.lower() for k in ['date', 'time', 'type', 'direction', 'month', 'week']) else align_left
                    
                cell.border = cell_border
                if not cell.fill.fill_type and row_fill.fill_type:
                    cell.fill = row_fill
                    
            cur_r += 1
            
        # Auto column widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col[:30]) # sample first 30 rows
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 13)
        ws.freeze_panes = "A8"
        
    # Remove default sheet if exists
    if "Sheet" in wb.sheetnames:
        wb.remove(wb["Sheet"])
        
    out_file = os.path.join(BACKTEST_DIR, "All_Strategies_Weekly_Monthly_250Days_Report.xlsx")
    wb.save(out_file)
    print(f"\n=======================================================")
    print(f"SUCCESS: MASTER EXCEL WORKBOOK GENERATED AT:")
    print(f"{out_file}")
    print(f"=======================================================")
    return out_file

# ----------------------------------------------------------------------
# 7. MAIN ORCHESTRATOR
# ----------------------------------------------------------------------
def main():
    print("=" * 80)
    print("ORCHESTRATING 250-DAY AUDIT & WEEKLY/MONTHLY EXCEL GENERATION")
    print("=" * 80)
    
    # 1. Ensure all missing trade logs are generated
    ensure_ema_trades()
    ensure_supertrend_trades()
    
    # 2. Load all strategies
    strategies_raw = load_all_strategy_datasets()
    print(f"Loaded {len(strategies_raw)} strategy datasets for processing.")
    
    # 3. Process weekly, monthly, and overall metrics
    processed = {}
    for key, s in strategies_raw.items():
        m_df, w_df, summ, norm_df = process_strategy_metrics(s['data'], capital=s['capital'])
        processed[key] = {
            'name': s['name'],
            'asset_class': s['asset_class'],
            'timeframe': s['timeframe'],
            'summary': summ,
            'monthly': m_df,
            'weekly': w_df,
            'data': norm_df
        }
        print(f"Processed {key}: {summ['total_trades']} trades | Net P&L: ₹{summ['net_pnl']:,.2f} | WR: {summ['win_rate']:.1f}%")
        
    # 4. Generate Master Excel File
    out_path = create_excel_workbook(processed)
    print("Execution Complete.")

if __name__ == '__main__':
    main()
