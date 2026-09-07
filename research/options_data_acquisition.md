# Historical NIFTY Options Data Acquisition

## Recommended first research dataset

Zenodo record `10.5281/zenodo.10899828` contains one-minute NIFTY spot, futures and options data for 2017–2020. The options files contain option type, strike, trade date/time, OHLC and volume and are organized by expiry/month. The archive is approximately 312 MB for the options ZIP.

This dataset is suitable for the first premium-P&L research pass, but it does **not** provide everything required for a production-grade execution model (notably reliable bid/ask history and a full 2015–2026 span).

## Required normalized schema

```text
datetime
underlying
expiry
strike
right            # CE / PE
open
high
low
close
volume
open_interest   # nullable when unavailable
bid              # nullable for public OHLC datasets
ask              # nullable for public OHLC datasets
```

## Joining to the RA-ORB signal

For each underlying signal:

1. Determine the exact entry timestamp from NIFTY 5-minute data.
2. Select only contracts that existed at that timestamp.
3. Select the nearest eligible expiry according to the research rule.
4. Select ATM / ITM / OTM or delta-targeted strike using information available at entry only.
5. Enter at ask when bid/ask exists; otherwise use a conservative proxy and label the run as OHLC-only.
6. Exit according to the underlying strategy stop/target or the defined maximum holding time.
7. Record option premium P&L, underlying move, IV/Greeks when reconstructable, spread cost and time-to-expiry.

## Critical anti-look-ahead rules

- Never select a contract using its future high/low or future liquidity.
- Strike selection must use spot/index value known at entry.
- Expiry selection must use the contract calendar known at entry.
- Any IV or delta used for selection must be calculated from information available at entry.
- Costs must be applied at both entry and exit.

## Data-quality checks

Before any option backtest is accepted:

- verify timestamps are in IST;
- remove duplicate candles;
- verify expiry >= trade date;
- verify strike/right consistency;
- detect missing intraday segments;
- detect impossible OHLC values;
- compare underlying price to the corresponding spot/futures reference;
- check that selected contracts actually traded around the signal time;
- report coverage by year and expiry.

## Data coverage target

The long-term goal is a continuous 2017–2026 option dataset, preferably 1-minute or tick data. A public 2017–2020 dataset can validate the research pipeline first. A broker/vendor historical API can then extend the dataset and provide richer fields such as OI and, where available, quote-level information.

Do not mix different data sources silently. Each backtest run should record the source, coverage period, schema and execution assumptions in its manifest.
