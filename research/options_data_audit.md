# Historical NIFTY Options Data Audit

## Uploaded datasets

- `Nifty Options Data.zip`: 2017-2020 historical NIFTY options, 4 yearly nested archives, 47 monthly/expiry archives, 5,682 leaf option files, approximately 1.73 GB uncompressed text/CSV content.
- `Nifty spot and futures data.zip`: 2017-2020 1-minute NIFTY spot/futures data, 4 yearly archives.

## Option archive structure

The options dataset is nested ZIP -> yearly ZIP -> expiry/month ZIP -> contract files. Formats vary by period:

- 2017: `.txt` contract files such as `CE 10600.txt`.
- 2018: monthly archives contain CSV/TXT variants.
- 2019: expiry-window archives contain CSV/TXT variants; filenames use forms such as `NIFTY11450CE.csv`.
- 2020: filenames may include the expiry token, e.g. `NIFTY25Jun209300PE.txt`.

All tested option files contain contract identifier, date, time, OHLC and volume. No bid/ask fields are present in the source files.

## Coverage

The archive set contains 47 expiry/month packages across 2017-2020. The data has an apparent missing January 2018 package. Individual packages cover an expiry window beginning weeks before expiry and ending on the expiry date. The expiry can therefore be inferred from the maximum observed trade date/package metadata, but the ingestion layer should retain an explicit inferred-expiry field and validate it.

The separate NIFTY spot dataset contains 1-minute OHLC plus volume/open-interest-like trailing fields. The first observed spot minute is commonly 09:16, while option files can contain 09:15 observations.

## Contract matching audit

Using the existing RA-ORB baseline configuration (3-bar opening range, 4 consecutive closes, no gap filter, 0.60% underlying stop, 3R target, entry window through 11:00), the 2017-2020 NIFTY 5-minute dataset produces 653 baseline signals under the repository implementation.

For each signal, the historical option package active on that session was selected using the earliest expiry package covering the signal date. Strike spacing in the audited archives is consistently 50 points. ATM was defined as the nearest available strike to the NIFTY signal price.

For ATM CE/PE contracts:

- 638/653 signals (97.7%) had an entry and exit quote no more than one minute stale when using the repository's candle timestamp convention.
- Exact timestamp availability is materially lower at exits because option trades are sparse; therefore the backtest must use a documented last-observation-at-or-before-execution rule with a strict maximum staleness threshold.

## First diagnostic option-return pass

A diagnostic pass was run for ATM, one-strike ITM and one-strike OTM contracts. It uses option close prices only and the underlying strategy's exit timestamp. It is **not** the final strategy result because it does not yet model bid/ask, slippage, premium-based stops/targets, or exact intrabar execution.

With a one-minute maximum quote staleness:

| Contract | Matched trades | Win rate | Mean premium return | Median premium return |
|---|---:|---:|---:|---:|
| ATM | 638 | 45.0% | +3.64% | -3.01% |
| 1-strike ITM | 609 | 47.5% | +3.35% | -1.37% |
| 1-strike OTM | 608 | 43.6% | +5.41% | -4.46% |

These figures are diagnostic only. The gap between mean and median highlights why percentage return alone is not an adequate performance metric for long options.

## Required next-stage controls

1. Preserve the underlying RA-ORB signal timestamp convention and separately test strict candle-close timestamp alignment.
2. Select contracts using only information available at signal time.
3. Support ATM, one-strike ITM and one-strike OTM without post-hoc selection.
4. Use last available option observation at or before execution; reject quotes beyond a configurable staleness limit.
5. Add premium-based stop/target tests alongside underlying-driven exits.
6. Add bid/ask when available; otherwise apply explicit slippage stress because this dataset has no spread fields.
7. Calculate per-trade rupee P&L only after confirming the historical NIFTY lot size for each period.
8. Keep 2017-2020 results separate from the 2015-2026 underlying research; the options dataset does not extend to the later years.
9. Preserve train/validation/test chronology and avoid optimizing contract choice on the full sample.
10. Treat this first pass as data validation, not as evidence of deployable profitability.
