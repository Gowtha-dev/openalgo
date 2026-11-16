#!/usr/bin/env python3
"""
Backtest of SRB1OptionMCXGoldM5Min using genuine MCX GOLDM historical dataset
from /Users/gowtham/Documents/work/gold-data/GOLDM_BACKTEST/.

Period: 17 November 2025 to 13 November 2026 (256 trading sessions).
Underlying: MCX Gold Mini (GOLDM, 100g lot, quotation Rs per 10g, Rs 10 per point).
"""

import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import SRB1OptionMCXGoldM5Min as gold

DATA_DIR = os.getenv("GOLD_DATA_DIR", "/Users/gowtham/Documents/work/gold-data/GOLDM_BACKTEST")
FUTURES_CSV = os.path.join(DATA_DIR, "goldm_futures_daily.csv")
OPTIONS_CSV = os.path.join(DATA_DIR, "goldm_options_daily.csv")

STRIKE_STEP = 500
RUPEES_PER_POINT = 10  # 100g lot, Rs 10 per point
MAX_CAPITAL = 40000    # Rs 40,000 maximum capital per trade

print("=" * 80)
print("MCX GOLDM BACKTEST ENGINE — HISTORICAL DATASET")
print(f"Data Directory: {DATA_DIR}")
print("=" * 80)

if not os.path.exists(FUTURES_CSV) or not os.path.exists(OPTIONS_CSV):
    print(f"Error: Data files not found in {DATA_DIR}")
    sys.exit(1)

# 1. Load Futures Data & Build Continuous Near-Month Series
print("Loading MCX GOLDM Futures...")
fut_raw = pd.read_csv(FUTURES_CSV)
fut_raw["date"] = pd.to_datetime(fut_raw["date"])
fut_raw["expiry_date"] = pd.to_datetime(fut_raw["expiry_date"])

dates = sorted(fut_raw["date"].unique())
records = []
for d in dates:
    day_futs = fut_raw[(fut_raw["date"] == d) & (fut_raw["expiry_date"] >= d)].sort_values("expiry_date")
    if not day_futs.empty:
        c = day_futs.iloc[0]
        records.append({
            "date": d,
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": int(c["volume"]),
            "open_interest": int(c["open_interest"]),
            "expiry": c["expiry_date"]
        })

fut_df = pd.DataFrame(records).set_index("date").sort_index()
print(f"Continuous Near-Month Futures: {len(fut_df)} sessions ({fut_df.index[0].date()} to {fut_df.index[-1].date()})")

# 2. Load Options Data
print("Loading MCX GOLDM Options (268,904 rows)...")
opt_raw = pd.read_csv(OPTIONS_CSV)
opt_raw["date"] = pd.to_datetime(opt_raw["date"])
opt_raw["expiry_date"] = pd.to_datetime(opt_raw["expiry_date"])

# Index options by (expiry_date, strike, option_type)
opt_cache = {}
for (exp, strike, otype), g in opt_raw.groupby(["expiry_date", "strike", "option_type"]):
    opt_cache[(exp, strike, otype)] = g.set_index("date").sort_index()

print(f"Indexed {len(opt_cache)} unique option contract series.")


def get_option_series(day, side, strike, min_dte=1):
    """Returns nearest option expiry on/after day that has data."""
    expiries = sorted([exp for (exp, strk, otype) in opt_cache.keys() if strk == strike and otype == side and (exp - day).days >= min_dte])
    if not expiries:
        expiries = sorted([exp for (exp, strk, otype) in opt_cache.keys() if strk == strike and otype == side and exp >= day])
    if expiries:
        exp = expiries[0]
        sym = f"GOLDM{exp.strftime('%d%b%y').upper()}{strike}{side}"
        return sym, exp, opt_cache[(exp, strike, side)]
    return None, None, None


