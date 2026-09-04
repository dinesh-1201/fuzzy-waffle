# Phase 3B — RA-ORB Robustness Research

## Objective
Determine whether the Phase 3 RA-ORB edge is broad enough to justify further development, rather than selecting a single backtest optimum.

## Candidate baseline
- 5-minute NIFTY OHLC
- First 3 candles define the 15-minute opening range
- 4 consecutive completed closes beyond OR high/low confirm direction
- Entry at confirmation candle close
- One trade per session
- Baseline stop: 0.60%
- Baseline target: 3R
- Entry window: 09:30–11:00
- Ambiguous OHLC bar: stop-first (conservative)

## Feature families
1. Gap regime: <0.25%, 0.25–0.50%, 0.50–0.75%, 0.75–1.00%, 1.00–1.50%, 1.50–2.00%, >2.00%; retain gap direction.
2. Opening-range size: absolute OR width and OR width normalized by price; compare quantiles rather than arbitrary cutoffs.
3. Breakout timing: first valid confirmation bucket (09:35–10:00, 10:00–10:30, 10:30–11:00, later).
4. Weekday: Monday–Friday as a robustness dimension, not an optimization target.
5. Volatility: prior-session range and rolling historical daily range proxies, computed only from information available before entry.

## Validation protocol
- Chronological train/validation/test split.
- Candidate parameters selected only on train.
- Validation used for rejection/selection of broad hypotheses.
- Final test is untouched until the candidate is frozen.
- Prefer simple monotonic filters and broad parameter plateaus.

## Execution stress
- Apply conservative slippage in index points at entry and exit.
- Test multiple slippage assumptions.
- Test ambiguous bars as stop-first and, separately, target-first sensitivity.
- Report trade count, win rate, profit factor, expectancy in R, total R, max drawdown, and yearly stability.

## Acceptance standard
A candidate is not considered production-ready merely because it has high full-sample profit. It must retain positive expectancy and acceptable drawdown in the untouched chronological test, remain plausible under execution costs, and avoid dependence on a narrow parameter combination.

## Options gate
No option strategy is approved until the underlying signal passes the robustness gate. Option-specific P&L requires historical option data and a separate execution model including premium, IV, theta, spread and strike-selection effects.
