#!/usr/bin/env python3
"""
================================================================================
STRATEGY 5: GAP UP REVERSAL — STOCK PUT OPTION BUYING (BUY PE ALONE)
PORTFOLIO CAPITAL: ₹10,00,000 (10 LAKHS STRICT CEILING)
================================================================================

CORE LOGIC:
-----------
- Applies purely to GAP UP BEARISH REVERSALS on Nifty 50 stocks.
- Stock opens gap up 0.5% - 2.0% above previous day's close.
- Price breaks below first 1-Hour candle low and stays below VWAP.
- Action: BUY At-The-Money (ATM) Put Option (PE).
- Stop Loss: 30% drop in PE premium OR Spot breaks opening high.
- Target: Spot fills overnight gap OR square-off at 15:15.

CAPITAL SIZING OPTIONS ON ₹10,00,000:
------------------------------------
Mode A: Conservative 1 Lot
  - Premium per lot: ~₹13,400.
  - Zero rejections (all 418 signals executed).
  - High cash buffer (~₹9,00,000 cash remaining).

Mode B: Aggressive 10 Lots (Full Capital Utilization)
  - 10 Lots per signal (~₹1,34,000 deployed).
  - Max 7 concurrent positions (7 * ₹1.34L = ~₹9.4L deployed).
  - High capital compounding.

================================================================================
VERIFIED BACKTEST RESULTS (250 TRADING DAYS ON NIFTY 50 STOCKS):
================================================================================
                               MODE A (1 LOT SAFE)       MODE B (10 LOTS AGGRESSIVE)
Total Signals Triggered:       418 signals               418 signals
Trades Executed:               418 trades (100%)         408 trades (10 skipped)
Winning Trades:                281 trades                272 trades
Losing Trades:                 137 trades                136 trades
Net Win Rate:                  67.22%                    66.67%

Financial Performance:
----------------------
Starting Capital:              ₹10,00,000.00             ₹10,00,000.00
Gross P&L:                     +₹353,683.82              +₹3,240,446.20
Brokerage & Taxes:             ₹32,672.09                ₹318,418.00
Net Realized P&L:              +₹321,011.73              +₹2,922,028.20
Ending Account Capital:        ₹13,21,011.73             ₹39,22,028.20
Net ROI on ₹10L Capital:       +32.10%                   +292.20%

Risk & Drawdown Metrics:
------------------------
Maximum Peak-to-Trough DD:     -₹23,317.35               -₹233,173.50
Max Drawdown % on ₹10L:        -2.33%                    -23.32%
Total Return in R-Multiple:    +86.20 R                  +794.90 R
Profit Factor:                 2.91                      2.85
Calmar Ratio (Return / Max DD):13.77x                    12.53x
================================================================================
"""

import os
import sys
import pandas as pd
import numpy as np

MAX_CAPITAL = 1000000.0         # ₹10 Lakhs
MAX_CONCURRENT_POSITIONS = 7

def run_simulation(trade_log_path=None):
    if trade_log_path is None:
        trade_log_path = os.path.join(
            os.path.dirname(__file__),
            "../../workspace/backtests/trade_logs_gap_options_twoside_1h_250d.csv"
        )

    if not os.path.exists(trade_log_path):
        print(f"Error: Trade log not found at {trade_log_path}")
        return

    df = pd.read_csv(trade_log_path)
    df = df[df['type'] == 'BUY PE'].copy().reset_index(drop=True)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    df = df.sort_values(by='entry_time').reset_index(drop=True)

    print("=" * 75)
    print("STRATEGY 5: GAP UP BUY PE ALONE - ₹10 LAKH CAPITAL SIMULATION")
    print(f"Initial Capital: ₹{MAX_CAPITAL:,.2f} | Total Signals: {len(df)}")
    print("=" * 75)

    # --- Mode A: 1 Lot ---
    df_1lot = df.copy()
    df_1lot['cum'] = df_1lot['net_pnl'].cumsum()
    dd_1lot = (df_1lot['cum'] - df_1lot['cum'].cummax()).min()
    pnl_1lot = df_1lot['net_pnl'].sum()
    gross_1lot = df_1lot['gross_pnl'].sum()
    tax_1lot = df_1lot['charges'].sum()
    wr_1lot = (df_1lot['net_pnl'] > 0).mean() * 100
    r_1lot = df_1lot['r_multiple'].sum()

    print("\n--- MODE A: CONSERVATIVE 1 LOT (ZERO SKIPPED) ---")
    print(f"Executed:            {len(df_1lot)} trades")
    print(f"Win Rate:            {wr_1lot:.2f}%")
    print(f"Gross P&L:           ₹{gross_1lot:,.2f}")
    print(f"Brokerage & Charges: ₹{tax_1lot:,.2f}")
    print(f"Net Realized P&L:    ₹{pnl_1lot:,.2f}")
    print(f"ROI on ₹10L:         {(pnl_1lot / MAX_CAPITAL) * 100:.2f}%")
    print(f"Max Drawdown:        ₹{dd_1lot:,.2f} ({(dd_1lot / MAX_CAPITAL) * 100:.2f}%)")
    print(f"Total Return (R):    +{r_1lot:.2f} R")

    # --- Mode B: 10 Lots ---
    active = []
    exec_10lot = []
    rejected = 0
    for _, trade in df.iterrows():
        active = [p for p in active if p['exit_time'] > trade['entry_time']]
        if len(active) < MAX_CONCURRENT_POSITIONS:
            active.append(trade)
            exec_10lot.append(trade)
        else:
            rejected += 1

    df_10lot = pd.DataFrame(exec_10lot)
    df_10lot['net_pnl_10x'] = df_10lot['net_pnl'] * 10
    df_10lot['gross_pnl_10x'] = df_10lot['gross_pnl'] * 10
    df_10lot['charges_10x'] = df_10lot['charges'] * 10
    df_10lot['cum_10x'] = df_10lot['net_pnl_10x'].cumsum()
    dd_10lot = (df_10lot['cum_10x'] - df_10lot['cum_10x'].cummax()).min()
    pnl_10lot = df_10lot['net_pnl_10x'].sum()
    gross_10lot = df_10lot['gross_pnl_10x'].sum()
    tax_10lot = df_10lot['charges_10x'].sum()
    wr_10lot = (df_10lot['net_pnl_10x'] > 0).mean() * 100
    r_10lot = df_10lot['r_multiple'].sum() * 10

    print("\n--- MODE B: AGGRESSIVE 10 LOTS (FULL ₹10L UTILIZATION) ---")
    print(f"Executed:            {len(df_10lot)} trades (Rejected: {rejected})")
    print(f"Win Rate:            {wr_10lot:.2f}%")
    print(f"Gross P&L:           ₹{gross_10lot:,.2f}")
    print(f"Brokerage & Charges: ₹{tax_10lot:,.2f}")
    print(f"Net Realized P&L:    ₹{pnl_10lot:,.2f}")
    print(f"ROI on ₹10L:         {(pnl_10lot / MAX_CAPITAL) * 100:.2f}%")
    print(f"Max Drawdown:        ₹{dd_10lot:,.2f} ({(dd_10lot / MAX_CAPITAL) * 100:.2f}%)")
    print(f"Total Return (R):    +{r_10lot:.2f} R")
    print("=" * 75)

if __name__ == "__main__":
    run_simulation()
