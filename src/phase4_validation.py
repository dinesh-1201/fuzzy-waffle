from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from src.nifty_orb_backtest import prepare_sessions


@dataclass(frozen=True)
class WalkForwardConfig:
    train_years: int = 3
    test_months: int = 6
    or_quantile: float = 0.25
    fixed_or_width_pct: float | None = None
    stop_pct: float = 0.60
    target_r: float = 3.0


def _metrics(r: pd.Series) -> dict:
    r = pd.Series(r, dtype=float).dropna()
    if r.empty:
        return {"trades": 0, "win_rate": np.nan, "profit_factor": np.nan,
                "avg_r": np.nan, "total_r": 0.0, "max_dd_r": np.nan}
    wins = r[r > 0].sum()
    losses = -r[r < 0].sum()
    equity = r.cumsum()
    dd = equity - equity.cummax()
    return {
        "trades": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "profit_factor": float(wins / losses) if losses else np.inf,
        "avg_r": float(r.mean()),
        "total_r": float(r.sum()),
        "max_dd_r": float(dd.min()),
    }


def rolling_windows(session_dates: pd.Series, cfg: WalkForwardConfig):
    dates = pd.Series(pd.to_datetime(session_dates).sort_values().unique())
    cursor = dates.min() + pd.DateOffset(years=cfg.train_years)
    end = dates.max()
    while cursor <= end:
        train_start = cursor - pd.DateOffset(years=cfg.train_years)
        train_end = cursor - pd.Timedelta(days=1)
        test_end = min(cursor + pd.DateOffset(months=cfg.test_months) - pd.Timedelta(days=1), end)
        yield train_start, train_end, cursor, test_end
        cursor += pd.DateOffset(months=cfg.test_months)


def monte_carlo_r(r: Iterable[float], n_sims: int = 20_000, seed: int = 42) -> dict:
    """Bootstrap trade outcomes with replacement.

    This intentionally resamples observed trade R values rather than pretending
    to model future market paths. Use it as a distributional stress test only.
    """
    values = np.asarray(list(r), dtype=float)
    if values.size == 0:
        raise ValueError("At least one trade outcome is required")
    rng = np.random.default_rng(seed)
    sims = rng.choice(values, size=(n_sims, values.size), replace=True)
    totals = sims.sum(axis=1)
    means = sims.mean(axis=1)
    equity = np.cumsum(sims, axis=1)
    peak = np.maximum.accumulate(equity, axis=1)
    drawdowns = (equity - peak).min(axis=1)
    return {
        "n_sims": int(n_sims),
        "prob_positive_total_r": float((totals > 0).mean()),
        "total_r_p01": float(np.quantile(totals, 0.01)),
        "total_r_p05": float(np.quantile(totals, 0.05)),
        "total_r_p50": float(np.quantile(totals, 0.50)),
        "total_r_p95": float(np.quantile(totals, 0.95)),
        "avg_r_p05": float(np.quantile(means, 0.05)),
        "avg_r_p50": float(np.quantile(means, 0.50)),
        "avg_r_p95": float(np.quantile(means, 0.95)),
        "max_dd_r_p05": float(np.quantile(drawdowns, 0.05)),
        "max_dd_r_p50": float(np.quantile(drawdowns, 0.50)),
        "max_dd_r_p95": float(np.quantile(drawdowns, 0.95)),
    }


__all__ = ["WalkForwardConfig", "rolling_windows", "monte_carlo_r"]
