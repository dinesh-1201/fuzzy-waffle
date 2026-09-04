from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ORBConfig:
    opening_bars: int = 3
    confirmation_closes: int = 2
    max_gap_pct: float | None = 0.50
    stop_pct: float = 0.60
    target_r: float = 2.0
    entry_start: str = "09:35"
    last_entry: str = "11:00"
    exit_time: str = "15:25"


def prepare_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and enrich 5-minute NIFTY OHLC data without look-ahead."""
    required = {"Date", "Time", "Open", "High", "Low", "Close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    out = df.copy()
    out["DateTime"] = pd.to_datetime(
        out["Date"].astype(str) + " " + out["Time"].astype(str),
        errors="coerce",
    )
    out = out.dropna(subset=["DateTime"]).sort_values("DateTime")
    out = out.set_index("DateTime")

    out = out.between_time("09:15", "15:25").copy()
    out["SessionDate"] = out.index.date

    sessions = out.groupby("SessionDate", sort=True)
    sizes = sessions.size()
    complete = sizes[sizes == 75].index
    out = out[out["SessionDate"].isin(complete)].copy()

    first = out.groupby("SessionDate")["Open"].first()
    prev_close = out.groupby("SessionDate")["Close"].last().shift(1)
    out["DayOpen"] = out["SessionDate"].map(first)
    out["PrevClose"] = out["SessionDate"].map(prev_close)
    out["GapPct"] = (out["DayOpen"] - out["PrevClose"]) / out["PrevClose"] * 100.0
    return out


def _entry_side(day: pd.DataFrame, cfg: ORBConfig) -> tuple[int, float] | None:
    """Return (direction, entry_price) or None. Direction is +1 long, -1 short."""
    or_high = day["High"].iloc[: cfg.opening_bars].max()
    or_low = day["Low"].iloc[: cfg.opening_bars].min()
    post = day.iloc[cfg.opening_bars:]
    post = post.between_time(cfg.entry_start, cfg.last_entry)

    up_count = 0
    down_count = 0
    for _, row in post.iterrows():
        if row["Close"] > or_high:
            up_count += 1
            down_count = 0
        elif row["Close"] < or_low:
            down_count += 1
            up_count = 0
        else:
            up_count = 0
            down_count = 0

        if up_count >= cfg.confirmation_closes:
            return 1, float(row["Close"])
        if down_count >= cfg.confirmation_closes:
            return -1, float(row["Close"])
    return None


def backtest(df: pd.DataFrame, cfg: ORBConfig) -> pd.DataFrame:
    """Backtest one-trade-per-day ORB with OHLC execution assumptions.

    Entry occurs at the close of the confirmation candle. Within each subsequent
    candle, stop is assumed to trigger before target when both are touched.
    Remaining position is exited at 15:25 close. Returns are measured in R.
    """
    df = prepare_sessions(df)
    trades: list[dict] = []

    for session_date, day in df.groupby("SessionDate", sort=True):
        gap = float(day["GapPct"].iloc[0])
        if cfg.max_gap_pct is not None and abs(gap) >= cfg.max_gap_pct:
            continue

        side_entry = _entry_side(day, cfg)
        if side_entry is None:
            continue

        direction, entry = side_entry
        risk = entry * cfg.stop_pct / 100.0
        stop = entry - direction * risk
        target = entry + direction * risk * cfg.target_r

        # Find first post-entry exit. Entry is at a bar close, so only later bars count.
        ts = day.index
        entry_idx = next(i for i, t in enumerate(ts) if day.iloc[i]["Close"] == entry and t.time().strftime("%H:%M") >= cfg.entry_start)
        exit_price = float(day.iloc[-1]["Close"])
        exit_reason = "EOD"
        exit_ts = day.index[-1]

        for i in range(entry_idx + 1, len(day)):
            row = day.iloc[i]
            hit_stop = row["Low"] <= stop if direction == 1 else row["High"] >= stop
            hit_target = row["High"] >= target if direction == 1 else row["Low"] <= target
            if hit_stop:
                exit_price = stop
                exit_reason = "SL"
                exit_ts = day.index[i]
                break
            if hit_target:
                exit_price = target
                exit_reason = "TP"
                exit_ts = day.index[i]
                break

        r = direction * (exit_price - entry) / risk
        trades.append(
            {
                "SessionDate": session_date,
                "EntryTime": day.index[entry_idx],
                "ExitTime": exit_ts,
                "Direction": direction,
                "GapPct": gap,
                "Entry": entry,
                "Exit": exit_price,
                "Stop": stop,
                "Target": target,
                "ExitReason": exit_reason,
                "R": r,
            }
        )

    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0, "win_rate": np.nan, "profit_factor": np.nan, "avg_R": np.nan, "max_drawdown_R": np.nan}
    r = trades["R"].astype(float)
    equity = r.cumsum()
    dd = equity - equity.cummax()
    gross_profit = r[r > 0].sum()
    gross_loss = -r[r < 0].sum()
    return {
        "trades": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss else np.inf,
        "avg_R": float(r.mean()),
        "max_drawdown_R": float(dd.min()),
        "total_R": float(r.sum()),
    }


if __name__ == "__main__":
    raise SystemExit("Import the module and supply the local NIFTY OHLC dataset.")
