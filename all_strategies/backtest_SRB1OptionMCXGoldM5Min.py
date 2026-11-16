"""Backtest of SRB1OptionMCXGoldM5Min over the last N days using OpenAlgo history.

Signals come from the near-month GOLDM future (5m). A trade buys the ATM option
(strike = future close rounded to 500) in the nearest expiry that has data, at the
signal candle close, and is managed bar by bar with the strategy's exit rules.
Costs, slippage and spreads are NOT modelled.
"""
import importlib.util
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta

import pandas as pd
from openalgo import api

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("gold", os.path.join(HERE, "SRB1OptionMCXGoldM5Min.py"))
gold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gold)

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
STRIKE_STEP = 500
RUPEES_PER_POINT = 10  # GOLDM lot 100 g, premium quoted per 10 g
MAX_CAPITAL = 40000    # skip any entry whose premium outlay exceeds this

client = api(api_key=os.environ["OPENALGO_API_KEY"],
             host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"))
end = datetime.now()
test_start = (end - timedelta(days=DAYS)).date()
warm_start = (end - timedelta(days=DAYS + 8)).strftime("%Y-%m-%d")


def hist(symbol):
    d = client.history(symbol=symbol, exchange="MCX", interval="5m",
                       start_date=warm_start, end_date=end.strftime("%Y-%m-%d"))
    if not isinstance(d, pd.DataFrame) or d.empty:
        return None
    d = d.sort_index()[["open", "high", "low", "close"]]
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)
    return d


# One continuous future series: Dec contract covers the whole window.
fut_sym = "GOLDM04DEC26FUT"
fut = hist(fut_sym)
print(f"future {fut_sym}: {len(fut)} bars {fut.index[0]} -> {fut.index[-1]}")

_opt_cache = {}


def option_series(day, side, strike):
    """Option 5m bars for the nearest expiry on/after `day` that returns data."""
    for k in range(0, 40):
        exp = (day + timedelta(days=k)).strftime("%d%b%y").upper()
        key = (exp, strike, side)
        if key not in _opt_cache:
            sym = f"GOLDM{exp}{strike}{side}"
            try:
                _opt_cache[key] = (sym, hist(sym))
            except Exception:
                _opt_cache[key] = (sym, None)
        sym, d = _opt_cache[key]
        if d is not None and len(d) and d.index[-1].date() >= day:
            return sym, d
    return None, None


def run(cfg, label):
    d = gold.add_signals(fut, cfg)
    trades = []
    for day, g in d.groupby(d.index.date):
        if day < test_start:
            continue
        n, r_loss, pos = 0, 0.0, None
        for ts, r in g.iterrows():
            hhmm = ts.strftime("%H:%M")
            close_t = (ts + timedelta(minutes=5)).strftime("%H:%M")
            if pos:
                o = pos["bars"]
                ob = o.loc[ts] if ts in o.index else None
                why, px = None, None
                if ob is not None and ob["low"] <= pos["opt_sl"]:
                    why, px = "option SL", pos["opt_sl"]
                elif pos["side"] == "CE" and r["low"] <= pos["stop"] or \
                        pos["side"] == "PE" and r["high"] >= pos["stop"]:
                    why = "future stop"
                else:
                    flipped = (not r["st_up"]) if pos["side"] == "CE" else bool(r["st_up"])
                    if flipped:
                        why = "supertrend flip"
                    elif close_t >= cfg.squareoff:
                        why = "squareoff"
                if why:
                    if px is None:
                        px = ob["close"] if ob is not None else pos["last"]
                    pts = px - pos["entry_prem"]
                    r_loss += pts / (pos["entry_prem"] * cfg.opt_sl_pct)
                    trades.append(dict(cfg=label, day=day, side=pos["side"], opt=pos["opt"],
                                       entry_time=pos["t"], exit_time=ts, entry=pos["entry_prem"],
                                       exit=px, points=pts, rupees=pts * gold.LOTS * RUPEES_PER_POINT,
                                       reason=why))
                    pos = None
                    continue
                if ob is not None:
                    pos["last"] = ob["close"]
                # trail like the live script
                if pos["side"] == "CE" and r["st_up"]:
                    pos["stop"] = max(pos["stop"], r["st"])
                if pos["side"] == "PE" and not r["st_up"]:
                    pos["stop"] = min(pos["stop"], r["st"])
                moved = (r["close"] - pos["entry"]) if pos["side"] == "CE" else (pos["entry"] - r["close"])
                if not pos["be"] and pos["risk"] > 0 and moved >= cfg.breakeven_r * pos["risk"]:
                    pos["be"] = True
                    pos["stop"] = (max(pos["stop"], pos["entry"]) if pos["side"] == "CE"
                                   else min(pos["stop"], pos["entry"]))
                continue
            if n >= cfg.max_trades_day or r_loss <= -cfg.max_daily_loss_r:
                continue
            side = "CE" if r["BUY_CE"] else "PE" if r["BUY_PE"] else None
            if not side or close_t >= cfg.squareoff:
                continue
            strike = int(round(r["close"] / STRIKE_STEP) * STRIKE_STEP)
            sym, ob_all = option_series(day, side, strike)
            if ob_all is None or ts not in ob_all.index:
                continue
            prem = float(ob_all.loc[ts, "close"])
            if prem <= 0 or prem * RUPEES_PER_POINT * gold.LOTS > MAX_CAPITAL:
                continue
            entry = float(r["close"])
            stop = (max(r["st"], entry - cfg.max_sl_atr * r["atr"]) if side == "CE"
                    else min(r["st"], entry + cfg.max_sl_atr * r["atr"]))
            pos = dict(side=side, opt=sym, bars=ob_all, entry_prem=prem, opt_sl=prem * (1 - cfg.opt_sl_pct),
                       entry=entry, stop=stop, risk=abs(entry - stop), be=False, t=ts, last=prem)
            n += 1
        if pos:  # no overnight: close at the last bar of the day
            lb = pos["last"]
            pts = lb - pos["entry_prem"]
            trades.append(dict(cfg=label, day=day, side=pos["side"], opt=pos["opt"], entry_time=pos["t"],
                               exit_time=g.index[-1], entry=pos["entry_prem"], exit=lb, points=pts,
                               rupees=pts * gold.LOTS * RUPEES_PER_POINT, reason="end of data"))
    return pd.DataFrame(trades)


base = gold.Cfg()
variants = {
    "full-session (23:00 sqoff)": base,
    "till 15:30": replace(base, entry_end="15:00", squareoff="15:30"),
}
out = []
for label, cfg in variants.items():
    t = run(cfg, label)
    out.append(t)
    print(f"\n=== {label} ===")
    if t.empty:
        print("no trades")
        continue
    print(t[["day", "side", "opt", "entry_time", "entry", "exit", "points", "reason"]].to_string(index=False))
    w = (t.points > 0).sum()
    print(f"trades {len(t)}  wins {w}  win% {100*w/len(t):.0f}  points {t.points.sum():.1f}  "
          f"approx Rs {t.rupees.sum():,.0f}")

res = pd.concat(out) if out else pd.DataFrame()
os.makedirs(os.path.join(HERE, "TestOutput"), exist_ok=True)
res.to_csv(os.path.join(HERE, "TestOutput", f"SRB1OptionMCXGoldM5Min_backtest_{DAYS}d.csv"), index=False)
