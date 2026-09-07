"""Run the historical NIFTY -> option backtest from local uploaded data."""
from __future__ import annotations

import argparse
import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from src.nifty_orb_backtest import ORBConfig, backtest as backtest_nifty
from src.options_backtest import OptionBacktestConfig, backtest_options, summarize_option_trades


def _read_nested_zip(zf: zipfile.ZipFile, name: str) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    raw = zf.read(name)
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as child:
            for child_name in child.namelist():
                if not child_name.endswith("/"):
                    out.extend(_read_nested_zip(child, child_name))
    elif name.lower().endswith((".csv", ".txt")):
        out.append((name, raw))
    return out


def _parse_contract_metadata(name: str, raw: bytes):
    upper = Path(name).name.upper()
    option_type = "CE" if "CE" in upper else ("PE" if "PE" in upper else None)
    m = re.search(r"NIFTY(\d{2}[A-Z]{3}\d{2})(\d+(?:\.\d+)?)(CE|PE)", upper)
    if m:
        expiry = pd.to_datetime(m.group(1), format="%d%b%y", errors="coerce")
        return m.group(3), float(m.group(2)), expiry.normalize() if pd.notna(expiry) else None
    m = re.search(r"(?:^|[ _-])(CE|PE)[ _-]?(\d+(?:\.\d+)?)", upper)
    strike = float(m.group(2)) if m else None
    if m:
        option_type = m.group(1)
    try:
        sample = pd.read_csv(io.BytesIO(raw), nrows=2)
        cols = {str(c).strip().lower(): c for c in sample.columns}
        for key in ("expiry", "expiry date", "expiry_date"):
            if key in cols and not sample.empty:
                expiry = pd.to_datetime(sample[cols[key]].iloc[0], errors="coerce")
                if pd.notna(expiry):
                    return option_type, strike, pd.Timestamp(expiry).normalize()
    except Exception:
        pass
    return option_type, strike, None


def load_option_archives(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for archive in paths:
        with zipfile.ZipFile(archive) as outer:
            for name in outer.namelist():
                if name.endswith("/"):
                    continue
                for leaf_name, raw in _read_nested_zip(outer, name):
                    try:
                        option_type, strike, expiry = _parse_contract_metadata(leaf_name, raw)
                        if leaf_name.lower().endswith(".csv"):
                            df = pd.read_csv(io.BytesIO(raw))
                        else:
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
                        print(f"WARNING: {archive.name}:{leaf_name}: {exc}")
    if not frames:
        raise RuntimeError("No CSV/TXT option files were found.")
    return pd.concat(frames, ignore_index=True, sort=False)


def load_nifty(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    cols = {str(c).strip().lower(): c for c in df.columns}
    dt = pd.to_datetime(df[cols["date"]].astype(str) + " " + df[cols["time"]].astype(str), errors="coerce")
    return pd.DataFrame({
        "Datetime": dt,
        "Open": pd.to_numeric(df[cols["open"]], errors="coerce"),
        "High": pd.to_numeric(df[cols["high"]], errors="coerce"),
        "Low": pd.to_numeric(df[cols["low"]], errors="coerce"),
        "Close": pd.to_numeric(df[cols["close"]], errors="coerce"),
    }).dropna().sort_values("Datetime").reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the NIFTY RA-ORB option backtest on local historical archives.")
    ap.add_argument("--nifty", required=True, type=Path)
    ap.add_argument("--options", required=True, nargs="+", type=Path)
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--end", default="2020-12-31")
    ap.add_argument("--output", default="results/options_backtest", type=Path)
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    nifty = load_nifty(args.nifty)
    nifty = nifty[(nifty.Datetime >= start) & (nifty.Datetime <= end)].copy()

    # Previously tested baseline: 3 opening bars, 4 consecutive closes,
    # 0.60% NIFTY stop, 3R target, entry through 11:00.
    signals = backtest_nifty(nifty, ORBConfig(opening_bars=3, confirmation_closes=4, stop_pct=0.60, target_r=3.0, last_entry="11:00", exit_time="15:25"))
    signals = signals[(signals.EntryTime >= start) & (signals.EntryTime <= end)].copy()
    print(f"NIFTY bars: {len(nifty):,}")
    print(f"NIFTY RA-ORB signals: {len(signals):,}")

    options = load_option_archives(args.options)
    print(f"Raw option rows loaded: {len(options):,}")
    print(f"Option rows with expiry metadata: {options.get('Expiry', pd.Series(dtype='datetime64[ns]')).notna().sum():,}")

    configs = [
        ("ATM_nearest", OptionBacktestConfig(strike_offset=0, expiry_rank=0, quote_mode="strict")),
        ("ATM_next", OptionBacktestConfig(strike_offset=0, expiry_rank=1, quote_mode="strict")),
        ("ITM_nearest", OptionBacktestConfig(strike_offset=-1, expiry_rank=0, quote_mode="strict")),
        ("OTM_nearest", OptionBacktestConfig(strike_offset=1, expiry_rank=0, quote_mode="strict")),
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    signals.to_csv(args.output / "nifty_signals.csv", index=False)
    summary_rows = []
    for name, cfg in configs:
        trades = backtest_options(signals, options, cfg)
        trades.to_csv(args.output / f"{name}_trades.csv", index=False)
        completed = trades[trades.Status == "TRADE"] if "Status" in trades.columns else trades
        metrics = summarize_option_trades(completed)
        metrics.update({"setup": name, "rows": len(trades), "skipped": int((trades.Status == "SKIPPED").sum()) if "Status" in trades.columns else 0})
        summary_rows.append(metrics)
        print(metrics)
    pd.DataFrame(summary_rows).to_csv(args.output / "summary.csv", index=False)
    print(f"Results written to {args.output.resolve()}")


if __name__ == "__main__":
    main()
