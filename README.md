# NIFTY Algo Research

Research and backtesting framework for NIFTY 5-minute strategies.

## Current phase

Phase 3 — strategy development.

Initial candidate: **Regime-Aware Opening Range Breakout (RA-ORB)**.

## Research principles

- No look-ahead bias.
- Separate signal discovery from execution modelling.
- Test simple rules before complex rules.
- Prefer robustness across time periods over peak backtest performance.
- Report win rate, expectancy, profit factor, drawdown, trade count and yearly stability.
- Keep NIFTY underlying-signal results separate from options P&L results.
- Apply transaction-cost and slippage assumptions before live deployment.

## Structure

- `src/` — reusable research and backtest code
- `configs/` — strategy parameter sets
- `research/` — notebooks and exploratory analysis
- `tests/` — deterministic unit tests
- `results/` — generated summaries and charts
- `data/` — local data only; raw data should not be committed unless licensing permits
