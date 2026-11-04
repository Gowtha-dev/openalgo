#!/usr/bin/env python3
"""
Backtest Engine: Daily Nifty 9:20 Intraday Short Straddle (Selling Both CE & PE)
Capital: Rs 14,00,000 (Same as Gap Reversion Strategy)
Strategy Rules:
---------------
- Underlying: NIFTY 50 Index (^NSEI)
- Frequency: Every single trading day
- Entry: 09:20 AM (sell 1 lot ATM CE + 1 lot ATM PE)
- Capital Allocation: Selling 1 pair of Nifty Straddle requires ~Rs 1.4 Lakhs margin.
  With Rs 14 Lakhs total capital, we trade 8 Lots (Rs 11.2 Lakhs margin + Rs 2.8 Lakhs buffer).
- Stop Loss: 25% or 30% individual leg SL (if CE spikes +25%, exit CE, hold PE; or exit PE if PE spikes).
- Target / Exit: 15:15 PM session square-off (or when combined profit reaches target).
- Charges: Flat Rs 20/order brokerage + STT + NSE exchange turnover charges + GST.
"""

import os
import sys
import time
import math
from datetime import datetime, time as dtime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf

CAPITAL = 1400000.0  # Rs 14 Lakhs
NIFTY_LOT_SIZE = 75  # Nifty 50 lot size
LOTS_TRADED = 8      # 8 lots = 600 qty (requires ~Rs 11.5L margin, perfect fit for Rs 14L)
TOTAL_QTY = NIFTY_LOT_SIZE * LOTS_TRADED  # 600 shares

STOP_LOSS_PCT = 0.25  # 25% stop loss per leg
ENTRY_TIME = dtime(9, 20)
EXIT_TIME = dtime(15, 15)

def calculate_nifty_fno_charges(ce_entry, ce_exit, pe_entry, pe_exit, qty):
    # 4 orders total: Sell CE, Sell PE, Buy CE, Buy PE
    brokerage = 80.0  # 4 * Rs 20
    turnover = (ce_entry + ce_exit + pe_entry + pe_exit) * qty
    stt = (ce_entry + pe_entry) * qty * 0.001  # STT on sell side
    exchange_txn = turnover * 0.0005
    sebi_fee = turnover * 0.000001
    stamp_duty = (ce_exit + pe_exit) * qty * 0.00003
    gst = (brokerage + exchange_txn + sebi_fee) * 0.18
    return round(brokerage + stt + exchange_txn + sebi_fee + stamp_duty + gst, 2)


def estimate_nifty_atm_premium(spot_price, iv=0.14, dte=3):
    """ATM Straddle premium for near weekly expiry: ~1.0% to 1.3% of spot price per leg."""
    t = max(dte, 0.5) / 365.0
    return max(20.0, 0.40 * spot_price * iv * math.sqrt(t))


