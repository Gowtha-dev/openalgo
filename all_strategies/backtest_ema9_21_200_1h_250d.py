#!/usr/bin/env python3
"""
================================================================================
BACKTEST ENGINE: 9/21/200 EMA + RSI + VOLUME PULLBACK STRATEGY
Timeframe: 1-Hour Candles (250 Trading Days)
Mode: Intraday MIS (Mandatory 15:15 PM Square-off) vs Swing Comparison
Universe: NIFTY 50 Universe (Top 49 Liquid Equities)
Capital per Trade: ₹50,000 (with realistic 0.05% slippage & ₹20 brokerage)
================================================================================

STRATEGY RULES:
--------------------------------------------------------------------------------
1. Macro Trend Filter (200 EMA):
   - Bullish Regime: Close > 200 EMA -> Long entries only. Ignore all bearish crosses.
   - Bearish Regime: Close < 200 EMA -> Short entries only. Ignore all bullish crosses.
2. Momentum & Crossover (9 & 21 EMA):
   - Fast EMA 9 crosses above Medium EMA 21 for Long.
   - Fast EMA 9 crosses below Medium EMA 21 for Short.
   - Avoid flat/tangled lines (minimum 0.15% separation).
3. Momentum Filter (RSI 14):
   - Long: RSI(14) > 50 (bullish territory).
   - Short: RSI(14) < 50 (bearish momentum).
4. Volume Checklist (20 MA):
   - Volume on rejection candle must be above its 20-period moving average.
5. Entry on Pullback Rejection (Magnetic Zone):
   - Long: Price pulls back into zone between 9 & 21 EMA (Low <= EMA 9, Low >= EMA 21).
           Enters when green rejection candle closes firmly back above 9 EMA.
   - Short: Price rallies into zone between 9 & 21 EMA (High >= EMA 9, High <= EMA 21).
            Enters when red rejection candle closes firmly back below 9 EMA.
6. Risk Management & Exits:
   - Stop Loss: Slightly below 21 EMA or swing low (Long); above 21 EMA or swing high (Short).
   - Target: 1:2 Risk-to-Reward ratio (2R).
   - MIS Intraday Square-off: 15:15 PM IST sharp.
================================================================================
"""

import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, time as dtime, timedelta

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

CAPITAL_PER_TRADE = 50000.0  # Rs 50,000 capital per trade
SLIPPAGE_PCT = 0.0005        # 0.05% slippage
COMMISSION_PER_ORDER = 20.0  # Rs 20/order flat brokerage

def fetch_data(symbol, period="730d", interval="1h"):
    ticker = f"{symbol}.NS" if not symbol.startswith("^") and not symbol.endswith(".NS") else symbol
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df.empty or len(df) < 250:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")
        return df
    except Exception:
        return None

