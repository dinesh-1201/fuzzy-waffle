# Phase 3B — RA-ORB Robustness Findings

Dataset: cleaned NIFTY 5-minute cash-index OHLC, 2,784 complete sessions, 2015-01-09 through 2026-05-18. No volume/options data.

## Baseline
15-minute opening range; four consecutive closes outside the range; entry at confirmation close; one trade/day; entry through 11:00; 0.60% stop; 3R target; EOD exit; stop-first for ambiguous OHLC bars.

Full sample: 1,880 trades, 52.77% wins, PF 1.334, +0.1067R/trade, +200.51R.

## Robustness findings

### Gap
Gap direction is not a useful standalone filter. Baseline trades aligned with the opening gap: 923 trades, PF 1.288; counter-gap: 957 trades, PF 1.379. This argues against forcing trades to agree with the gap.

Absolute gap buckets were strongest around 0.25–0.75%, but this is exploratory and should not be treated as a hard rule without walk-forward validation.

### Opening-range width
Opening-range width was the strongest simple conditioning variable tested. Using only the training period to set the threshold, the 25th percentile was approximately 0.2497% of price.

Filtering to OR width <= 0.2497% produced:
- Train: 282 trades, 56.03% win, PF 1.677, +0.1574R/trade, +44.39R
- Validation: 109 trades, 55.96% win, PF 1.796, +0.1717R/trade, +18.71R
- Untouched test: 89 trades, 58.43% win, PF 1.613, +0.1445R/trade, +12.86R

This is a materially more promising candidate than the unrestricted baseline, but the sample is smaller and must survive further walk-forward tests.

### Breakout timing
Requiring the first valid four-close confirmation at or after 10:00 reduced trade count but improved full-sample quality: 1,103 trades, 53.04% win, PF 1.436, +0.1319R/trade. Untouched test: 211 trades, 57.35% win, PF 1.290, +0.0798R/trade.

### Weekday
Monday was strongest in-sample (PF 1.575), but a Monday-only rule degraded materially in the later test (PF 1.082). Therefore weekday should remain a diagnostic feature, not a production filter.

A Tuesday exclusion combined with small OR width produced a strong test result (69 trades, 60.87% win, PF 1.707), but this is explicitly NOT frozen because adding a weekday rule after inspecting historical behavior creates a meaningful overfitting risk.

## Slippage stress
For the unrestricted baseline, subtracting round-trip slippage of 1, 2, 3 and 5 NIFTY index points gave approximately:
- 1 point: PF 1.244, +0.0809R/trade
- 2 points: PF 1.160, +0.0551R/trade
- 3 points: PF 1.082, +0.0293R/trade
- 5 points: PF 0.942, -0.0223R/trade

For the small-OR-width candidate, the same 1/2/3/5-point stress produced approximately +0.119/+0.0938/+0.0684/+0.0177R per trade respectively. This suggests the filtered candidate has more execution-cost headroom, although actual brokerage/taxes/slippage must be modeled for the chosen instrument.

## Current decision
Do NOT claim an 80% win rate. The research has instead found a potentially stronger and simpler edge: four-close ORB entries are substantially better when the initial 15-minute range is relatively narrow. The training-derived 25th-percentile OR-width filter is the current leading hypothesis.

Do not freeze the Tuesday exclusion. Do not move to live trading yet. Next gate is rolling walk-forward validation across multiple chronological windows and then an instrument-specific options model.
