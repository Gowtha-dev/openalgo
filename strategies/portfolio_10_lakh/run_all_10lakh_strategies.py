#!/usr/bin/env python3
"""
================================================================================
MASTER RUNNER: BENCHMARK ALL STRATEGIES ON ₹10,00,000 (10 LAKHS) CAPITAL
================================================================================
Executes and compares all strategies under the strict ₹10L capital ceiling.
"""

import os
import sys

# Add current folder to path
sys.path.insert(0, os.path.dirname(__file__))

import S_1_GapOpt_Sel_TwoSide
import S_2_GapOpt_Sel_CE_GapUp
import S_3_GapOpt_Buy_TwoSide_Aggr
import S_4_GapOpt_Buy_TwoSide_Cons
import S_5_GapOpt_Buy_PE_GapUp
import S_6_Nifty_Daily_Straddle
import S_7_Gap_Eq_MIS
import S_8_SRB1_Eq_1h

def main():
    print("\n" + "=" * 80)
    print("RUNNING ALL STRATEGIES UNDER ₹10,00,000 (10 LAKHS) CAPITAL CEILING")
    print("=" * 80 + "\n")

    S_1_GapOpt_Sel_TwoSide.run_simulation()
    print("\n")
    S_2_GapOpt_Sel_CE_GapUp.run_simulation()
    print("\n")
    S_3_GapOpt_Buy_TwoSide_Aggr.run_simulation()
    print("\n")
    S_4_GapOpt_Buy_TwoSide_Cons.run_simulation()
    print("\n")
    S_5_GapOpt_Buy_PE_GapUp.run_simulation()
    print("\n")
    S_6_Nifty_Daily_Straddle.run_simulation()
    print("\n")
    S_7_Gap_Eq_MIS.run_simulation()
    print("\n")
    S_8_SRB1_Eq_1h.run_simulation()

if __name__ == "__main__":
    main()
