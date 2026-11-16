#!/usr/bin/env python3
"""
SRB1OptionMCXGoldM5Min - Support & Resistance Breakout 1 (SRB1) Option Strategy for MCX GOLDM
Momentum Breakout Strategy trading ATM Call and Put options based on MCX GOLDM Futures signals.
"""

from dataclasses import dataclass
import pandas as pd
import numpy as np

LOTS = 1
RUPEES_PER_POINT = 10  # GOLDM lot size is 100g, premium is quoted in Rs per 10g


@dataclass
class Cfg:
    squareoff: str = "23:00"
    entry_end: str = "22:00"
    opt_sl_pct: float = 0.30        # 30% stop loss on option premium
    max_sl_atr: float = 1.5         # Initial future stop: 1.5 * ATR
    breakeven_r: float = 1.0        # Trail stop to breakeven when profit reaches +1R
    max_trades_day: int = 2         # Maximum entries allowed per trading day
    max_daily_loss_r: float = 2.0   # Daily risk cutoff at -2R cumulative loss
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    rsi_period: int = 14
    rsi_buy_threshold: float = 70.0
    rsi_sell_threshold: float = 30.0
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 10


def calculate_atr(df: pd.DataFrame, period: int = 10) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    atr = calculate_atr(df, period)
    high, low, close = df["high"], df["low"], df["close"]
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    upper_band = basic_upper.copy()
    lower_band = basic_lower.copy()
    trend = pd.Series(1, index=df.index)
    st = pd.Series(np.nan, index=df.index)

    bu_arr = basic_upper.values
    bl_arr = basic_lower.values
    ub_arr = upper_band.values
    lb_arr = lower_band.values
    c_arr = close.values
    tr_arr = trend.values
    st_arr = st.values

    for i in range(1, len(df)):
        if bl_arr[i] > lb_arr[i - 1] or c_arr[i - 1] < lb_arr[i - 1]:
            lb_arr[i] = bl_arr[i]
        else:
            lb_arr[i] = lb_arr[i - 1]

        if bu_arr[i] < ub_arr[i - 1] or c_arr[i - 1] > ub_arr[i - 1]:
            ub_arr[i] = bu_arr[i]
        else:
            ub_arr[i] = ub_arr[i - 1]

        prev_trend = tr_arr[i - 1]
        if prev_trend == 1:
            if c_arr[i] < lb_arr[i]:
                tr_arr[i] = -1
                st_arr[i] = ub_arr[i]
            else:
                tr_arr[i] = 1
                st_arr[i] = lb_arr[i]
        else:
            if c_arr[i] > ub_arr[i]:
                tr_arr[i] = 1
                st_arr[i] = lb_arr[i]
            else:
                tr_arr[i] = -1
                st_arr[i] = ub_arr[i]

    return pd.Series(st_arr, index=df.index), pd.Series(tr_arr == 1, index=df.index), atr


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)


def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0):
    sma = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    return upper, lower


def calculate_pivots(df: pd.DataFrame):
    """Calculates previous bar R1 and S1 pivot levels."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_h = high.shift(1)
    prev_l = low.shift(1)
    prev_c = close.shift(1)
    pivot = (prev_h + prev_l + prev_c) / 3.0
    r1 = (2.0 * pivot) - prev_l
    s1 = (2.0 * pivot) - prev_h
    return r1, s1


def add_signals(fut: pd.DataFrame, cfg: Cfg = None) -> pd.DataFrame:
    """Adds SRB1 indicator series and BUY_CE / BUY_PE trigger columns to fut DataFrame."""
    if cfg is None:
        cfg = Cfg()

    d = fut.copy()
    st, st_up, atr = calculate_supertrend(d, cfg.supertrend_period, cfg.supertrend_multiplier)
    d["st"] = st
    d["st_up"] = st_up
    d["atr"] = atr

    d["rsi"] = calculate_rsi(d, cfg.rsi_period)
    bb_upper, bb_lower = calculate_bollinger_bands(d, cfg.bb_period, cfg.bb_std)
    d["bb_upper"] = bb_upper
    d["bb_lower"] = bb_lower

    r1, s1 = calculate_pivots(d)
    d["r1"] = r1
    d["s1"] = s1

    # SRB1 Long (BUY_CE): Supertrend up, Close > ST, RSI > threshold, Close > R1, Close > BB Upper
    d["BUY_CE"] = (
        (d["st_up"])
        & (d["close"] > d["st"])
        & (d["rsi"] > cfg.rsi_buy_threshold)
        & (d["close"] > d["r1"])
        & (d["close"] > d["bb_upper"])
    )

    # SRB1 Short (BUY_PE): Supertrend down, Close < ST, RSI < threshold, Close < S1, Close < BB Lower
    d["BUY_PE"] = (
        (~d["st_up"])
        & (d["close"] < d["st"])
        & (d["rsi"] < cfg.rsi_sell_threshold)
        & (d["close"] < d["s1"])
        & (d["close"] < d["bb_lower"])
    )

    return d
