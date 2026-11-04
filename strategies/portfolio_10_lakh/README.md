# ₹10 Lakh Portfolio Strategies (OpenAlgo)

This directory contains standalone Python strategies specifically engineered, sized, and backtested under a strict **₹10,00,000 (10 Lakhs / 10 Lac)** capital ceiling.

All files follow the concise naming standard:
* **`S_`**: Strategy prefix
* **`GapOpt`**: Gap Reversion Option
* **`Sel`**: Option Selling
* **`Buy`**: Option Buying

Each script has the complete logic, sizing parameters, and **full verified backtest results embedded as comments at the top of the file**.

---

## Strategy Catalog & Performance Summary (₹10 Lakh Capital)

| Short Script Name | Type & Description | Max Positions / Sizing | Trades Executed | Win Rate | Max Drawdown | Net Realized P&L | ROI on ₹10L |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| [`S_1_GapOpt_Sel_TwoSide.py`](file:///Users/gowtham/Documents/work/openalgo/openalgo/strategies/portfolio_10_lakh/S_1_GapOpt_Sel_TwoSide.py) | Two-Sided Gap Reversion Option Selling (Sell CE/PE) | Max 8 Concurrent Lots (Margin: ₹1.2L/lot) | **691** (7 skipped) | **78.00%** | **-₹17,973** (-1.80%) | **+₹7,90,850.30** | **+79.09%** |
| [`S_2_GapOpt_Sel_CE_GapUp.py`](file:///Users/gowtham/Documents/work/openalgo/openalgo/strategies/portfolio_10_lakh/S_2_GapOpt_Sel_CE_GapUp.py) | Gap Up Bearish Reversal Option Selling (Sell CE alone) | Max 8 Concurrent Lots (Margin: ₹1.2L/lot) | **413** (5 skipped) | **78.69%** | **-₹13,223** (-1.32%) | **+₹4,67,478.41** | **+46.75%** |
| [`S_3_GapOpt_Buy_TwoSide_Aggr.py`](file:///Users/gowtham/Documents/work/openalgo/openalgo/strategies/portfolio_10_lakh/S_3_GapOpt_Buy_TwoSide_Aggr.py)| Two-Sided Gap Option Buying (Full 10L Deployment) | 10 Lots/Trade, Max 7 Concurrent Positions | **682** (16 skipped)| **67.60%** | **-₹335,429** (-33.54%)| **+₹52,98,865.40**| **+529.89%** |
| [`S_4_GapOpt_Buy_TwoSide_Cons.py`](file:///Users/gowtham/Documents/work/openalgo/openalgo/strategies/portfolio_10_lakh/S_4_GapOpt_Buy_TwoSide_Cons.py)| Two-Sided Gap Option Buying (Ultra-Safe Buffer) | Strictly 1 Lot/Trade, Zero Rejections | **698** (0 skipped) | **67.77%** | **-₹33,543** (-3.35%) | **+₹5,48,575.54** | **+54.86%** |
| [`S_5_GapOpt_Buy_PE_GapUp.py`](file:///Users/gowtham/Documents/work/openalgo/openalgo/strategies/portfolio_10_lakh/S_5_GapOpt_Buy_PE_GapUp.py) | Gap Up Bearish Reversal Option Buying (Buy PE alone) | Mode A: 1 Lot Safe \| Mode B: 10 Lots Full | **418** / **408** | **67.22%** / **66.67%** | **-₹23,317** / **-₹233,174** | **+₹3,21,011** / **+₹29,22,028** | **+32.10%** / **+292.20%** |
| [`S_6_Nifty_Daily_Straddle.py`](file:///Users/gowtham/Documents/work/openalgo/openalgo/strategies/portfolio_10_lakh/S_6_Nifty_Daily_Straddle.py) | Daily 9:20 AM Nifty 50 Index ATM Straddle | 7 Lot Pairs (350 CE + 350 PE, Margin ₹9.8L) | **247 days** | **60.73%** | **-₹269,375** (-26.94%)| **+₹9,54,381.27** | **+95.44%** |
| [`S_7_Gap_Eq_MIS.py`](file:///Users/gowtham/Documents/work/openalgo/openalgo/strategies/portfolio_10_lakh/S_7_Gap_Eq_MIS.py) | Intraday Equity Mean Reversion (5x Leverage) | 10 Concurrent Slots (₹50L buying power) | **1,097** | **71.38%** | **-₹20,321** (-2.03%) | **+₹1,73,471.50** | **+17.35%** |
| [`S_8_SRB1_Eq_1h.py`](file:///Users/gowtham/Documents/work/openalgo/openalgo/strategies/portfolio_10_lakh/S_8_SRB1_Eq_1h.py) | SRB1 1-Hour Breakout Momentum (CNC Delivery) | 7 Concurrent Stocks (~₹1.43L allocation) | **72** | **50.00%** | **-₹3,273** (-0.33%) | **+₹4,823.64** (30d) | **+0.48% / mo** |

---

## How to Run

### Run Any Strategy Individually:
```bash
uv run python openalgo/strategies/portfolio_10_lakh/S_1_GapOpt_Sel_TwoSide.py
uv run python openalgo/strategies/portfolio_10_lakh/S_3_GapOpt_Buy_TwoSide_Aggr.py
```

### Run the Master Benchmark Suite:
```bash
uv run python openalgo/strategies/portfolio_10_lakh/run_all_10lakh_strategies.py
```
