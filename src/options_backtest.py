"""NIFTY option backtest engine scaffold.

This module deliberately does NOT claim option performance without historical
option data. It converts the existing underlying RA-ORB signal into a
contract-aware option backtest once normalized option candles are supplied.

Design rules:
- Signal comes only from the underlying NIFTY 5-minute data.
- Contract selection happens at signal time; no future information is used.
- Option candles are joined at/after the signal timestamp.
- Expiry, strike, option type, and entry premium are explicit fields.
- OHLC-only data uses conservative stop/target handling when both are hit.
- Bid/ask columns are supported when available for more realistic execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OptionBacktestConfig:
    """Contract and execution choices for a single test specification."""

    option_type: str = "CE"  # CE for long calls, PE for long puts
    strike_offset: int = 0  # 0=ATM, +1/-1 = one strike away from ATM
    expiry_rank: int = 0  # 0=nearest eligible expiry, 1=next eligible expiry
    premium_stop_pct: Optional[float] = None
    premium_target_pct: Optional[float] = None
    max_hold_minutes: Optional[int] = None
    exit_at_signal_exit: bool = True
    lot_size: int = 1
    round_trip_slippage_pct: float = 0.0


def normalize_option_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize common option-data column names to a stable internal schema."""
    aliases = {
        "datetime": "Datetime",
        "date": "Date",
        "trade_dt": "Date",
        "trade_date": "Date",
        "trade time": "Time",
        "trade_time": "Time",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "ltp": "Close",
        "volume": "Volume",
        "strike": "Strike",
        "strike price": "Strike",
        "expiry": "Expiry",
        "expiry date": "Expiry",
        "option type": "OptionType",
        "opt type": "OptionType",
        "instrument": "Instrument",
        "symbol": "Symbol",
        "bid": "Bid",
        "ask": "Ask",
        "iv": "IV",
        "open interest": "OI",
        "oi": "OI",
    }

    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    rename = {}
    for c in out.columns:
        key = c.lower().strip()
        if key in aliases:
            rename[c] = aliases[key]
    out = out.rename(columns=rename)

    if "Datetime" not in out.columns:
        if {"Date", "Time"}.issubset(out.columns):
            out["Datetime"] = pd.to_datetime(
                out["Date"].astype(str) + " " + out["Time"].astype(str),
                errors="coerce",
            )
        elif "Date" in out.columns:
            # Daily data is acceptable for schema checks but not for intraday execution.
            out["Datetime"] = pd.to_datetime(out["Date"], errors="coerce")

    if "Datetime" not in out.columns:
        raise ValueError("Option data needs Datetime, or Date + Time columns.")

    out["Datetime"] = pd.to_datetime(out["Datetime"], errors="coerce")
    out = out.dropna(subset=["Datetime"]).copy()

    for col in ["Open", "High", "Low", "Close", "Strike", "Bid", "Ask", "IV", "OI", "Volume"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    if "OptionType" in out.columns:
        out["OptionType"] = out["OptionType"].astype(str).str.upper().str.strip()
        out["OptionType"] = out["OptionType"].replace({"CALL": "CE", "PUT": "PE"})

    if "Expiry" in out.columns:
        out["Expiry"] = pd.to_datetime(out["Expiry"], errors="coerce").dt.normalize()

    return out.sort_values("Datetime").reset_index(drop=True)


def validate_option_schema(df: pd.DataFrame) -> list[str]:
    """Return missing fields needed for a tradable intraday option backtest."""
    required = ["Datetime", "Open", "High", "Low", "Close", "Strike", "Expiry", "OptionType"]
    return [c for c in required if c not in df.columns]


def infer_strike_step(strikes: Iterable[float]) -> float:
    """Infer the smallest positive strike spacing visible in the supplied contracts."""
    vals = np.sort(pd.Series(list(strikes)).dropna().unique())
    diffs = np.diff(vals)
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        raise ValueError("Cannot infer strike step from the supplied option contracts.")
    return float(np.min(diffs))


def select_contract(
    options: pd.DataFrame,
    signal_time: pd.Timestamp,
    spot: float,
    option_type: str,
    strike_offset: int = 0,
    expiry_rank: int = 0,
) -> dict:
    """Select the contract using only information available at signal_time.

    The nearest expiry is chosen from contracts that are still alive at the
    signal timestamp. ATM is the available strike nearest to spot. Offset is
    applied in strike steps, with CE/PE direction handled by the sign of the
    offset supplied by the caller.
    """
    required = {"Datetime", "Strike", "Expiry", "OptionType"}
    missing = required - set(options.columns)
    if missing:
        raise ValueError(f"Missing option selection fields: {sorted(missing)}")

    t = pd.Timestamp(signal_time)
    opt_type = option_type.upper()
    live = options[
        (options["Datetime"] <= t)
        & (options["Expiry"] >= t.normalize())
        & (options["OptionType"] == opt_type)
    ].copy()
    if live.empty:
        raise ValueError("No eligible option contract exists at the signal timestamp.")

    expiries = sorted(live["Expiry"].dropna().unique())
    if expiry_rank >= len(expiries):
        raise ValueError("Requested expiry rank is unavailable at the signal timestamp.")
    expiry = pd.Timestamp(expiries[expiry_rank])
    live = live[live["Expiry"] == expiry]

    step = infer_strike_step(live["Strike"])
    atm = float(live.iloc[(live["Strike"] - spot).abs().argsort().iloc[0]]["Strike"])
    target_strike = atm + strike_offset * step
    strike = float(live.iloc[(live["Strike"] - target_strike).abs().argsort().iloc[0]]["Strike"])

    candidates = live[live["Strike"] == strike].sort_values("Datetime")
    row = candidates.iloc[-1]
    return {
        "Symbol": row.get("Symbol", None),
        "OptionType": opt_type,
        "Strike": strike,
        "Expiry": expiry,
        "ATMStrike": atm,
        "StrikeStep": step,
        "SelectedAt": t,
    }


def execution_price(row: pd.Series, side: str) -> float:
    """Use ask for buys and bid for sells when available; otherwise Close."""
    side = side.lower()
    if side == "buy" and "Ask" in row.index and pd.notna(row["Ask"]):
        return float(row["Ask"])
    if side == "sell" and "Bid" in row.index and pd.notna(row["Bid"]):
        return float(row["Bid"])
    return float(row["Close"])


def premium_return(entry: float, exit_price: float, option_type: str) -> float:
    """Long-option percentage return before transaction costs."""
    if entry <= 0:
        return np.nan
    return (exit_price - entry) / entry


def summarize_option_trades(trades: pd.DataFrame) -> dict:
    """Return compact option-P&L statistics from a completed trade table."""
    if trades.empty:
        return {"trades": 0, "win_rate": np.nan, "profit_factor": np.nan, "total_pnl": 0.0}

    pnl = pd.to_numeric(trades["PnL"], errors="coerce").dropna()
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()
    pf = gross_profit / gross_loss if gross_loss > 0 else np.inf
    return {
        "trades": int(len(pnl)),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": float(pf),
        "total_pnl": float(pnl.sum()),
        "avg_pnl": float(pnl.mean()),
        "median_pnl": float(pnl.median()),
        "max_drawdown": float(_max_drawdown(pnl)),
    }


def _max_drawdown(pnl: pd.Series) -> float:
    equity = pnl.cumsum()
    dd = equity - equity.cummax()
    return float(dd.min()) if len(dd) else 0.0


def option_data_quality_report(options: pd.DataFrame) -> dict:
    """Basic checks before any performance calculation is allowed."""
    df = normalize_option_columns(options)
    missing = validate_option_schema(df)
    if missing:
        return {"ok": False, "missing_columns": missing}

    duplicate_keys = df.duplicated(["Datetime", "Strike", "Expiry", "OptionType"]).sum()
    bad_ohlc = ((df["High"] < df["Low"]) | (df["High"] < df["Close"]) | (df["Low"] > df["Close"])).sum()
    zero_close = (df["Close"] <= 0).sum()

    return {
        "ok": bool(duplicate_keys == 0 and bad_ohlc == 0 and zero_close == 0),
        "rows": int(len(df)),
        "start": df["Datetime"].min(),
        "end": df["Datetime"].max(),
        "contracts": int(df[["Strike", "Expiry", "OptionType"]].drop_duplicates().shape[0]),
        "duplicate_contract_bars": int(duplicate_keys),
        "bad_ohlc_rows": int(bad_ohlc),
        "nonpositive_close_rows": int(zero_close),
        "has_bid_ask": bool({"Bid", "Ask"}.issubset(df.columns)),
        "has_iv": bool("IV" in df.columns),
        "has_oi": bool("OI" in df.columns),
        "has_volume": bool("Volume" in df.columns),
    }
