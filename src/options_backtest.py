"""NIFTY option backtest helpers.

The underlying NIFTY signal is kept separate from the option trade.  This module
only uses option quotes that were actually available at or after the signal
execution time.

Important rules:
- Contract must be alive on the signal date.
- Contract must have a quote close to the execution time.
- Strict mode enters on the first option quote at/after execution time.
- Legacy mode can use the latest quote at/before execution time for comparison.
- No future quote is allowed to choose the contract itself.
- OHLC-only stop/target checks use the conservative stop-first rule when both
  levels are touched in one bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OptionBacktestConfig:
    option_type: str = "CE"
    strike_offset: int = 0
    expiry_rank: int = 0
    premium_stop_pct: Optional[float] = None
    premium_target_pct: Optional[float] = None
    max_hold_minutes: Optional[int] = None
    exit_at_signal_exit: bool = True
    lot_size: int = 1
    round_trip_slippage_pct: float = 0.0
    quote_mode: str = "strict"  # strict=first quote at/after time; legacy=latest at/before
    max_entry_staleness_minutes: int = 2
    max_exit_staleness_minutes: int = 5


def normalize_option_columns(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "datetime": "Datetime", "date": "Date", "trade_dt": "Date",
        "trade_date": "Date", "trade time": "Time", "trade_time": "Time",
        "open": "Open", "high": "High", "low": "Low", "close": "Close",
        "ltp": "Close", "volume": "Volume", "strike": "Strike",
        "strike price": "Strike", "expiry": "Expiry", "expiry date": "Expiry",
        "option type": "OptionType", "opt type": "OptionType",
        "instrument": "Instrument", "symbol": "Symbol", "bid": "Bid",
        "ask": "Ask", "iv": "IV", "open interest": "OI", "oi": "OI",
    }
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    rename = {c: aliases[c.lower().strip()] for c in out.columns if c.lower().strip() in aliases}
    out = out.rename(columns=rename)
    if "Datetime" not in out.columns:
        if {"Date", "Time"}.issubset(out.columns):
            out["Datetime"] = pd.to_datetime(out["Date"].astype(str) + " " + out["Time"].astype(str), errors="coerce")
        elif "Date" in out.columns:
            out["Datetime"] = pd.to_datetime(out["Date"], errors="coerce")
    if "Datetime" not in out.columns:
        raise ValueError("Option data needs Datetime, or Date + Time columns.")
    out["Datetime"] = pd.to_datetime(out["Datetime"], errors="coerce")
    out = out.dropna(subset=["Datetime"]).copy()
    for col in ["Open", "High", "Low", "Close", "Strike", "Bid", "Ask", "IV", "OI", "Volume"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "OptionType" in out.columns:
        out["OptionType"] = out["OptionType"].astype(str).str.upper().str.strip().replace({"CALL": "CE", "PUT": "PE"})
    if "Expiry" in out.columns:
        out["Expiry"] = pd.to_datetime(out["Expiry"], errors="coerce").dt.normalize()
    return out.sort_values("Datetime").reset_index(drop=True)


def validate_option_schema(df: pd.DataFrame) -> list[str]:
    required = ["Datetime", "Open", "High", "Low", "Close", "Strike", "Expiry", "OptionType"]
    return [c for c in required if c not in df.columns]


def infer_strike_step(strikes: Iterable[float]) -> float:
    vals = np.sort(pd.Series(list(strikes)).dropna().unique())
    diffs = np.diff(vals)
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        raise ValueError("Cannot infer strike step from the supplied option contracts.")
    # Median spacing is safer than taking a single accidental small gap.
    return float(np.median(diffs))


def _contract_pool(options: pd.DataFrame, signal_time: pd.Timestamp, option_type: str) -> pd.DataFrame:
    t = pd.Timestamp(signal_time)
    return options[
        (options["Datetime"] <= t)
        & (options["Expiry"] >= t.normalize())
        & (options["OptionType"] == option_type.upper())
    ].copy()


def select_contract(
    options: pd.DataFrame,
    signal_time: pd.Timestamp,
    spot: float,
    option_type: str,
    strike_offset: int = 0,
    expiry_rank: int = 0,
) -> dict:
    """Choose expiry and strike using only contracts visible by signal_time."""
    required = {"Datetime", "Strike", "Expiry", "OptionType"}
    missing = required - set(options.columns)
    if missing:
        raise ValueError(f"Missing option selection fields: {sorted(missing)}")
    live = _contract_pool(options, signal_time, option_type).dropna(subset=["Strike", "Expiry"])
    if live.empty:
        raise ValueError("No eligible option contract exists at the signal timestamp.")
    expiries = sorted(live["Expiry"].unique())
    if expiry_rank < 0 or expiry_rank >= len(expiries):
        raise ValueError("Requested expiry rank is unavailable at the signal timestamp.")
    expiry = pd.Timestamp(expiries[expiry_rank])
    live = live[live["Expiry"] == expiry]
    step = infer_strike_step(live["Strike"])
    strikes = np.sort(live["Strike"].dropna().unique())
    atm = float(strikes[np.argmin(np.abs(strikes - float(spot)))])
    target = atm + int(strike_offset) * step
    strike = float(strikes[np.argmin(np.abs(strikes - target))])
    candidates = live[live["Strike"] == strike].sort_values("Datetime")
    row = candidates.iloc[-1]
    return {
        "Symbol": row.get("Symbol", None), "OptionType": option_type.upper(),
        "Strike": strike, "Expiry": expiry, "ATMStrike": atm,
        "StrikeStep": step, "SelectedAt": pd.Timestamp(signal_time),
    }


def get_quote(
    contract: dict,
    options: pd.DataFrame,
    execution_time: pd.Timestamp,
    mode: str = "strict",
    max_staleness_minutes: Optional[int] = None,
) -> tuple[pd.Series, float]:
    """Return a quote and its time distance from execution_time.

    Strict mode prevents using an old quote when entering. Legacy mode is kept
    only so we can prove whether earlier research depended on that convention.
    """
    t = pd.Timestamp(execution_time)
    rows = options[
        (options["Strike"] == float(contract["Strike"]))
        & (options["Expiry"] == pd.Timestamp(contract["Expiry"]))
        & (options["OptionType"] == contract["OptionType"])
    ].sort_values("Datetime")
    if rows.empty:
        raise ValueError("No quote data exists for the selected contract.")
    if mode == "strict":
        rows = rows[rows["Datetime"] >= t]
        if rows.empty:
            raise ValueError("No option quote exists at/after execution time.")
        row = rows.iloc[0]
    elif mode == "legacy":
        rows = rows[rows["Datetime"] <= t]
        if rows.empty:
            raise ValueError("No option quote exists at/before execution time.")
        row = rows.iloc[-1]
    else:
        raise ValueError("quote mode must be 'strict' or 'legacy'.")
    stale = abs((pd.Timestamp(row["Datetime"]) - t).total_seconds()) / 60.0
    if max_staleness_minutes is not None and stale > max_staleness_minutes:
        raise ValueError(f"Option quote is too far from execution time: {stale:.2f} minutes.")
    return row, float(stale)


def execution_price(row: pd.Series, side: str) -> float:
    side = side.lower()
    if side == "buy" and "Ask" in row.index and pd.notna(row["Ask"]):
        return float(row["Ask"])
    if side == "sell" and "Bid" in row.index and pd.notna(row["Bid"]):
        return float(row["Bid"])
    return float(row["Close"])


def apply_slippage(price: float, side: str, slippage_pct: float) -> float:
    """Apply round-trip slippage half on entry and half on exit."""
    if price <= 0 or slippage_pct <= 0:
        return float(price)
    half = slippage_pct / 2.0 / 100.0
    return float(price * (1.0 + half if side.lower() == "buy" else 1.0 - half))


def premium_return(entry: float, exit_price: float, option_type: str = "CE") -> float:
    if entry <= 0:
        return np.nan
    return (exit_price - entry) / entry


def summarize_option_trades(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0, "win_rate": np.nan, "profit_factor": np.nan, "total_pnl": 0.0}
    pnl = pd.to_numeric(trades["PnL"], errors="coerce").dropna()
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()
    return {
        "trades": int(len(pnl)), "win_rate": float((pnl > 0).mean()),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else np.inf,
        "total_pnl": float(pnl.sum()), "avg_pnl": float(pnl.mean()),
        "median_pnl": float(pnl.median()), "max_drawdown": float(_max_drawdown(pnl)),
    }


def _max_drawdown(pnl: pd.Series) -> float:
    equity = pnl.cumsum()
    return float((equity - equity.cummax()).min()) if len(equity) else 0.0


def option_data_quality_report(options: pd.DataFrame) -> dict:
    df = normalize_option_columns(options)
    missing = validate_option_schema(df)
    if missing:
        return {"ok": False, "missing_columns": missing}
    duplicate_keys = df.duplicated(["Datetime", "Strike", "Expiry", "OptionType"]).sum()
    bad_ohlc = ((df["High"] < df["Low"]) | (df["High"] < df["Close"]) | (df["Low"] > df["Close"])).sum()
    zero_close = (df["Close"] <= 0).sum()
    return {
        "ok": bool(duplicate_keys == 0 and bad_ohlc == 0 and zero_close == 0),
        "rows": int(len(df)), "start": df["Datetime"].min(), "end": df["Datetime"].max(),
        "contracts": int(df[["Strike", "Expiry", "OptionType"]].drop_duplicates().shape[0]),
        "duplicate_contract_bars": int(duplicate_keys), "bad_ohlc_rows": int(bad_ohlc),
        "nonpositive_close_rows": int(zero_close), "has_bid_ask": bool({"Bid", "Ask"}.issubset(df.columns)),
        "has_iv": bool("IV" in df.columns), "has_oi": bool("OI" in df.columns),
        "has_volume": bool("Volume" in df.columns),
    }
