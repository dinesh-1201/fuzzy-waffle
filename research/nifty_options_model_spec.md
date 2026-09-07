# NIFTY Options Strategy Model Specification

This is a research specification only. No option performance is claimed until historical option data is available.

## Signal layer
Use the frozen/validated NIFTY underlying signal to produce:
- timestamp of confirmed entry
- direction (CALL/PUT)
- underlying entry price
- stop and target in underlying points
- intended maximum holding time

## Contract-selection layer
For every signal, select an option using only information available at the entry timestamp. Candidate dimensions:
- expiry: nearest weekly expiry that satisfies liquidity/holding constraints
- strike: ATM, 1-step ITM/OTM, or delta-targeted alternatives
- target delta band (to be calibrated from historical chain data)
- minimum premium/liquidity filters
- bid/ask spread and quote availability

## Required historical fields
At minimum:
- timestamp
- expiry
- strike
- call/put
- bid, ask, last/traded price
- volume/open interest when available
- underlying spot/index
- implied volatility or sufficient data to reconstruct it

## Option P&L
Model actual entry at ask and exit at bid for long options, with configurable slippage. Track:
- premium P&L
- underlying move contribution
- IV change
- theta/time decay
- spread cost
- expiry proximity
- max adverse/favourable excursion

## Risk controls
- fixed rupee risk per trade
- maximum daily loss
- maximum number of trades/day
- no averaging down
- mandatory exit before the selected session cutoff
- kill switch for data/API failures

## Validation
The options model must be evaluated chronologically. Contract selection parameters are fit only on training data. Validation and final test must use historical chains that were not used for parameter selection.

## Important distinction
A profitable NIFTY index backtest does not imply a profitable option-buying strategy. Option premium behavior depends on delta, gamma, theta, IV, spread, expiry, strike and execution quality. The options model is therefore a separate validation stage.
