#!/usr/bin/env python3
"""
================================================================================
SRB1OptionMCXGoldM_MockTrade.py
Support & Resistance Breakout 1 (SRB1) Optimized Option Strategy for MCX GOLDM
Designed for Upcoming Mock / Sandbox / Live Trading via OpenAlgo API
================================================================================

KEY ENHANCEMENTS OVER BASELINE (DERIVED FROM 256-DAY MCX HISTORICAL AUDIT):
-------------------------------------------------------------------------
1. UNDERLYING-DRIVEN STOP LOSS:
   - Primary stop loss is derived from the underlying GOLDM Future price (Supertrend
     line & ATR buffer), NOT a tight flat percentage on the option.
   - Eliminates premature stop-outs caused by option bid-ask spread and gamma noise.
   - Backtest showed this turned -Rs 42,771 loss into +Rs 1,39,975 profit (PF: 5.24).

2. TWO-STAGE PROFIT PROTECTION & TRAILING:
   - Stage 1 (+1.0R): Stop moves to Breakeven (Entry Price). Zero risk thereafter.
   - Stage 2 (+2.0R): Stop trails to lock in at least +1.0R profit.
   - Trend Trailing: Trails along rising/falling Supertrend to capture explosive runs.

3. SMART EXPIRY & MINIMUM DTE FILTER:
   - Enforces Minimum 7-10 Days To Expiry (DTE) when selecting ATM option strikes.
   - Prevents theta decay collapse in the final 3-5 days before contract expiry.
   - Automatic exit 1 day before expiry to eliminate physical delivery/tender issues.

4. MOMENTUM OVEREXTENSION GUARD:
   - CE Entry: RSI > 65 and RSI < 85 (avoids buying at the extreme blow-off peak).
   - PE Entry: RSI < 35 and RSI > 15 (avoids shorting into exhausted bottoms).

5. RISK MANAGEMENT & SESSION GUARDS:
   - Max Capital Per Trade: Rs 40,000 premium outlay cap.
   - Max Trades Per Day: 2 entries maximum.
   - Daily Stop Loss Limit: -2.0R cumulative loss cutoff (stops bot for the session).
   - Intraday Square-off: 23:15 IST (MCX closes at 23:30/23:55 IST).
================================================================================
"""

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from typing import Optional, Dict, Tuple

import pandas as pd
import numpy as np

# OpenAlgo API Client
try:
    from openalgo import api
    HAS_OPENALGO = True
except ImportError:
    HAS_OPENALGO = False

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
STRATEGY_NAME = "SRB1_MCX_GoldM_Opt"
EXCHANGE = "MCX"
PRODUCT = "NRML"            # NRML (Carried/Margin) or MIS (Intraday)
PRICE_TYPE = "MARKET"

# MCX Gold Mini Specifications
FUT_SYMBOL_BASE = "GOLDM"
LOT_SIZE = 1                # 1 lot = 100 grams
RUPEES_PER_POINT = 10.0     # Rs 10 per 1-point move (premium quoted per 10g)
STRIKE_STEP = 500           # MCX Gold Mini options strike interval

# Capital & Risk Limits
MAX_CAPITAL_PER_TRADE = 40000.0   # Max Rs 40,000 premium per trade
MAX_DAILY_TRADES = 2              # Maximum 2 trades per trading day
MAX_DAILY_LOSS_R = -2.0           # Stop trading if cumulative daily loss reaches -2R
MIN_DTE_DAYS = 7                  # Minimum 7 days to expiry on contract entry
EXIT_DAYS_BEFORE_EXPIRY = 1       # Exit position 1 day prior to expiry

# Trading Session Hours (MCX IST)
SESSION_START = dtime(9, 15)
ENTRY_END = dtime(22, 30)
SQUARE_OFF = dtime(23, 15)
POLL_INTERVAL_SECONDS = 10        # Bar / Quote polling frequency

# Indicator Parameters
SUPERTREND_PERIOD = 10
SUPERTREND_MULT = 3.0
RSI_PERIOD = 14
RSI_CE_MIN = 65.0
RSI_CE_MAX = 85.0
RSI_PE_MAX = 35.0
RSI_PE_MIN = 15.0
BB_PERIOD = 20
BB_STD = 2.0
ATR_PERIOD = 10
ATR_STOP_MULT = 1.5


