from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import re
import zipfile

import pandas as pd


OPTION_COLUMNS = ["Contract", "Date", "Time", "Open", "High", "Low", "Close", "Volume"]


@dataclass(frozen=True)
class OptionContract:
    side: str
    strike: int
    expiry: pd.Timestamp
    archive_key: str
    path: str


def _year_from_name(name: str) -> int:
    m = re.search(r"(20\d{2})", name)
    if not m:
        raise ValueError(f"Cannot infer year from archive name: {name}")
    return int(m.group(1))


def parse_contract_filename(path: str) -> tuple[str, int] | None:
    """Parse common historical NIFTY option filename conventions.

    Supported examples include `CE 10600.txt`, `NIFTY11450CE.csv`, and
    date-coded names such as `NIFTY25Jun209300PE.txt`.
    """
    name = PurePosixPath(path).name
    m = re.search(r"(?:CE|PE)\s*(\d+)(?:\.csv|\.txt)$", name, re.I)
    if m:
        side = "CE" if re.search(r"CE", name, re.I) else "PE"
        return side, int(m.group(1))

    # Date-coded form: NIFTY25Jun20 + strike + CE/PE.
    m = re.search(r"NIFTY\d{2}[A-Za-z]{3}\d{2}(\d+)(CE|PE)\.(?:csv|txt)$", name, re.I)
    if m:
        return m.group(2).upper(), int(m.group(1))

    # Generic form where strike immediately precedes CE/PE.
    m = re.search(r"(\d+)(CE|PE)\.(?:csv|txt)$", name, re.I)
    if m:
        return m.group(2).upper(), int(m.group(1))
    return None


def _walk_nested(zbytes: bytes, prefix: str = ""):
    """Yield `(path, bytes)` for every CSV/TXT leaf in nested ZIPs."""
    with zipfile.ZipFile(BytesIO(zbytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            data = zf.read(info.filename)
            path = f"{prefix}/{info.filename}" if prefix else info.filename
            if info.filename.lower().endswith(".zip"):
                yield from _walk_nested(data, path)
            elif info.filename.lower().endswith((".csv", ".txt")):
                yield path, data


def iter_option_leaves(zip_path: str):
    """Iterate all leaf option files without extracting the archive to disk."""
    with zipfile.ZipFile(zip_path) as outer:
        for info in outer.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".zip"):
                continue
            year = _year_from_name(info.filename)
            for path, data in _walk_nested(outer.read(info.filename), info.filename):
                parsed = parse_contract_filename(path)
                if parsed is None:
                    continue
                yield year, path, parsed[0], parsed[1], data


def read_option_bytes(data: bytes) -> pd.DataFrame:
    """Read one historical option leaf into a normalized DataFrame."""
    df = pd.read_csv(BytesIO(data), header=None, names=OPTION_COLUMNS, usecols=range(8))
    df["Datetime"] = pd.to_datetime(
        df["Date"].astype(str) + " " + df["Time"].astype(str), errors="coerce"
    )
    df = df.dropna(subset=["Datetime"]).copy()
    df["Open"] = pd.to_numeric(df["Open"], errors="coerce")
    df["High"] = pd.to_numeric(df["High"], errors="coerce")
    df["Low"] = pd.to_numeric(df["Low"], errors="coerce")
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    return df[["Datetime", "Open", "High", "Low", "Close", "Volume"]].sort_values("Datetime")


def infer_expiry(df: pd.DataFrame) -> pd.Timestamp:
    """Infer an expiry from a contract/package data window.

    This is appropriate for the supplied expiry-window dataset, where each
    package terminates on the contract expiry date. The inferred value should
    still be validated against the package name/calendar before production use.
    """
    if df.empty:
        raise ValueError("Cannot infer expiry from empty option data")
    return pd.Timestamp(df["Datetime"].max().date())
