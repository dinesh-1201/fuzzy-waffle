"""Run the historical NIFTY -> option backtest from local uploaded data.

This runner is intentionally separate from the research code so the large option
archives never need to be committed to GitHub. It reads nested ZIP files from a
local folder, builds the NIFTY RA-ORB signals, then feeds those signals into the
option backtest engine.

Example:
    python scripts/run_options_backtest.py \
      --nifty "NIFTY_5min_CLEANED_2015_2026.xlsx" \
      --options "NiftyOptions 2017.zip" "NiftyOptions 2018.zip" \
                "NiftyOptions 2019.zip" "NiftyOptions 2020.zip" \
      --start 2017-01-01 --end 2020-12-31 \
      --output results/options_backtest
"""
from __future__ import annotations

import argparse
import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from src.options_backtest import OptionBacktestConfig, backtest_options, summarize_option_trades
from src.nifty_orb_backtest import backtest_ra_orb


def _read_nested_zip(zf: zipfile.ZipFile, name: str) -> list[tuple[str, bytes]]:
    """Recursively read CSV/TXT leaves from a ZIP without extracting everything."""
    out: list[tuple[str, bytes]] = []
    raw = zf.read(name)
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as child:
            for child_name in child.namelist():
                if child_name.endswith("/"):
                    continue
                out.extend(_read_nested_zip(child, child_name))
    elif name.lower().endswith((".csv", ".txt")):
        out.append((name, raw))
    return out


def _parse_contract_metadata(name: str, text: str) -> tuple[str | None, float | None, pd.Timestamp | None]:
    """Best-effort metadata parser for the supplied historical archive formats."""
    base = Path(name).name
    upper = base.upper()
    option_type = "CE" if "CE" in upper else ("PE" if "PE" in upper else None)

    # Formats such as NIFTY25Jun209600PE.csv
    m = re.search(r"NIFTY(\d{2}[A-Z]{3}\d{2})(\d+(?:\.\d+)?)(CE|PE)", upper)
    if m:
        expiry = pd.to_datetime(m.group(1), format="%d%b%y", errors="coerce")
        return m.group(3), float(m.group(2)), expiry.normalize() if pd.notna(expiry) else None

    # Formats such as "CE 8250.txt". The expiry is usually carried by the
    # enclosing monthly archive, so the loader leaves it unresolved here.
    m = re.search(r"(?:^|[ _-])(CE|PE)[ _-]?(\d+(?:\.\d+)?)", upper)
    strike = float(m.group(2)) if m else None
    if m:
        option_type = m.group(1)

    # Some CSV files include explicit expiry columns.
    try:
        first = pd.read_csv(io.BytesIO(text.encode()), nrows=2)
        cols = {str(c).strip().lower(): c for c in first.columns}
        for key in ("expiry", "expiry date", "expiry_date"):
            if key in cols and not first.empty:
                expiry = pd.to_datetime(first[cols[key]].iloc[0], errors="coerce")
                if pd.notna(expiry):
                    return option_type, strike, pd.Timestamp(expiry).normalize()
    except Exception:
        pass
    return option_type, strike, None


def load_option_archives(paths: list[Path]) -> pd.DataFrame:
    """Load supported option leaves into one normalized dataframe.

    The 2017/early-2018 text archives can require expiry information from their
    monthly parent archive. Those rows are retained with a missing Expiry so the
    backtest will skip them rather than inventing an expiry.
    """
    frames: list[pd.DataFrame] = []
    for archive in paths:
        with zipfile.ZipFile(archive) as outer:
            for name in outer.namelist():
                if name.endswith("/"):
                    continue
                for leaf_name, raw in _read_nested_zip(outer, name):
                    try:
                        sample = raw.decode("utf-8", errors="ignore")
                        option_type, strike, expiry = _parse_contract_metadata(leaf_name, sample)
                        if leaf_name.lower().endswith(".csv"):
                            df = pd.read_csv(io.BytesIO(raw))
                        else:
                            # Legacy text format: contract,date,time,open,high,low,close,volume
                            df = pd.read_csv(io.BytesIO(raw), header=None)
                            if df.shape[1] >= 7:
                                df = df.iloc[:, :8]
                                df.columns = ["Contract", "Date", "Time", "Open", "High", "Low", "Close", "Volume"][:df.shape[1]]
                        df["OptionType"] = option_type
                        df["Strike"] = strike
                        if expiry is not None:
                            df["Expiry"] = expiry
                        frames.append(df)
                    except Exception as exc:
                        print(f"WARNING: could not parse {archive.name}:{leaf_name}: {exc}")
    if not frames:
        raise RuntimeError("No CSV/TXT option files were found in the supplied archives.")
    out = pd.concat(frames, ignore_index=True, sort=False)
    return out


