import pandas as pd

from src.nifty_orb_backtest import ORBConfig, prepare_sessions, summarize


def test_summary_empty():
    out = summarize(pd.DataFrame())
    assert out["trades"] == 0


def test_prepare_session_count():
    rows = []
    base = pd.Timestamp("2024-01-02 09:15")
    for i in range(75):
        ts = base + pd.Timedelta(minutes=5 * i)
        rows.append({"Datetime": ts, "open": 100+i, "high": 101+i, "low": 99+i, "close": 100.5+i})
    df = pd.DataFrame(rows)
    prepared = prepare_sessions(df)
    assert len(prepared) == 75
    assert prepared["SessionDate"].nunique() == 1


def test_default_config_is_conservative():
    cfg = ORBConfig()
    assert cfg.confirmation_closes >= 2
    assert cfg.worst_case_ambiguous_bar is True