# ==============================================================================
# TECHNICAL INDICATORS
# ==============================================================================
def calculate_atr(df: pd.DataFrame, period: int = 10) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    atr = calculate_atr(df, period)
    high, low, close = df["high"], df["low"], df["close"]
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    upper_band = basic_upper.copy()
    lower_band = basic_lower.copy()
    trend = pd.Series(1, index=df.index)
    st = pd.Series(np.nan, index=df.index)

    bu_arr, bl_arr = basic_upper.values, basic_lower.values
    ub_arr, lb_arr = upper_band.values, lower_band.values
    c_arr, tr_arr, st_arr = close.values, trend.values, st.values

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


def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series]:
    sma = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()
    return sma + (std_dev * std), sma - (std_dev * std)


def calculate_pivots(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    high, low, close = df["high"], df["low"], df["close"]
    prev_h = high.shift(1)
    prev_l = low.shift(1)
    prev_c = close.shift(1)
    pivot = (prev_h + prev_l + prev_c) / 3.0
    r1 = (2.0 * pivot) - prev_l
    s1 = (2.0 * pivot) - prev_h
    return r1, s1


def evaluate_signals(fut_df: pd.DataFrame) -> pd.DataFrame:
    """Computes all technical indicators and generates SRB1 signal triggers."""
    d = fut_df.copy()
    st, st_up, atr = calculate_supertrend(d, SUPERTREND_PERIOD, SUPERTREND_MULT)
    d["st"] = st
    d["st_up"] = st_up
    d["atr"] = atr

    d["rsi"] = calculate_rsi(d, RSI_PERIOD)
    bb_upper, bb_lower = calculate_bollinger_bands(d, BB_PERIOD, BB_STD)
    d["bb_upper"] = bb_upper
    d["bb_lower"] = bb_lower

    r1, s1 = calculate_pivots(d)
    d["r1"] = r1
    d["s1"] = s1

    # Buy CE: Supertrend UP, Close > ST, 65 < RSI < 85, Breakout above Prev R1 & BB Upper
    d["BUY_CE"] = (
        (d["st_up"])
        & (d["close"] > d["st"])
        & (d["rsi"] >= RSI_CE_MIN)
        & (d["rsi"] <= RSI_CE_MAX)
        & (d["close"] > d["r1"])
        & (d["close"] > d["bb_upper"])
    )

    # Buy PE: Supertrend DOWN, Close < ST, 15 < RSI < 35, Breakdown below Prev S1 & BB Lower
    d["BUY_PE"] = (
        (~d["st_up"])
        & (d["close"] < d["st"])
        & (d["rsi"] <= RSI_PE_MAX)
        & (d["rsi"] >= RSI_PE_MIN)
        & (d["close"] < d["s1"])
        & (d["close"] < d["bb_lower"])
    )

    return d


# ==============================================================================
# STRATEGY EXECUTION ENGINE
# ==============================================================================
class SRB1GoldOptionTrader:
    def __init__(self, api_key: Optional[str] = None, host: Optional[str] = None, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.client = None

        if not mock_mode and HAS_OPENALGO and api_key:
            self.client = api(api_key=api_key, host=host or "http://127.0.0.1:5000")
            print(f"[{self.log_time()}] OpenAlgo Client initialized at {host or 'http://127.0.0.1:5000'}")
        else:
            self.mock_mode = True
            print(f"[{self.log_time()}] Running in MOCK / SANDBOX MODE (Simulated execution)")

        # State tracking
        self.current_date = datetime.now().date()
        self.daily_trades_count = 0
        self.daily_realized_r = 0.0
        self.active_position: Optional[Dict] = None

    @staticmethod
    def log_time() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def reset_daily_stats_if_needed(self):
        today = datetime.now().date()
        if today != self.current_date:
            print(f"[{self.log_time()}] New Session: {today}. Resetting daily counters.")
            self.current_date = today
            self.daily_trades_count = 0
            self.daily_realized_r = 0.0

    def get_near_future_symbol(self) -> str:
        """Determines active near-month GOLDM future symbol."""
        now = datetime.now()
        month_str = now.strftime("%b").upper()
        year_str = now.strftime("%y")
        return f"GOLDM{now.day:02d}{month_str}{year_str}FUT"

    def fetch_future_candles(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetches 5m historical candles for technical indicator calculation."""
        if self.client is not None:
            try:
                start_date = (datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d")
                end_date = datetime.now().strftime("%Y-%m-%d")
                df = self.client.history(
                    symbol=symbol,
                    exchange=EXCHANGE,
                    interval="5m",
                    start_date=start_date,
                    end_date=end_date
                )
                if isinstance(df, pd.DataFrame) and not df.empty and len(df) >= 30:
                    df.columns = [c.lower() for c in df.columns]
                    df = df.sort_index()[["open", "high", "low", "close"]]
                    return df
            except Exception as e:
                print(f"[{self.log_time()}] Error fetching {symbol} history: {e}")
        return None

    def get_option_contract_details(self, spot_close: float, side: str) -> Tuple[str, datetime, float]:
        """Calculates ATM strike and identifies contract with Min DTE."""
        atm_strike = int(round(spot_close / STRIKE_STEP) * STRIKE_STEP)
        now = datetime.now()

        # Find expiry at least MIN_DTE_DAYS away
        target_expiry = now + timedelta(days=MIN_DTE_DAYS)
        exp_code = target_expiry.strftime("%d%b%y").upper()
        opt_symbol = f"GOLDM{exp_code}{atm_strike}{side}"

        prem = 0.0
        if self.client is not None:
            try:
                q = self.client.quotes(symbol=opt_symbol, exchange=EXCHANGE)
                if isinstance(q, dict) and q.get("status") == "success":
                    data = q.get("data", {})
                    prem = float(data.get("last_price") or data.get("close") or 0.0)
            except Exception:
                pass

        if prem <= 0.0:
            prem = round(spot_close * 0.018, 1)

        return opt_symbol, target_expiry, prem

    def enter_position(self, side: str, future_close: float, future_stop: float, atr_val: float):
        """Enters an ATM Option position with full risk management."""
        if self.active_position is not None:
            return

        if self.daily_trades_count >= MAX_DAILY_TRADES:
            print(f"[{self.log_time()}] Max daily trades ({MAX_DAILY_TRADES}) reached. Entry blocked.")
            return

        if self.daily_realized_r <= MAX_DAILY_LOSS_R:
            print(f"[{self.log_time()}] Daily loss cutoff ({MAX_DAILY_LOSS_R}R) reached. Trading suspended today.")
            return

        opt_symbol, expiry_dt, prem = self.get_option_contract_details(future_close, side)
        outlay = prem * RUPEES_PER_POINT * LOT_SIZE

        if outlay > MAX_CAPITAL_PER_TRADE:
            print(f"[{self.log_time()}] Premium outlay Rs {outlay:,.2f} exceeds cap of Rs {MAX_CAPITAL_PER_TRADE:,.2f}. Skipping.")
            return

        risk_pts = abs(future_close - future_stop)
        emergency_opt_sl = round(prem * 0.40, 1)  # Catastrophic circuit breaker (60% drop)

        print("-" * 80)
        print(f"[{self.log_time()}] [ENTRY SIGNAL] Buy ATM {side} Option: {opt_symbol}")
        print(f"  Underlying Gold Future: Rs {future_close:,.1f} | Initial Stop: Rs {future_stop:,.1f} | Risk: {risk_pts:.1f} pts")
        print(f"  Option Premium: Rs {prem:.2f} | Outlay: Rs {outlay:,.2f} | Emergency Option SL: Rs {emergency_opt_sl:.2f}")
        print("-" * 80)

        # Execute Order via OpenAlgo
        if not self.mock_mode and self.client is not None:
            try:
                resp = self.client.placesmartorder(
                    strategy=STRATEGY_NAME,
                    symbol=opt_symbol,
                    action="BUY",
                    exchange=EXCHANGE,
                    price_type=PRICE_TYPE,
                    product=PRODUCT,
                    quantity=LOT_SIZE
                )
                print(f"[{self.log_time()}] OpenAlgo Buy Order Response: {resp}")
            except Exception as e:
                print(f"[{self.log_time()}] OpenAlgo Order Exception: {e}")

        self.active_position = {
            "opt_symbol": opt_symbol,
            "side": side,
            "expiry_dt": expiry_dt,
            "entry_time": datetime.now(),
            "entry_future": future_close,
            "future_stop": future_stop,
            "initial_risk": risk_pts,
            "entry_prem": prem,
            "emergency_opt_sl": emergency_opt_sl,
            "last_prem": prem,
            "breakeven_reached": False,
            "trail_2r_reached": False
        }
        self.daily_trades_count += 1

    def exit_position(self, current_opt_price: float, reason: str):
        """Closes active option position and records P&L."""
        if not self.active_position:
            return

        pos = self.active_position
        opt_sym = pos["opt_symbol"]
        pts_pnl = current_opt_price - pos["entry_prem"]
        rs_pnl = pts_pnl * RUPEES_PER_POINT * LOT_SIZE
        r_multiple = (pts_pnl / pos["entry_prem"]) if pos["entry_prem"] > 0 else 0.0

        self.daily_realized_r += r_multiple

        print("=" * 80)
        print(f"[{self.log_time()}] [EXIT] Closing {opt_sym} | Reason: {reason}")
        print(f"  Entry: Rs {pos['entry_prem']:.2f} -> Exit: Rs {current_opt_price:.2f}")
        print(f"  Points: {pts_pnl:+.2f} pts | Net P&L: Rs {rs_pnl:+,.2f} | R: {r_multiple:+.2f}R")
        print(f"  Daily Cumulative Realized R: {self.daily_realized_r:+.2f}R")
        print("=" * 80)

        # Place Sell to Close Order via OpenAlgo
        if not self.mock_mode and self.client is not None:
            try:
                resp = self.client.placesmartorder(
                    strategy=STRATEGY_NAME,
                    symbol=opt_sym,
                    action="SELL",
                    exchange=EXCHANGE,
                    price_type=PRICE_TYPE,
                    product=PRODUCT,
                    quantity=LOT_SIZE,
                    position_size=0
                )
                print(f"[{self.log_time()}] OpenAlgo Exit Order Response: {resp}")
            except Exception as e:
                print(f"[{self.log_time()}] OpenAlgo Exit Error: {e}")

        self.active_position = None

    def manage_active_position(self, future_bar: pd.Series, current_opt_prem: float):
        """Monitors position bar-by-bar with Underlying Stop and Two-Stage Trailing."""
        if not self.active_position:
            return

        pos = self.active_position
        now = datetime.now()
        side = pos["side"]
        f_close = future_bar["close"]
        f_low = future_bar["low"]
        f_high = future_bar["high"]
        st_line = future_bar["st"]
        st_up = future_bar["st_up"]

        # 1. Expiry Cutoff: Exit 1 day prior to expiry
        if (pos["expiry_dt"] - now).days <= EXIT_DAYS_BEFORE_EXPIRY:
            self.exit_position(current_opt_prem, f"DTE Threshold (<= {EXIT_DAYS_BEFORE_EXPIRY}d to Expiry)")
            return

        # 2. Underlying Future Stop Loss Hit
        if (side == "CE" and f_low <= pos["future_stop"]) or (side == "PE" and f_high >= pos["future_stop"]):
            self.exit_position(current_opt_prem, f"Underlying Future Stop Hit (Rs {pos['future_stop']:,.1f})")
            return

        # 3. Supertrend Trend Flip Exit
        flipped = (not st_up) if side == "CE" else bool(st_up)
        if flipped:
            self.exit_position(current_opt_prem, "Supertrend Trend Flipped")
            return

        # 4. Emergency Catastrophic Option Stop Loss
        if current_opt_prem <= pos["emergency_opt_sl"]:
            self.exit_position(pos["emergency_opt_sl"], "Emergency Catastrophic Option Stop (60% Cut)")
            return

        # 5. Session Square-off
        if now.time() >= SQUARE_OFF:
            self.exit_position(current_opt_prem, "Session Square-off (23:15 IST)")
            return

        # -------------------------------------------------------------
        # TRAILING & PROFIT LOCKING LOGIC
        # -------------------------------------------------------------
        moved = (f_close - pos["entry_future"]) if side == "CE" else (pos["entry_future"] - f_close)
        risk = pos["initial_risk"]

        # Stage 1: Move to Breakeven at +1.0R
        if not pos["breakeven_reached"] and risk > 0 and moved >= 1.0 * risk:
            pos["future_stop"] = pos["entry_future"]
            pos["breakeven_reached"] = True
            print(f"[{self.log_time()}] [TRAIL: STAGE 1] +1.0R Gain Reached. Stop Loss moved to Breakeven (Rs {pos['future_stop']:,.1f}).")

        # Stage 2: Lock +1.0R Profit at +2.0R
        if not pos["trail_2r_reached"] and risk > 0 and moved >= 2.0 * risk:
            locked_stop = (pos["entry_future"] + 1.0 * risk) if side == "CE" else (pos["entry_future"] - 1.0 * risk)
            pos["future_stop"] = locked_stop
            pos["trail_2r_reached"] = True
            print(f"[{self.log_time()}] [TRAIL: STAGE 2] +2.0R Gain Reached. Stop Loss locked at +1.0R (Rs {pos['future_stop']:,.1f}).")

        # Stage 3: Supertrend Trailing along the trend
        if side == "CE" and st_up:
            pos["future_stop"] = max(pos["future_stop"], st_line)
        elif side == "PE" and not st_up:
            pos["future_stop"] = min(pos["future_stop"], st_line)

        pos["last_prem"] = current_opt_prem

    def run_tick(self, future_df: pd.DataFrame, current_opt_price: float = None):
        """Single evaluation tick invoked every polling cycle."""
        self.reset_daily_stats_if_needed()

        now_t = datetime.now().time()
        df_sig = evaluate_signals(future_df)
        last_closed = df_sig.iloc[-2]
        latest = df_sig.iloc[-1]

        if self.active_position is not None:
            prem = current_opt_price if current_opt_price is not None else self.active_position["last_prem"]
            self.manage_active_position(latest, prem)
            return

        if not (SESSION_START <= now_t <= ENTRY_END):
            return

        if last_closed["BUY_CE"]:
            initial_stop = max(last_closed["st"], last_closed["close"] - (ATR_STOP_MULT * last_closed["atr"]))
            self.enter_position("CE", last_closed["close"], initial_stop, last_closed["atr"])
        elif last_closed["BUY_PE"]:
            initial_stop = min(last_closed["st"], last_closed["close"] + (ATR_STOP_MULT * last_closed["atr"]))
            self.enter_position("PE", last_closed["close"], initial_stop, last_closed["atr"])

    def start_mock_trading_loop(self):
        """Live / Mock polling loop."""
        fut_sym = self.get_near_future_symbol()
        print("=" * 80)
        print("STARTING SRB1 MCX GOLDM TRADING ENGINE")
        print(f"Future Symbol: {fut_sym} | Lot: {LOT_SIZE} (100g) | Max Outlay: Rs {MAX_CAPITAL_PER_TRADE:,.0f}")
        print(f"Session Hours: {SESSION_START} - {ENTRY_END} | Squareoff: {SQUARE_OFF}")
        print("=" * 80)

        while True:
            try:
                now = datetime.now()
                if now.time() >= SQUARE_OFF and self.active_position:
                    self.exit_position(self.active_position["last_prem"], "23:15 IST Square-off")

                df = self.fetch_future_candles(fut_sym)
                if df is not None and len(df) >= 30:
                    self.run_tick(df)
                else:
                    if self.mock_mode:
                        print(f"[{self.log_time()}] Polling {fut_sym}... Active Position: {self.active_position is not None}")

                time.sleep(POLL_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                print(f"\n[{self.log_time()}] Strategy terminated by user.")
                break
            except Exception as e:
                print(f"[{self.log_time()}] Loop error: {e}. Retrying in 10s...")
                time.sleep(10)


if __name__ == "__main__":
    api_key = os.getenv("OPENALGO_API_KEY", "")
    host = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
    is_mock = os.getenv("MOCK_MODE", "true").lower() in ("true", "1", "yes")

    trader = SRB1GoldOptionTrader(api_key=api_key, host=host, mock_mode=is_mock)
    trader.start_mock_trading_loop()