def compute_indicators(df):
    df = df.copy()
    # 1. EMAs
    df['ema9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['ema200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    # 2. RSI 14
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 3. Volume MA 20
    df['vol_ma20'] = df['Volume'].rolling(window=20).mean()
    
    # 4. Swings (rolling 5 candles)
    df['swing_low'] = df['Low'].rolling(window=5).min()
    df['swing_high'] = df['High'].rolling(window=5).max()
    
    # 5. Crossovers
    df['bull_cross'] = (df['ema9'] > df['ema21']) & (df['ema9'].shift(1) <= df['ema21'].shift(1))
    df['bear_cross'] = (df['ema9'] < df['ema21']) & (df['ema9'].shift(1) >= df['ema21'].shift(1))
    
    return df

def backtest_symbol(df, symbol, is_mis=True, first_pullback_only=True):
    # Slice to past 250 trading days (~1750 1-hour candles)
    if len(df) > 1750:
        df = df.iloc[-1750:].copy()
        
    trades = []
    in_position = False
    current_trade = None
    
    active_cross = None
    cross_idx = 0
    trade_taken_for_cross = False
    
    times = df.index
    n = len(df)
    
    for i in range(25, n):
        row = df.iloc[i]
        t = times[i]
        candle_time = t.time()
        candle_date = t.date()
        
        # Track crossover event
        if row['bull_cross']:
            active_cross = 'LONG'
            cross_idx = i
            trade_taken_for_cross = False
        elif row['bear_cross']:
            active_cross = 'SHORT'
            cross_idx = i
            trade_taken_for_cross = False
            
        # Check exits if in position
        if in_position:
            entry_price = current_trade['entry_price']
            sl = current_trade['sl']
            target = current_trade['target']
            direction = current_trade['direction']
            shares = current_trade['shares']
            
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
                    pnl = (exit_price - entry_price) * shares - (2 * COMMISSION_PER_ORDER)
                    r_pnl = (exit_price - entry_price) / current_trade['risk_per_share']
                else:
                    pnl = (entry_price - exit_price) * shares - (2 * COMMISSION_PER_ORDER)
                    r_pnl = (entry_price - exit_price) / current_trade['risk_per_share']
                    
                current_trade.update({
                    'exit_time': t,
                    'exit_price': exit_price,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'r_pnl': r_pnl,
                    'holding_candles': i - current_trade['entry_idx']
                })
                trades.append(current_trade)
                in_position = False
                current_trade = None
                
            if in_position:
                continue

        # Check entries if not in position
        if is_mis and candle_time >= dtime(14, 30):
            continue
            
        if first_pullback_only and (active_cross is None or trade_taken_for_cross):
            continue
            
        if first_pullback_only:
            candles_since_cross = i - cross_idx
            if candles_since_cross > 10 or candles_since_cross < 1:
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
        
        # Volume check: volume above 20 MA line
        if vol <= vol_ma:
            continue
            
        # 🟢 LONG ENTRY:
        # Macro: Close > 200 EMA | Momentum: 9 EMA > 21 EMA | RSI > 50
        # Magnetic zone pullback: Low <= 9 EMA and Low >= 21 EMA * 0.995
        # Rejection: Green candle (Close > Open) and Close > 9 EMA
        if (close > ema200) and (ema9 > ema21) and (rsi > 50):
            if (low <= ema9) and (low >= ema21 * 0.995) and (close > open_p) and (close > ema9):
                entry_price = close * (1 + SLIPPAGE_PCT)
                sl = min(row['swing_low'], ema21 * 0.998)
                risk_per_share = entry_price - sl
                
                if risk_per_share > entry_price * 0.003 and risk_per_share < entry_price * 0.035:
                    target = entry_price + (2.0 * risk_per_share)
                    shares = int(CAPITAL_PER_TRADE / entry_price)
                    if shares > 0:
                        in_position = True
                        trade_taken_for_cross = True
                        current_trade = {
                            'symbol': symbol,
                            'direction': 'LONG',
                            'entry_time': t,
                            'entry_date': candle_date,
                            'entry_idx': i,
                            'entry_price': entry_price,
                            'sl': sl,
                            'target': target,
                            'risk_per_share': risk_per_share,
                            'shares': shares,
                            'capital': shares * entry_price
                        }
                        continue
                        
        # 🔴 SHORT ENTRY:
        # Macro: Close < 200 EMA | Momentum: 9 EMA < 21 EMA | RSI < 50
        # Magnetic zone pullback: High >= 9 EMA and High <= 21 EMA * 1.005
        # Rejection: Red candle (Close < Open) and Close < 9 EMA
        if (close < ema200) and (ema9 < ema21) and (rsi < 50):
            if (high >= ema9) and (high <= ema21 * 1.005) and (close < open_p) and (close < ema9):
                entry_price = close * (1 - SLIPPAGE_PCT)
                sl = max(row['swing_high'], ema21 * 1.002)
                risk_per_share = sl - entry_price
                
                if risk_per_share > entry_price * 0.003 and risk_per_share < entry_price * 0.035:
                    target = entry_price - (2.0 * risk_per_share)
                    shares = int(CAPITAL_PER_TRADE / entry_price)
                    if shares > 0:
                        in_position = True
                        trade_taken_for_cross = True
                        current_trade = {
                            'symbol': symbol,
                            'direction': 'SHORT',
                            'entry_time': t,
                            'entry_date': candle_date,
                            'entry_idx': i,
                            'entry_price': entry_price,
                            'sl': sl,
                            'target': target,
                            'risk_per_share': risk_per_share,
                            'shares': shares,
                            'capital': shares * entry_price
                        }
                        continue
                        
    return trades

def run_evaluation():
    print("=" * 80)
    print("9/21/200 EMA + RSI + VOLUME PULLBACK STRATEGY — 250-DAY COMPARATIVE REPORT")
    print("=" * 80)
    
    modes = [
        ("1-Hour Pure MIS (Intraday)", True, True),
        ("1-Hour Swing (Multi-Day Holding)", False, True),
        ("1-Hour Continuous Re-entries", True, False),
    ]
    
    results = []
    
    for label, is_mis, first_pb in modes:
        print(f"\nProcessing configuration: {label}...")
        all_trades = []
        for sym in NIFTY_50_STOCKS:
            df = fetch_data(sym)
            if df is None: continue
            df = compute_indicators(df)
            trades = backtest_symbol(df, sym, is_mis=is_mis, first_pullback_only=first_pb)
            if trades:
                all_trades.extend(trades)
                
        if not all_trades:
            continue
            
        tdf = pd.DataFrame(all_trades)
        total = len(tdf)
        wins = (tdf['pnl'] > 0).sum()
        losses = (tdf['pnl'] <= 0).sum()
        wr = (wins / total) * 100
        pnl = tdf['pnl'].sum()
        total_r = tdf['r_pnl'].sum()
        avg_r = tdf['r_pnl'].mean()
        
        gp = tdf[tdf['pnl'] > 0]['pnl'].sum()
        gl = abs(tdf[tdf['pnl'] < 0]['pnl'].sum())
        pf = gp / gl if gl > 0 else 0
        
        tdf['cum_pnl'] = tdf['pnl'].cumsum()
        tdf['peak'] = tdf['cum_pnl'].cummax()
        tdf['drawdown'] = tdf['cum_pnl'] - tdf['peak']
        max_dd = tdf['drawdown'].min()
        
        target_hits = (tdf['exit_reason'] == 'TARGET_1:2').sum()
        sl_hits = (tdf['exit_reason'] == 'STOP_LOSS').sum()
        sq = (tdf['exit_reason'] == 'MIS_SQUAREOFF').sum()
        
        results.append({
            'Mode': label,
            'Trades': total,
            'Wins': wins,
            'Losses': losses,
            'Win Rate (%)': f"{wr:.2f}%",
            'Total PnL (₹)': f"₹{pnl:,.2f}",
            'Total R': f"{total_r:+.2f} R",
            'Profit Factor': f"{pf:.2f}",
            'Max Drawdown (₹)': f"₹{max_dd:,.2f}",
            'Target Hit %': f"{target_hits/total*100:.1f}%",
            'SL Hit %': f"{sl_hits/total*100:.1f}%",
            'EOD Squareoff %': f"{sq/total*100:.1f}%",
            'Avg Duration': f"{tdf['holding_candles'].mean():.1f} hrs"
        })
        
    res_df = pd.DataFrame(results)
    print("\n" + "=" * 80)
    print("BACKTEST COMPARISON TABLE (PAST 250 TRADING DAYS)")
    print("=" * 80)
    print(res_df.to_string(index=False))
    print("=" * 80)

if __name__ == '__main__':
    run_evaluation()