def run_backtest(cfg: gold.Cfg, label: str, use_opt_sl: bool = True, min_dte: int = 1) -> pd.DataFrame:
    d = gold.add_signals(fut_df, cfg)
    trades = []
    pos = None

    # Warmup of 25 bars for Supertrend/ATR/BB/RSI stabilization
    for i in range(25, len(d)):
        ts = d.index[i]
        r = d.iloc[i]
        day = ts.date()

        if pos:
            o = pos["bars"]
            ob = o.loc[ts] if ts in o.index else None
            why, px = None, None

            # 1. Option Expiry reached
            if ts >= pos["expiry"]:
                why = "option expiry"
                px = ob["close"] if ob is not None else pos["last"]
            # 2. Option Stop Loss
            elif use_opt_sl and pos["opt_sl"] is not None and ob is not None and ob["low"] <= pos["opt_sl"]:
                why = "option SL"
                px = pos["opt_sl"]
            # 3. Underlying Future Stop Loss
            elif (pos["side"] == "CE" and r["low"] <= pos["stop"]) or (pos["side"] == "PE" and r["high"] >= pos["stop"]):
                why = "future stop"
                px = ob["close"] if ob is not None else pos["last"]
            # 4. Supertrend Flip Exit
            else:
                flipped = (not r["st_up"]) if pos["side"] == "CE" else bool(r["st_up"])
                if flipped:
                    why = "supertrend flip"
                    px = ob["close"] if ob is not None else pos["last"]

            if why:
                if px is None:
                    px = ob["close"] if ob is not None else pos["last"]
                pts = px - pos["entry_prem"]
                trades.append(dict(
                    cfg=label,
                    day=pos["entry_date"],
                    side=pos["side"],
                    opt=pos["opt"],
                    entry_time=str(pos["entry_date"]),
                    exit_time=str(day),
                    entry=pos["entry_prem"],
                    exit=px,
                    points=round(pts, 2),
                    rupees=round(pts * gold.LOTS * RUPEES_PER_POINT, 2),
                    reason=why
                ))
                pos = None
                continue

            if ob is not None:
                pos["last"] = ob["close"]

            # Trail stop along Supertrend
            if pos["side"] == "CE" and r["st_up"]:
                pos["stop"] = max(pos["stop"], r["st"])
            if pos["side"] == "PE" and not r["st_up"]:
                pos["stop"] = min(pos["stop"], r["st"])

            # Breakeven trailing when gain >= breakeven_r * initial_risk
            moved = (r["close"] - pos["entry"]) if pos["side"] == "CE" else (pos["entry"] - r["close"])
            if not pos["be"] and pos["risk"] > 0 and moved >= cfg.breakeven_r * pos["risk"]:
                pos["be"] = True
                pos["stop"] = max(pos["stop"], pos["entry"]) if pos["side"] == "CE" else min(pos["stop"], pos["entry"])
            continue

        # Entry logic
        side = "CE" if r["BUY_CE"] else "PE" if r["BUY_PE"] else None
        if not side:
            continue

        strike = int(round(r["close"] / STRIKE_STEP) * STRIKE_STEP)
        sym, exp, ob_all = get_option_series(ts, side, strike, min_dte=min_dte)
        if ob_all is None or ts not in ob_all.index:
            continue

        prem = float(ob_all.loc[ts, "close"])
        if prem <= 0 or (prem * RUPEES_PER_POINT * gold.LOTS > MAX_CAPITAL):
            continue

        entry = float(r["close"])
        stop = (max(r["st"], entry - cfg.max_sl_atr * r["atr"]) if side == "CE"
                else min(r["st"], entry + cfg.max_sl_atr * r["atr"]))
        opt_sl = prem * (1.0 - cfg.opt_sl_pct) if use_opt_sl else None

        pos = dict(
            entry_date=day,
            side=side,
            opt=sym,
            expiry=exp,
            bars=ob_all,
            entry_prem=prem,
            opt_sl=opt_sl,
            entry=entry,
            stop=stop,
            risk=abs(entry - stop),
            be=False,
            last=prem
        )

    # Square off at end of data if still open
    if pos:
        lb = pos["last"]
        pts = lb - pos["entry_prem"]
        trades.append(dict(
            cfg=label,
            day=pos["entry_date"],
            side=pos["side"],
            opt=pos["opt"],
            entry_time=str(pos["entry_date"]),
            exit_time=str(fut_df.index[-1].date()),
            entry=pos["entry_prem"],
            exit=lb,
            points=round(pts, 2),
            rupees=round(pts * gold.LOTS * RUPEES_PER_POINT, 2),
            reason="end of data"
        ))

    return pd.DataFrame(trades)


# Run configurations
configs = [
    ("Baseline (30% Option SL, Nearest Expiry)", gold.Cfg(opt_sl_pct=0.30), True, 1),
    ("Conservative (50% Option SL, Min 5 DTE)", gold.Cfg(opt_sl_pct=0.50), True, 5),
    ("Trend-Follower (Future Stop & Supertrend Trail, Min 5 DTE)", gold.Cfg(), False, 5),
    ("Trend-Follower (Future Stop & Supertrend Trail, Min 10 DTE)", gold.Cfg(), False, 10),
]

all_trades = []
print("\n" + "=" * 90)
print("PERFORMANCE AUDIT ACROSS ALL CONFIGURATION VARIANTS")
print("=" * 90)

for label, cfg, use_opt_sl, min_dte in configs:
    t = run_backtest(cfg, label, use_opt_sl=use_opt_sl, min_dte=min_dte)
    all_trades.append(t)
    print(f"\n--- {label} ---")
    if t.empty:
        print("No trades generated.")
        continue

    cols = ["day", "side", "opt", "entry_time", "exit_time", "entry", "exit", "points", "rupees", "reason"]
    print(t[cols].to_string(index=False))

    w = (t["points"] > 0).sum()
    l = (t["points"] <= 0).sum()
    win_rate = 100.0 * w / len(t) if len(t) > 0.0 else 0.0
    tot_pts = t["points"].sum()
    tot_rs = t["rupees"].sum()
    gross_profit = t[t["rupees"] > 0]["rupees"].sum()
    gross_loss = abs(t[t["rupees"] < 0]["rupees"].sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    print("-" * 90)
    print(f"Trades: {len(t)} | Wins: {w} | Losses: {l} | Win Rate: {win_rate:.1f}%")
    print(f"Total Points: {tot_pts:+.2f} | Net Realized P&L: ₹{tot_rs:+,.2f} | Profit Factor: {pf:.2f}")

# Save results
out_dir = os.path.join(HERE, "TestOutput")
os.makedirs(out_dir, exist_ok=True)
out_csv = os.path.join(out_dir, "SRB1OptionMCXGoldM5Min_backtest_gold_data.csv")
res_df = pd.concat([t for t in all_trades if not t.empty], ignore_index=True) if all_trades else pd.DataFrame()
res_df.to_csv(out_csv, index=False)
print("\n" + "=" * 90)
print(f"All backtest results saved successfully to: {out_csv}")
print("=" * 90)
