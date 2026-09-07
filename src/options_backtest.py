"""NIFTY option backtest helpers.

The underlying NIFTY signal is kept separate from the option trade.  The option
trade uses only quotes that are available at/after the signal execution time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OptionBacktestConfig:
    option_type: str = "AUTO"  # AUTO follows the NIFTY signal direction: CE up, PE down
    strike_offset: int = 0      # 0=nearest ATM, +1/-1=one strike away, etc.
    expiry_rank: int = 0        # 0=nearest eligible expiry
    premium_stop_pct: Optional[float] = None
    premium_target_pct: Optional[float] = None
    max_hold_minutes: Optional[int] = None
    exit_at_signal_exit: bool = True
    lot_size: int = 1
    round_trip_slippage_pct: float = 0.0
    quote_mode: str = "strict"  # strict=first quote at/after time; legacy=latest at/before
    max_entry_staleness_minutes: int = 2
    max_exit_staleness_minutes: int = 5
    worst_case_ambiguous_bar: bool = True


def normalize_option_columns(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "datetime": "Datetime", "date": "Date", "trade_dt": "Date", "trade_date": "Date",
        "time": "Time", "trade time": "Time", "trade_time": "Time",
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "ltp": "Close",
        "volume": "Volume", "strike": "Strike", "strike price": "Strike",
        "expiry": "Expiry", "expiry date": "Expiry", "option type": "OptionType", "opt type": "OptionType",
        "instrument": "Instrument", "symbol": "Symbol", "bid": "Bid", "ask": "Ask",
        "iv": "IV", "open interest": "OI", "oi": "OI",
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
        out["OptionType"] = (
            out["OptionType"].astype(str).str.upper().str.strip()
            .replace({"CALL": "CE", "PUT": "PE"})
        )
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
    """Choose an expiry and strike using only contracts visible by signal_time."""
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
    """Return a quote and its time distance from execution_time."""
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
    if price <= 0 or slippage_pct <= 0:
        return float(price)
    half = slippage_pct / 2.0 / 100.0
    return float(price * (1.0 + half if side.lower() == "buy" else 1.0 - half))


def premium_return(entry: float, exit_price: float, option_type: str = "CE") -> float:
    if entry <= 0:
        return np.nan
    return (exit_price - entry) / entry


def _max_drawdown(pnl: pd.Series) -> float:
    equity = pnl.cumsum()
    return float((equity - equity.cummax()).min()) if len(equity) else 0.0


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
        "median_pnl": float(pnl.median()), "max_drawdown": _max_drawdown(pnl),
    }


def _signal_direction(row: pd.Series) -> int:
    value = row.get("Direction", row.get("direction"))
    if pd.isna(value):
        raise ValueError("Signal trade is missing Direction.")
    return 1 if float(value) > 0 else -1


def _signal_value(row: pd.Series, names: tuple[str, ...]) -> object:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return row[name]
    return None


def _option_path(options: pd.DataFrame, contract: dict, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return options[
        (options["Strike"] == float(contract["Strike"]))
        & (options["Expiry"] == pd.Timestamp(contract["Expiry"]))
        & (options["OptionType"] == contract["OptionType"])
        & (options["Datetime"] >= pd.Timestamp(start))
        & (options["Datetime"] <= pd.Timestamp(end))
    ].sort_values("Datetime").copy()


def _find_premium_exit(
    path: pd.DataFrame,
    entry_price: float,
    cfg: OptionBacktestConfig,
    signal_exit: pd.Timestamp,
) -> tuple[pd.Series | None, str]:
    """Find premium stop/target; returns option bar and reason."""
    if path.empty:
        return None, "NO_PATH"
    stop = None if cfg.premium_stop_pct is None else entry_price * (1.0 - cfg.premium_stop_pct / 100.0)
    target = None if cfg.premium_target_pct is None else entry_price * (1.0 + cfg.premium_target_pct / 100.0)
    for _, bar in path.iterrows():
        hi = float(bar["High"])
        lo = float(bar["Low"])
        hit_stop = stop is not None and lo <= stop
        hit_target = target is not None and hi >= target
        if hit_stop and hit_target:
            return bar, "PREMIUM_SL" if cfg.worst_case_ambiguous_bar else "PREMIUM_TP"
        if hit_stop:
            return bar, "PREMIUM_SL"
        if hit_target:
            return bar, "PREMIUM_TP"
    return None, ""


def backtest_options(
    signal_trades: pd.DataFrame,
    options: pd.DataFrame,
    cfg: OptionBacktestConfig = OptionBacktestConfig(),
) -> pd.DataFrame:
    """Convert completed NIFTY signals into realistic long-option trades.

    Signal entry/exit times come from the underlying NIFTY backtest. The option
    is bought after the signal, then sold on a premium stop/target, the NIFTY
    signal exit, or the configured maximum holding time.
    """
    options = normalize_option_columns(options)
    missing = validate_option_schema(options)
    if missing:
        raise ValueError(f"Option data missing columns: {missing}")
    if signal_trades.empty:
        return pd.DataFrame()
    rows: list[dict] = []

    for _, signal in signal_trades.sort_values("EntryTime").iterrows():
        entry_time = pd.Timestamp(_signal_value(signal, ("EntryTime", "entry_time")))
        signal_exit = pd.Timestamp(_signal_value(signal, ("ExitTime", "exit_time")))
        spot = float(_signal_value(signal, ("Entry", "entry", "SpotEntry")))
        direction = _signal_direction(signal)
        option_type = cfg.option_type.upper()
        if option_type == "AUTO":
            option_type = "CE" if direction > 0 else "PE"
        if option_type not in {"CE", "PE"}:
            raise ValueError("option_type must be AUTO, CE or PE")

        try:
            contract = select_contract(
                options, entry_time, spot, option_type,
                strike_offset=cfg.strike_offset, expiry_rank=cfg.expiry_rank,
            )
            entry_row, entry_stale = get_quote(
                contract, options, entry_time, cfg.quote_mode, cfg.max_entry_staleness_minutes,
            )
        except ValueError as exc:
            rows.append({
                "SignalEntryTime": entry_time, "SignalExitTime": signal_exit,
                "Direction": direction, "OptionType": option_type,
                "Status": "SKIPPED", "SkipReason": str(exc),
            })
            continue

        entry_raw = execution_price(entry_row, "buy")
        entry_price = apply_slippage(entry_raw, "buy", cfg.round_trip_slippage_pct)
        hold_end = signal_exit if cfg.exit_at_signal_exit else entry_time + pd.Timedelta(minutes=cfg.max_hold_minutes or 10**6)
        if cfg.max_hold_minutes is not None:
            hold_end = min(hold_end, entry_time + pd.Timedelta(minutes=cfg.max_hold_minutes))

        path = _option_path(options, contract, entry_row["Datetime"], hold_end)
        premium_bar, premium_reason = _find_premium_exit(path, entry_price, cfg, signal_exit)

        if premium_bar is not None:
            exit_time_requested = pd.Timestamp(premium_bar["Datetime"])
            exit_row = premium_bar
            reason = premium_reason
            exit_raw = float(entry_price * (1.0 - cfg.premium_stop_pct / 100.0) if premium_reason == "PREMIUM_SL" else entry_price * (1.0 + cfg.premium_target_pct / 100.0))
            exit_stale = 0.0
        else:
            if hold_end < signal_exit:
                exit_time_requested = hold_end
            else:
                exit_time_requested = signal_exit
            try:
                exit_row, exit_stale = get_quote(
                    contract, options, exit_time_requested, cfg.quote_mode,
                    cfg.max_exit_staleness_minutes,
                )
            except ValueError as exc:
                rows.append({
                    "SignalEntryTime": entry_time, "SignalExitTime": signal_exit,
                    "Direction": direction, "OptionType": option_type,
                    "Strike": contract["Strike"], "Expiry": contract["Expiry"],
                    "Status": "SKIPPED", "SkipReason": f"Exit: {exc}",
                    "EntryTime": entry_row["Datetime"], "EntryPrice": entry_price,
                    "EntryStalenessMin": entry_stale,
                })
                continue
            exit_time_requested = pd.Timestamp(exit_row["Datetime"])
            exit_raw = execution_price(exit_row, "sell")
            reason = "SIGNAL_EXIT" if exit_time_requested == signal_exit else "MAX_HOLD"

        exit_price = apply_slippage(exit_raw, "sell", cfg.round_trip_slippage_pct)
        pnl_per_unit = exit_price - entry_price
        pnl = pnl_per_unit * cfg.lot_size
        rows.append({
            "SignalEntryTime": entry_time, "SignalExitTime": signal_exit,
            "EntryTime": pd.Timestamp(entry_row["Datetime"]), "ExitTime": exit_time_requested,
            "Direction": direction, "OptionType": option_type,
            "Strike": contract["Strike"], "ATMStrike": contract["ATMStrike"],
            "StrikeOffset": cfg.strike_offset, "Expiry": contract["Expiry"],
            "DTE": (pd.Timestamp(contract["Expiry"]) - entry_time.normalize()).days,
            "EntryPrice": entry_price, "ExitPrice": exit_price,
            "EntryStalenessMin": entry_stale, "ExitStalenessMin": exit_stale,
            "PnL": pnl, "ReturnPct": premium_return(entry_price, exit_price) * 100.0,
            "ExitReason": reason, "Status": "TRADE", "SkipReason": "",
        })
    return pd.DataFrame(rows)


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