def run_nifty_straddle_backtest(period="250d", interval="1h"):
    print(f"Downloading Nifty data for {period} ({interval})...")
    raw = yf.download("^NSEI", period=period, interval=interval, progress=False)
    if raw.empty:
        print("Could not download Nifty data.")
        sys.exit(1)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]

    raw['timestamp'] = pd.to_datetime(raw.index)
    if raw['timestamp'].dt.tz is not None:
        raw['timestamp'] = raw['timestamp'].dt.tz_localize(None)

    raw = raw.sort_values('timestamp').reset_index(drop=True)
    raw['date'] = raw['timestamp'].dt.date

    dates = raw['date'].unique()
    print(f"Loaded {len(dates)} trading days for Nifty Straddle simulation.")

    trades = []
    
    for d in dates:
        day_df = raw[raw['date'] == d].sort_values('timestamp')
        if len(day_df) < 3:
            continue

        open_bar = day_df.iloc[0]
        close_bar = day_df.iloc[-1]
        spot_entry = open_bar['open']
        spot_high = day_df['high'].max()
        spot_low = day_df['low'].min()
        spot_exit = close_bar['close']

        # Sell ATM CE + ATM PE at 09:20
        atm_strike = round(spot_entry / 50.0) * 50.0
        ce_entry_prem = estimate_nifty_atm_premium(spot_entry)
        pe_entry_prem = estimate_nifty_atm_premium(spot_entry)

        # Delta ~ 0.50, Theta decay during 6 hours ~ 15% to 20% of premium
        theta_decay = ce_entry_prem * 0.18

        # Track throughout the day if individual leg hits 25% SL
        # CE expands if Spot rises: Adverse = spot_high - spot_entry
        ce_max_adverse = max(0.0, spot_high - spot_entry)
        ce_max_prem = ce_entry_prem + (ce_max_adverse * 0.50)

        # PE expands if Spot falls: Adverse = spot_entry - spot_low
        pe_max_adverse = max(0.0, spot_entry - spot_low)
        pe_max_prem = pe_entry_prem + (pe_max_adverse * 0.50)

        ce_sl_hit = ce_max_prem >= (ce_entry_prem * (1.0 + STOP_LOSS_PCT))
        pe_sl_hit = pe_max_prem >= (pe_entry_prem * (1.0 + STOP_LOSS_PCT))

        # Determine CE exit premium
        if ce_sl_hit:
            ce_exit_prem = ce_entry_prem * (1.0 + STOP_LOSS_PCT)
            ce_reason = "CE SL Hit"
        else:
            # End of day price
            spot_net_move = spot_exit - spot_entry
            ce_exit_prem = max(0.5, ce_entry_prem + (spot_net_move * 0.50) - theta_decay)
            ce_reason = "Square-off 15:15"

        # Determine PE exit premium
        if pe_sl_hit:
            pe_exit_prem = pe_entry_prem * (1.0 + STOP_LOSS_PCT)
            pe_reason = "PE SL Hit"
        else:
            spot_net_move = spot_entry - spot_exit
            pe_exit_prem = max(0.5, pe_entry_prem + (spot_net_move * 0.50) - theta_decay)
            pe_reason = "Square-off 15:15"

        # Profit for option seller = (Sell Prem - Buy Prem) * Qty
        ce_pnl = (ce_entry_prem - ce_exit_prem) * TOTAL_QTY
        pe_pnl = (pe_entry_prem - pe_exit_prem) * TOTAL_QTY
        gross_pnl = ce_pnl + pe_pnl

        charges = calculate_nifty_fno_charges(ce_entry_prem, ce_exit_prem, pe_entry_prem, pe_exit_prem, TOTAL_QTY)
        net_pnl = gross_pnl - charges

        # Risk amount = 25% of both premiums * Qty
        day_risk = (ce_entry_prem + pe_entry_prem) * STOP_LOSS_PCT * TOTAL_QTY
        r_mult = gross_pnl / day_risk

        trades.append({
            "date": d,
            "nifty_spot_entry": round(spot_entry, 2),
            "nifty_spot_exit": round(spot_exit, 2),
            "atm_strike": int(atm_strike),
            "ce_entry_prem": round(ce_entry_prem, 2),
            "ce_exit_prem": round(ce_exit_prem, 2),
            "pe_entry_prem": round(pe_entry_prem, 2),
            "pe_exit_prem": round(pe_exit_prem, 2),
            "lots": LOTS_TRADED,
            "total_qty": TOTAL_QTY,
            "ce_reason": ce_reason,
            "pe_reason": pe_reason,
            "gross_pnl": round(gross_pnl, 2),
            "charges": charges,
            "net_pnl": round(net_pnl, 2),
            "r_multiple": round(r_mult, 2)
        })

    return pd.DataFrame(trades)


if __name__ == "__main__":
    t0 = time.time()
    df_trades = run_nifty_straddle_backtest(period="250d", interval="1h")

    out_dir = "openalgo/workspace/backtests"
    os.makedirs(out_dir, exist_ok=True)
    csv_file = os.path.join(out_dir, "trades_nifty_daily_straddle_250d.csv")
    df_trades.to_csv(csv_file, index=False)

    total_days = len(df_trades)
    wins = df_trades[df_trades['net_pnl'] > 0]
    losses = df_trades[df_trades['net_pnl'] <= 0]
    win_rate = len(wins) / total_days * 100.0

    gross_pnl = df_trades['gross_pnl'].sum()
    charges = df_trades['charges'].sum()
    net_pnl = df_trades['net_pnl'].sum()
    total_r = df_trades['r_multiple'].sum()
    avg_r = df_trades['r_multiple'].mean()

    gp = wins['net_pnl'].sum()
    gl = abs(losses['net_pnl'].sum())
    pf = gp / gl if gl > 0 else np.nan

    cum = df_trades['net_pnl'].cumsum()
    max_dd = (cum.cummax() - cum).max()
    roi = (net_pnl / CAPITAL) * 100.0

    print("\n" + "=" * 75)
    print(f" DAILY NIFTY SHORT STRADDLE (SELL BOTH CE & PE) - 250 TRADING DAYS")
    print(f" Capital: Rs {CAPITAL:,.0f} | 8 Lots (600 Qty) | 25% Stop Loss per leg")
    print("=" * 75)
    print(f"Total Trading Sessions  : {total_days}")
    print(f"Net Win Rate            : {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"Gross P&L               : Rs {gross_pnl:,.2f}")
    print(f"Brokerage & F&O Charges : Rs {charges:,.2f} (~Rs {df_trades['charges'].mean():.2f}/day)")
    print(f"Net P&L (After Charges) : Rs {net_pnl:,.2f}")
    print(f"Annual ROI on Rs 14L    : {roi:.1f}%")
    print(f"Total Return (R)        : {total_r:+.2f} R")
    print(f"Average R / Day         : {avg_r:+.3f} R")
    print(f"Net Profit Factor       : {pf:.2f}")
    print(f"Maximum Drawdown        : Rs {max_dd:,.2f} ({max_dd/CAPITAL*100:.1f}%)")
    print("=" * 75)
    print(f"CSV saved to: {csv_file}")