def load_nifty(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    cols = {str(c).strip().lower(): c for c in df.columns}
    if "datetime" in cols:
        dt = pd.to_datetime(df[cols["datetime"]], errors="coerce")
    else:
        if "date" not in cols or "time" not in cols:
            raise ValueError("NIFTY workbook must contain Date and Time columns.")
        dt = pd.to_datetime(df[cols["date"]].astype(str) + " " + df[cols["time"]].astype(str), errors="coerce")
    out = pd.DataFrame({
        "Datetime": dt,
        "Open": pd.to_numeric(df[cols["open"]], errors="coerce"),
        "High": pd.to_numeric(df[cols["high"]], errors="coerce"),
        "Low": pd.to_numeric(df[cols["low"]], errors="coerce"),
        "Close": pd.to_numeric(df[cols["close"]], errors="coerce"),
    }).dropna().sort_values("Datetime").reset_index(drop=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nifty", required=True, type=Path)
    ap.add_argument("--options", required=True, nargs="+", type=Path)
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--end", default="2020-12-31")
    ap.add_argument("--output", default="results/options_backtest", type=Path)
    args = ap.parse_args()

    nifty = load_nifty(args.nifty)
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    nifty = nifty[(nifty.Datetime >= start) & (nifty.Datetime <= end)].copy()

    # Proven baseline signal: 15-minute opening range + 4 consecutive closes,
    # 0.6% NIFTY stop, 3R target, one trade/day, entry through 11:00.
    signals = backtest_ra_orb(
        nifty,
        opening_bars=3,
        confirmations=4,
        stop_pct=0.006,
        target_r=3.0,
        entry_cutoff="11:00",
        one_trade_per_day=True,
    )
    signals = signals[(signals.EntryTime >= start) & (signals.EntryTime <= end)].copy()

    print(f"NIFTY bars: {len(nifty):,}")
    print(f"NIFTY signals: {len(signals):,}")

    options = load_option_archives(args.options)
    options = options[(pd.to_datetime(options.get("Date", pd.NaT), errors="coerce") >= start.normalize()) | options.get("Datetime", pd.Series(dtype="datetime64[ns]")).notna()].copy()
    print(f"Raw option rows loaded: {len(options):,}")

    configs = [
        ("ATM_nearest", OptionBacktestConfig(strike_offset=0, expiry_rank=0, quote_mode="strict")),
        ("ATM_next", OptionBacktestConfig(strike_offset=0, expiry_rank=1, quote_mode="strict")),
        ("ITM_nearest", OptionBacktestConfig(strike_offset=-1, expiry_rank=0, quote_mode="strict")),
        ("OTM_nearest", OptionBacktestConfig(strike_offset=1, expiry_rank=0, quote_mode="strict")),
    ]
    summary_rows = []
    args.output.mkdir(parents=True, exist_ok=True)
    for name, cfg in configs:
        trades = backtest_options(signals, options, cfg)
        trades.to_csv(args.output / f"{name}_trades.csv", index=False)
        metrics = summarize_option_trades(trades[trades.Status == "TRADE"] if "Status" in trades else trades)
        metrics["setup"] = name
        metrics["rows"] = len(trades)
        metrics["skipped"] = int((trades.Status == "SKIPPED").sum()) if "Status" in trades else 0
        summary_rows.append(metrics)
        print(name, metrics)
    pd.DataFrame(summary_rows).to_csv(args.output / "summary.csv", index=False)
    signals.to_csv(args.output / "nifty_signals.csv", index=False)
    print(f"Results written to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
