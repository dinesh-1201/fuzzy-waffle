# First Real Option-Premium Diagnostic — 2019–2020

## Purpose
This is a pipeline validation, not a final strategy result. It connects the existing RA-ORB underlying signal to actual historical NIFTY option contracts.

## Signal model
- Existing RA-ORB baseline: 3-bar opening range, 4 consecutive closes beyond the range, entry window through 11:00.
- Stop: 0.60% of NIFTY entry.
- Target: 3R.
- One trade per session.
- Exit timing follows the underlying strategy exit timestamp.

## Option model used for this diagnostic
- Directional contract: CE for bullish signal, PE for bearish signal.
- Nearest available expiry on or after the signal date.
- Strike: closest available strike to NIFTY spot entry.
- Entry/exit premium: latest recorded option close at or before the corresponding signal/exit timestamp.
- No bid/ask, brokerage, tax, or slippage adjustment yet.

## Coverage
For 2019–2020, the baseline produced 332 underlying signals. 224 could be matched to a directional option contract with usable entry and exit observations under the current archive structure.

The lower coverage is primarily a data-archive/contract-availability issue, not evidence of failed signals. The loader must be expanded to handle the older 2017–2018 TXT structures and archive-specific contract layouts before using the full 2017–2020 sample for conclusions.

## Diagnostic results
| Contract | Trades | Mean premium return | Median premium return |
|---|---:|---:|---:|
| Nearest-expiry nearest-strike directional | 224 | +4.00% | -2.05% |
| CE subset |  | +6.10% |  |
| PE subset |  | +2.18% |  |

These figures are raw premium returns, not account-level returns. They are intentionally not presented as strategy performance.

## Important finding
The positive mean with a negative median shows a skewed distribution: a relatively small number of large winners can dominate many small/medium losses. Therefore the next analysis must use trade-level P&L, profit factor, drawdown, losing streaks, and cost stress rather than mean option return alone.

## Timestamp audit
- Entry staleness was usually zero minutes in the matched sample.
- Maximum observed entry staleness: 12 minutes.
- Exit staleness could be materially larger, with a maximum of 43 minutes in this diagnostic.
- This must be controlled explicitly in the production backtest. A stale quote cannot silently be treated as an executable market price.

## Next gate
1. Finish 2017–2018 TXT normalization.
2. Build a strict timestamp/executability policy.
3. Test ATM, 1-strike ITM, 2-strike ITM, 1-strike OTM and 2-strike OTM.
4. Compare nearest versus next expiry.
5. Test underlying-driven versus premium-driven exits.
6. Add slippage/cost stress.
7. Freeze the methodology before final train/validation/test evaluation.

No live trading is implied by this diagnostic.