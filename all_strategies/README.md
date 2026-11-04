# OpenAlgo Unified Strategy Bundle & 250-Day Audit Repository

This directory consolidates all 10 algorithmic trading strategies developed, backtested, and audited across **250 trading days (October 2025 – November 2026)**.

## 📁 Repository Structure

### 1. Performance Reports
- `yearly_returns_and_monthly_profit.txt`: Complete plain-text audit report featuring:
  - 250-Day / Yearly Return Leaderboard (Trades, Win Rate %, Net P&L, Profit Factor, Max Drawdown, Total R)
  - Month-by-month profit matrix across all strategies side-by-side
  - Detailed month-wise breakdown tables for each individual strategy
- `All_Strategies_Weekly_Monthly_250Days_Report.xlsx`: Comprehensive 14-tab Excel workbook containing:
  - `Executive_Summary`
  - `Monthly_Matrix`
  - `Weekly_Matrix`
  - `All_Trades_Master_Log` (All 6,551 trades chronologically with Excel AutoFilter)
  - 10 dedicated strategy sheets with trade audit tables

### 2. Live Automated Strategy Execution Scripts
- `S1_GapOpt_Sel_TwoSide.py`: Gap Option Selling Two-Sided ATM (NFO Stock Options)
- `S2_GapOpt_Sel_CE_GapUp.py`: Gap Option Selling CE on Gap Up (NFO Stock Options)
- `S3_GapOpt_Buy_TwoSide.py`: Gap Option Buying Two-Sided ATM (NFO Stock Options)
- `S4_GapOpt_Buy_PE_GapUp.py`: Gap Option Buying PE on Gap Up (NFO Stock Options)
- `S5_Nifty_Daily_Straddle.py`: Nifty 50 09:20 Daily Straddle Selling (Index Options)
- `S6_Gap_Equity_MIS.py`: Overnight Gap Mean Reversion Intraday MIS (NSE Equities)
- `S7_S8_EMA_Cross_Pullback.py`: 9/21/200 EMA + RSI(14) + Volume Pullback Engine (MIS & Swing)
- `S9_S10_Supertrend_50EMA.py`: Supertrend (10, 3) + 50 EMA Trend Filter Strategy
- `S11_SRB1_Equity_1h.py`: SRB1 1-Hour Equity Trend Breakout

### 3. Historical Backtesting Simulation Engines
- `backtest_nifty_daily_straddle.py`: Daily 09:20 Nifty Straddle 250-day backtester
- `backtest_gap_option_selling_1h_250d.py`: Gap option selling simulation engine
- `backtest_gap_options_twoside_1h_250d.py`: Gap option buying simulation engine
- `backtest_gap_options_1h_250d.py`: Gap option buying PE simulation engine
- `backtest_ema9_21_200_1h_250d.py`: 9/21/200 EMA Pullback 250-day engine
- `backtest_supertrend_50ema.py`: Supertrend 10,3 multi-timeframe simulation engine
- `backtest_gap_reversion_equity.py`: Gap equity mean-reversion multi-timeframe engine
- `backtest_SRB1.py`: SRB1 breakout engine
- `generate_all_strategies_excel_report.py`: Master audit compiler & Excel generator

## 🏆 Master Leaderboard Summary (250 Days)

| Rank | Strategy | Asset Class | Total Trades | Win Rate | Net P&L (₹) | Profit Factor |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: |
| **#1** | **S5: Nifty Daily Straddle (09:20)** | Index Options (Selling) | 247 | 60.7% | **+₹13,63,401.82** | 1.45 |
| **#2** | **S1: Gap Option Selling Two-Sided** | Stock Options (Selling) | 698 | 77.9% | **+₹8,08,023.92** | 4.33 |
| **#3** | **S3: Gap Option Buying Two-Sided** | Stock Options (Buying) | 698 | 67.8% | **+₹5,48,575.54** | 2.64 |
| **#4** | **S2: Gap Option Selling CE on Gap Up**| Stock Options (Selling) | 418 | 78.7% | **+₹4,68,893.68** | 4.15 |
| **#5** | **S8: 9/21/200 EMA Pullback Swing** | Nifty 50 Equities | 629 | 67.2% | **+₹1,43,224.10** | 2.06 |
| **#6** | **S7: 9/21/200 EMA Pullback MIS** | Nifty 50 Equities | 606 | 63.0% | **+₹1,26,321.92** | 3.69 |
| **#7** | **S6: Gap Equity Reversion MIS** | Nifty 50 Equities | 1,097 | 71.4% | **+₹24,891.90** | 3.88 |
| **#8** | **S10: Supertrend Pure Flip Exit** | Nifty 50 Equities | 929 | 30.5% | -₹1,50,626.94 | 0.74 |
| **#9** | **S9: Supertrend 2x ATR Trail** | Nifty 50 Equities | 949 | 28.3% | -₹1,93,282.20 | 0.54 |
| **#10**| **S4: Gap Option Buying PE on Gap Up** | Stock Options (Buying) | 280 | 23.6% | -₹4,70,149.22 | 0.11 |
| 📊 | **COMBINED PORTFOLIO** | **Multi-Asset** | **6,551** | **62.8%** | **+₹26,69,274.52** | **2.38** |
