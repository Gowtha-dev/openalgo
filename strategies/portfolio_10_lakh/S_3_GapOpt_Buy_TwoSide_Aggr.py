#!/usr/bin/env python3
"""
================================================================================
STRATEGY 3: GAP REVERSION OPTION BUYING — TWO-SIDED (AGGRESSIVE 10 LOTS)
PORTFOLIO CAPITAL: ₹10,00,000 (10 LAKHS MAXIMUM DEPLOYMENT)
================================================================================

CORE LOGIC:
-----------
1. Gap Down Reversal (Bullish Setup):
   - Stock opens gap down 0.5% - 2.0% on Nifty 50 stocks.
   - Price breaks above first 1-Hour candle high and holds above VWAP.
   - Action: BUY 10 Lots At-The-Money (ATM) Call Option (CE).
   - Stop Loss: 30% drop in option premium OR Spot breaks opening low.
   - Target: Spot fills overnight gap OR square-off at 15:15.

2. Gap Up Reversal (Bearish Setup):
   - Stock opens gap up 0.5% - 2.0% on Nifty 50 stocks.
   - Price breaks below first 1-Hour candle low and stays below VWAP.
   - Action: BUY 10 Lots At-The-Money (ATM) Put Option (PE).
   - Stop Loss: 30% drop in option premium OR Spot breaks opening high.
   - Target: Spot fills overnight gap OR square-off at 15:15.

CAPITAL SIZING ON ₹10,00,000 (MAXIMUM CAPITAL UTILIZATION):
----------------------------------------------------------
- Premium per Lot: ~₹14,000.
- Sizing per Trade: 10 Lots (~₹1,40,000 premium invested per signal).
- Max Concurrent Positions: 7 Positions (7 * ₹1,40,000 = ₹9,80,000 deployed).
- Cash Buffer: ₹20,000 unallocated cash for safety and drawdown absorption.
- Position Cap: If 7 positions are currently open, any 8th signal is rejected.

================================================================================
VERIFIED BACKTEST RESULTS (250 TRADING DAYS ON NIFTY 50 STOCKS):
================================================================================
Total Signals Triggered:          698 signals
Trades Executed:                  682 trades (97.7% execution)
Trades Rejected (Capacity Cap):   16 trades (only 2.3% of signals)
Winning Trades:                   461 trades
Losing Trades:                    221 trades
Net Win Rate:                     67.60%

Financial Performance:
----------------------
Starting Capital:                 ₹10,00,000.00
Gross P&L:                        +₹5,840,284.40
Brokerage & Taxes (STT/GST/etc):  ₹541,419.00
Net Realized P&L:                 +₹5,298,865.40
Ending Account Capital:           ₹62,98,865.40
Net ROI on Capital:               +529.89%

Risk & Drawdown Metrics:
------------------------
Maximum Peak-to-Trough Drawdown:  -₹335,428.50
Max Drawdown % on ₹10L Capital:   -33.54%
Total Return in R-Multiple:       +1380.30 R
Average R per Trade:              +2.02 R
Profit Factor:                    2.98
Calmar Ratio (Return / Max DD):   15.80x
Theta (Time Decay) Impact:        NEGATIVE (Overcome by rapid 1-2h gap fills)
================================================================================
"""

import os
import sys
import pandas as pd
import numpy as np

MAX_CAPITAL = 1000000.0         # ₹10 Lakhs
LOT_MULTIPLIER = 10             # 10 lots per trade
MAX_CONCURRENT_POSITIONS = 7    # 7 slots * ~140k = ~980k <= 10L

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
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    df = df.sort_values(by='entry_time').reset_index(drop=True)

    print("=" * 75)
    print("STRATEGY 3: GAP OPTION BUYING (AGGRESSIVE 10 LOTS) - ₹10 LAKH CAPITAL")
    print(f"Initial Capital: ₹{MAX_CAPITAL:,.2f} | Sizing: {LOT_MULTIPLIER} Lots/trade | Max Positions: {MAX_CONCURRENT_POSITIONS}")
    print("=" * 75)

    active_positions = []
    executed_trades = []
    rejected_count = 0

    for _, trade in df.iterrows():
        active_positions = [p for p in active_positions if p['exit_time'] > trade['entry_time']]

        if len(active_positions) < MAX_CONCURRENT_POSITIONS:
            active_positions.append(trade)
            executed_trades.append(trade)
        else:
            rejected_count += 1

    res_df = pd.DataFrame(executed_trades)
    res_df['net_pnl_scaled'] = res_df['net_pnl'] * LOT_MULTIPLIER
    res_df['gross_pnl_scaled'] = res_df['gross_pnl'] * LOT_MULTIPLIER
    res_df['charges_scaled'] = res_df['charges'] * LOT_MULTIPLIER
    res_df['r_multiple_scaled'] = res_df['r_multiple'] * LOT_MULTIPLIER

    res_df['cum_pnl'] = res_df['net_pnl_scaled'].cumsum()
    res_df['peak'] = res_df['cum_pnl'].cummax()
    res_df['drawdown'] = res_df['cum_pnl'] - res_df['peak']

    wins = res_df[res_df['net_pnl_scaled'] > 0]
    losses = res_df[res_df['net_pnl_scaled'] <= 0]
    total_trades = len(res_df)
    win_rate = len(wins) / total_trades * 100
    net_pnl = res_df['net_pnl_scaled'].sum()
    gross_pnl = res_df['gross_pnl_scaled'].sum()
    charges = res_df['charges_scaled'].sum()
    max_dd = res_df['drawdown'].min()
    max_dd_pct = (max_dd / MAX_CAPITAL) * 100
    roi = (net_pnl / MAX_CAPITAL) * 100
    total_r = res_df['r_multiple_scaled'].sum()
    pf = wins['gross_pnl_scaled'].sum() / abs(losses['gross_pnl_scaled'].sum()) if len(losses) > 0 else np.nan

    print(f"Total Signals:          {len(df)}")
    print(f"Executed Trades:        {total_trades}")
    print(f"Rejected (Capacity):    {rejected_count}")
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
