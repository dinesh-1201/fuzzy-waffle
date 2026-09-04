from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ORBConfig:
    opening_bars: int = 3
    confirmation_closes: int = 4
    max_gap_pct: float | None = None
    stop_pct: float = 0.60
    target_r: float = 3.0
    entry_start: str = "09:30"
    last_entry: str = "11:00"
    exit_time: str = "15:25"
    worst_case_ambiguous_bar: bool = True


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "datetime": "Datetime",
        "date": "Date",
        "time": "Time",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
    }
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    rename = {}
    for c in out.columns:
        key = c.lower()
        if key in aliases:
            rename[c] = aliases[key]
    out = out.rename(columns=rename)
    required = {"Datetime", "Open", "High", "Low", "Close"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    return out


def prepare_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """Validate/enrich regular-session NIFTY 5-minute data."""
    out = _normalize_columns(df)
    if "Datetime" in out.columns:
        out["DateTime"] = pd.to_datetime(out["Datetime"], errors="coerce")
    else:
        out["DateTime"] = pd.to_datetime(
            out["Date"].astype(str) + " " + out["Time"].astype(str),
            errors="coerce",
        )
    out = out.dropna(subset=["DateTime"]).sort_values("DateTime")
    out = out.set_index("DateTime")
    out = out.between_time("09:15", "15:25").copy()
    out["SessionDate"] = out.index.date
    sizes = out.groupby("SessionDate", sort=True).size()
    complete = sizes[sizes == 75].index
    out = out[out["SessionDate"].isin(complete)].copy()

    first = out.groupby("SessionDate")["Open"].first()
    prev_close = out.groupby("SessionDate")["Close"].last().shift(1)
    out["DayOpen"] = out["SessionDate"].map(first)
    out["PrevClose"] = out["SessionDate"].map(prev_close)
    out["GapPct"] = (out["DayOpen"] - out["PrevClose"]) / out["PrevClose"] * 100.0
    return out


def _find_entry(day: pd.DataFrame, cfg: ORBConfig) -> tuple[int, int, float] | None:
    """Return (row index, direction, entry price) using only completed confirmation candles."""
    or_high = float(day["High"].iloc[: cfg.opening_bars].max())
    or_low = float(day["Low"].iloc[: cfg.opening_bars].min())
    up_count = down_count = 0
    start = pd.Timestamp(cfg.entry_start).time()
    last = pd.Timestamp(cfg.last_entry).time()

    for i in range(cfg.opening_bars, len(day)):
        tm = day.index[i].time()
        if tm < start:
            continue
        if tm > last:
            break
        close = float(day["Close"].iloc[i])
        if close > or_high:
            up_count += 1
            down_count = 0
        elif close < or_low:
            down_count += 1
            up_count = 0
        else:
            up_count = down_count = 0
        if up_count >= cfg.confirmation_closes:
            return i, 1, close
        if down_count >= cfg.confirmation_closes:
            return i, -1, close
    return None


def backtest(df: pd.DataFrame, cfg: ORBConfig = ORBConfig()) -> pd.DataFrame:
    """One-trade-per-session ORB.

    Entry is at the confirmation candle close. Stop/target are evaluated only on
    subsequent candles. When both are touched in one candle, worst-case SL first
    is used by default because OHLC data cannot resolve intrabar ordering.
    """
    data = prepare_sessions(df)
    trades: list[dict] = []

    for session_date, day in data.groupby("SessionDate", sort=True):
        gap = float(day["GapPct"].iloc[0])
        if pd.isna(gap):
            continue
        if cfg.max_gap_pct is not None and abs(gap) >= cfg.max_gap_pct:
            continue
        found = _find_entry(day, cfg)
        if found is None:
            continue
        entry_idx, direction, entry = found
        risk = entry * cfg.stop_pct / 100.0
        stop = entry - direction * risk
        target = entry + direction * risk * cfg.target_r

        exit_idx = len(day) - 1
        exit_price = float(day["Close"].iloc[-1])
        reason = "EOD"
        for i in range(entry_idx + 1, len(day)):
            hi = float(day["High"].iloc[i])
            lo = float(day["Low"].iloc[i])
            hit_stop = lo <= stop if direction == 1 else hi >= stop
            hit_target = hi >= target if direction == 1 else lo <= target
            if hit_stop and hit_target:
                exit_idx = i
                exit_price = stop if cfg.worst_case_ambiguous_bar else target
                reason = "SL_AMBIGUOUS" if cfg.worst_case_ambiguous_bar else "TP_AMBIGUOUS"
                break
            if hit_stop:
                exit_idx, exit_price, reason = i, stop, "SL"
                break
            if hit_target:
                exit_idx, exit_price, reason = i, target, "TP"
                break

        r_multiple = direction * (exit_price - entry) / risk
        trades.append(
            {
                "SessionDate": session_date,
                "EntryTime": day.index[entry_idx],
                "ExitTime": day.index[exit_idx],
                "Direction": direction,
                "GapPct": gap,
                "Entry": entry,
                "Exit": exit_price,
                "Stop": stop,
                "Target": target,
                "ExitReason": reason,
                "R": r_multiple,
            }
        )
    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {"trades": 0, "win_rate": np.nan, "profit_factor": np.nan, "avg_R": np.nan, "max_drawdown_R": np.nan, "total_R": 0.0}
    r = trades["R"].astype(float)
    equity = r.cumsum()
    dd = equity - equity.cummax()
    gains = r[r > 0].sum()
    losses = -r[r < 0].sum()
    return {
        "trades": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "profit_factor": float(gains / losses) if losses else np.inf,
        "avg_R": float(r.mean()),
        "max_drawdown_R": float(dd.min()),
        "total_R": float(r.sum()),
    }


if __name__ == "__main__":
    raise SystemExit("Import backtest() and provide the local NIFTY OHLC dataset.")
