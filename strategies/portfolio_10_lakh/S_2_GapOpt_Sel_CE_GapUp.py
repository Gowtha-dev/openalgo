#!/usr/bin/env python3
"""
================================================================================
STRATEGY 2: GAP UP REVERSAL — STOCK CALL OPTION SELLING (SELL CE ALONE)
PORTFOLIO CAPITAL: ₹10,00,000 (10 LAKHS STRICT CEILING)
================================================================================

CORE LOGIC:
-----------
- Applies purely to GAP UP BEARISH REVERSALS on Nifty 50 stocks.
- Stock opens gap up 0.5% - 2.0% above previous day's close.
- Price breaks below first 1-Hour candle low and stays below VWAP.
- Action: SELL 1 Lot At-The-Money (ATM) Call Option (CE).
- Stop Loss: 30% increase in CE premium OR Spot breaks opening high.
- Target: Spot fills overnight gap OR square-off at 15:15.

CAPITAL SIZING ON ₹10,00,000:
----------------------------
- Margin per Lot: ~₹1,20,000 (SEBI SPAN + Exposure Margin).
- Max Concurrent Positions Allowed: Exactly 8 Lots (₹9.6L deployed).
- Cash Buffer: ₹40,000 for M2M safety.
- Margin Rule: Max 8 active positions. Any concurrent signal beyond 8 is skipped.

================================================================================
VERIFIED BACKTEST RESULTS (250 TRADING DAYS ON NIFTY 50 STOCKS):
================================================================================
Total Signals Triggered:          418 signals
Trades Executed:                  413 trades (98.8% execution)
Trades Rejected (Margin Ceiling): 5 trades (only 1.2% of signals)
Winning Trades:                   325 trades
Losing Trades:                    88 trades
Net Win Rate:                     78.69%

Financial Performance:
----------------------
Starting Capital:                 ₹10,00,000.00
Gross P&L:                        +₹498,655.07
Brokerage & Taxes (STT/GST/etc):  ₹31,176.66
Net Realized P&L:                 +₹467,478.41
Ending Account Capital:           ₹14,67,478.41
Net ROI on Capital:               +46.75%

Risk & Drawdown Metrics:
------------------------
Maximum Peak-to-Trough Drawdown:  -₹13,222.70
Max Drawdown % on ₹10L Capital:   -1.32%
Total Return in R-Multiple:       +125.46 R
Average R per Trade:              +0.30 R
Profit Factor:                    4.54
Calmar Ratio (Return / Max DD):   35.35x
Theta (Time Decay) Advantage:     POSITIVE (Decays into profit automatically)
================================================================================
"""

import os
import sys
import pandas as pd
import numpy as np

MAX_CAPITAL = 1000000.0         # ₹10 Lakhs
MARGIN_PER_LOT = 120000.0       # Average SEBI margin per stock F&O lot
MAX_CONCURRENT_LOTS = int(MAX_CAPITAL // MARGIN_PER_LOT)  # Exactly 8 lots

def run_simulation(trade_log_path=None):
    if trade_log_path is None:
        trade_log_path = os.path.join(
            os.path.dirname(__file__),
            "../../workspace/backtests/trade_logs_gap_option_selling_1h_250d.csv"
        )

    if not os.path.exists(trade_log_path):
        print(f"Error: Trade log not found at {trade_log_path}")
        return

    df = pd.read_csv(trade_log_path)
    df = df[df['type'] == 'SELL CE'].copy().reset_index(drop=True)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    df = df.sort_values(by='entry_time').reset_index(drop=True)

    print("=" * 75)
    print("STRATEGY 2: GAP UP SELL CE ALONE - ₹10 LAKH CAPITAL SIMULATION")
    print(f"Initial Capital: ₹{MAX_CAPITAL:,.2f} | Max Concurrent Lots: {MAX_CONCURRENT_LOTS}")
    print("=" * 75)

    active_positions = []
    executed_trades = []
    rejected_count = 0

    for _, trade in df.iterrows():
        active_positions = [p for p in active_positions if p['exit_time'] > trade['entry_time']]

        if len(active_positions) < MAX_CONCURRENT_LOTS:
            active_positions.append(trade)
            executed_trades.append(trade)
        else:
            rejected_count += 1

    res_df = pd.DataFrame(executed_trades)
    res_df['cum_pnl'] = res_df['net_pnl'].cumsum()
    res_df['peak'] = res_df['cum_pnl'].cummax()
    res_df['drawdown'] = res_df['cum_pnl'] - res_df['peak']

    wins = res_df[res_df['net_pnl'] > 0]
    losses = res_df[res_df['net_pnl'] <= 0]
    total_trades = len(res_df)
    win_rate = len(wins) / total_trades * 100
    net_pnl = res_df['net_pnl'].sum()
    gross_pnl = res_df['gross_pnl'].sum()
    charges = res_df['charges'].sum()
    max_dd = res_df['drawdown'].min()
    max_dd_pct = (max_dd / MAX_CAPITAL) * 100
    roi = (net_pnl / MAX_CAPITAL) * 100
    total_r = res_df['r_multiple'].sum()
    pf = wins['gross_pnl'].sum() / abs(losses['gross_pnl'].sum()) if len(losses) > 0 else np.nan

    print(f"Total Signals:          {len(df)}")
    print(f"Executed Trades:        {total_trades}")
    print(f"Rejected (Margin Cap):  {rejected_count}")
    print(f"Win Rate:               {win_rate:.2f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"Gross P&L:              ₹{gross_pnl:,.2f}")
    print(f"Brokerage & Charges:    ₹{charges:,.2f}")
    print(f"Net Realized P&L:       ₹{net_pnl:,.2f}")
    print(f"Ending Capital:         ₹{(MAX_CAPITAL + net_pnl):,.2f}")
    print(f"ROI on ₹10L:            {roi:.2f}%")
    print(f"Max Drawdown:           ₹{max_dd:,.2f} ({max_dd_pct:.2f}%)")
    print(f"Total Return (R):       +{total_r:.2f} R")
    print(f"Profit Factor:          {pf:.2f}")
    print("=" * 75)

    return res_df

if __name__ == "__main__":
    run_simulation()
