# NIFTY Options Backtest Protocol

## Objective
Convert the validated underlying NIFTY RA-ORB signal into a realistic long-option test without look-ahead bias.

## Signal
- Underlying: cleaned NIFTY 5-minute OHLC dataset.
- Opening range: first 3 five-minute candles.
- Baseline signal: 4 consecutive closes beyond the opening-range high/low.
- Entry: confirmation-candle close.
- Existing underlying stop/target: 0.60% stop and 3R target.
- One trade per session, last entry 11:00, forced underlying exit 15:25.

## Contract selection
At the exact signal timestamp:
1. Keep only contracts whose expiry has not passed.
2. Choose the configured expiry rank (nearest eligible by default).
3. Determine ATM from the NIFTY spot price at signal time.
4. Select ATM or an explicit strike offset.
5. Select CE for bullish signals and PE for bearish signals.
6. Never use information from a future candle, future expiry chain, or future contract listing.

## Execution hierarchy
Best case:
- Buy at option ask.
- Sell at option bid.

Fallback:
- If bid/ask are unavailable, use OHLC close and apply explicit slippage stress.

## Exit models
Both should be tested separately:

### Model A — underlying-driven exit
The option remains open until the underlying strategy stop, target, or forced session exit occurs. The option is marked using the first available option price at/after the underlying exit timestamp.

### Model B — premium-driven exit
The option itself has a premium stop/target, with an optional maximum holding time. This answers whether the signal still works after theta and IV effects are introduced.

## Required outputs
For each configuration report:
- number of trades
- win rate
- profit factor
- average and median option return
- total P&L in points and rupees
- maximum drawdown
- average holding time
- expiry distance at entry
- ATM/ITM/OTM comparison
- theta/IV contribution where inputs permit it
- transaction-cost and slippage sensitivity

## Data quality gate
Do not publish strategy performance if any of these fail:
- duplicate contract bars
- invalid OHLC relationships
- non-positive option close
- missing expiry/strike/option type
- timestamps that cannot be aligned to the underlying signal

## First dataset
The first public candidate is the Zenodo NIFTY spot/futures/options one-minute dataset covering 2017–2020. It contains option type, strike, trade date/time, OHLC and volume, organized by expiry/month. It must be uploaded locally before the backtest is run.

## Coverage expansion
After the first pass, expand beyond 2020 using a source with reliable expired-contract history. A 2017–2020 dataset is a validation slice, not proof for the full 2015–2026 underlying period.

## No-go rules
- No option P&L claims from underlying R alone.
- No selecting today's best strike/expiry after observing the day's outcome.
- No using future IV, future OI, or future volume to choose the entry contract.
- No live orders in this research stage.
