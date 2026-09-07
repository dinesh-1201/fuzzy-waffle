import pandas as pd
import pytest

from src.options_backtest import (
    OptionBacktestConfig,
    backtest_options,
    get_quote,
    infer_strike_step,
    normalize_option_columns,
    select_contract,
)


def sample_options():
    rows = []
    for strike in (100, 150, 200):
        for typ in ("CE", "PE"):
            for tm, close in (("09:29", 10.0), ("09:30", 11.0), ("09:31", 12.0), ("09:35", 15.0)):
                rows.append({
                    "Datetime": pd.Timestamp(f"2020-01-02 {tm}"),
                    "Open": close, "High": close + 1, "Low": close - 1, "Close": close,
                    "Strike": strike, "Expiry": pd.Timestamp("2020-01-30"), "OptionType": typ,
                })
    return pd.DataFrame(rows)


def test_strike_step_uses_typical_spacing():
    assert infer_strike_step([100, 150, 200, 250]) == 50


def test_contract_selection_uses_only_visible_contracts():
    options = sample_options()
    c = select_contract(options, pd.Timestamp("2020-01-02 09:30"), 151, "CE")
    assert c["Strike"] == 150
    assert c["Expiry"] == pd.Timestamp("2020-01-30")


def test_strict_quote_uses_first_quote_after_execution():
    options = sample_options()
    c = select_contract(options, pd.Timestamp("2020-01-02 09:30"), 151, "CE")
    row, stale = get_quote(c, options, pd.Timestamp("2020-01-02 09:30:30"), "strict")
    assert row["Datetime"] == pd.Timestamp("2020-01-02 09:31")
    assert stale == pytest.approx(0.5)


def test_legacy_quote_is_explicitly_different():
    options = sample_options()
    c = select_contract(options, pd.Timestamp("2020-01-02 09:30"), 151, "CE")
    row, stale = get_quote(c, options, pd.Timestamp("2020-01-02 09:30:30"), "legacy")
    assert row["Datetime"] == pd.Timestamp("2020-01-02 09:30")
    assert stale == pytest.approx(0.5)


def test_normalize_common_columns():
    raw = pd.DataFrame({
        "date": ["2020-01-02"], "time": ["09:30"], "open": [10], "high": [11],
        "low": [9], "close": [10], "strike price": [150], "expiry date": ["2020-01-30"],
        "option type": ["call"],
    })
    out = normalize_option_columns(raw)
    assert out.loc[0, "OptionType"] == "CE"
    assert out.loc[0, "Strike"] == 150
    assert out.loc[0, "Datetime"] == pd.Timestamp("2020-01-02 09:30")


def test_full_signal_to_option_trade():
    options = sample_options()
    signals = pd.DataFrame([{
        "SessionDate": pd.Timestamp("2020-01-02").date(),
        "EntryTime": pd.Timestamp("2020-01-02 09:30"),
        "ExitTime": pd.Timestamp("2020-01-02 09:35"),
        "Direction": 1,
        "Entry": 151.0,
    }])
    trades = backtest_options(signals, options, OptionBacktestConfig(option_type="AUTO"))
    assert len(trades) == 1
    assert trades.loc[0, "Status"] == "TRADE"
    assert trades.loc[0, "OptionType"] == "CE"
    assert trades.loc[0, "Strike"] == 150
    assert trades.loc[0, "EntryPrice"] == pytest.approx(11.0)
    assert trades.loc[0, "ExitPrice"] == pytest.approx(15.0)
    assert trades.loc[0, "PnL"] == pytest.approx(4.0)


def test_premium_stop_is_applied_before_signal_exit():
    options = sample_options()
    mask = (
        (options["OptionType"] == "CE")
        & (options["Strike"] == 150)
        & (options["Datetime"] == pd.Timestamp("2020-01-02 09:31"))
    )
    options.loc[mask, "Low"] = 5.0
    signals = pd.DataFrame([{
        "EntryTime": pd.Timestamp("2020-01-02 09:30"),
        "ExitTime": pd.Timestamp("2020-01-02 09:35"),
        "Direction": 1,
        "Entry": 151.0,
    }])
    trades = backtest_options(
        signals, options,
        OptionBacktestConfig(option_type="CE", premium_stop_pct=10.0),
    )
    assert trades.loc[0, "ExitReason"] == "PREMIUM_SL"
    assert trades.loc[0, "ExitPrice"] == pytest.approx(9.9)
