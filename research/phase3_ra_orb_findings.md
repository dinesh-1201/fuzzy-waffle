# Phase 3 — Regime-Aware ORB findings

## Candidate baseline

- Instrument: NIFTY index
- Bar size: 5 minutes
- Session: 09:15–15:25, 75 bars/day
- Opening range: first 3 bars (15 minutes)
- Signal: four consecutive closes beyond OR high/low
- Entry: close of the fourth confirmation candle
- Entry window: 09:30–11:00
- One trade per day
- Stop: 0.60% of entry
- Target: 3R
- Exit: stop, target, or 15:25 close
- Intrabar ambiguity: worst-case (stop first if both stop and target are touched)
- Gap filter: none in the final baseline

## Full-period result

The full-period grid shows the strongest simple region around four-close confirmation. The no-gap-filter, 0.60% stop, 3R target configuration produced 1,880 trades, 52.77% win rate, 1.334 profit factor, 0.1067R average trade, +200.5R total and -16.68R maximum drawdown under the stated OHLC assumptions.

A 0.50% stop with 3R target increased average R/trade to 0.1210R but increased drawdown to -22.25R and reduced win rate to 50.90%.

Adding a hard |gap| < 0.75% filter gave 1,666 trades, 53.18% win rate, 1.326 profit factor and +166.45R, but increased maximum drawdown to -20.90R. This means the earlier hypothesis that large gaps should automatically be excluded is not supported by this baseline ORB signal.

## Chronological robustness check

A 60% train / 20% validation / 20% test split was used. Parameters were selected on the first 60% using profit factor, then evaluated on the later periods without refitting.

Selected on train: four-close confirmation, no gap filter, 0.60% stop, 3R target.

- Train: 1,096 trades; 51.82% win rate; PF 1.389; +0.1270R/trade; +139.19R; max DD -11.79R
- Validation: 391 trades; 53.45% win rate; PF 1.292; +0.0916R/trade; +35.83R; max DD -16.68R
- Test: 393 trades; 54.71% win rate; PF 1.214; +0.0649R/trade; +25.50R; max DD -7.38R

The edge degrades out of sample but remains positive. That is materially more useful than a high in-sample win rate with a failed test period.

## Yearly stability

The selected full-period baseline was profitable in 10 of 12 calendar-year slices shown by the data, with negative years in 2023 and 2026 YTD. This is not sufficient for live deployment, but it indicates the edge is not entirely concentrated in one historical regime.

## Important caveats

1. This is an index-signal backtest, not an options P&L backtest.
2. OHLC data cannot determine intrabar ordering when both stop and target are touched; worst-case handling is intentionally conservative.
3. No slippage, brokerage, taxes or spread assumptions are included in R results yet.
4. The dataset has no volume, so VWAP/relative-volume filters are not tested.
5. The present grid is intentionally simple. More filters will only be retained if they improve out-of-sample stability rather than merely increasing in-sample performance.

## Next research gates

1. Test breakout direction against opening gap direction.
2. Add opening-range size and recent-volatility normalization.
3. Test time-of-breakout buckets.
4. Test day-of-week and volatility regimes as conditional filters.
5. Compare fixed stops with ATR/OR-based stops.
6. Add explicit transaction-cost and slippage stress tests.
7. Freeze a candidate only after walk-forward testing.
8. Only then move to historical option-chain/premium data for execution feasibility.
