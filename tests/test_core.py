import numpy as np
import pandas as pd
import pytest

from tradebot.backtest import run_backtest
from tradebot.config import BotConfig, RiskConfig, StrategyConfig
from tradebot.data import synthetic
from tradebot.indicators import rsi
from tradebot.risk import DrawdownGuard, Position, position_size
from tradebot.strategy import generate_signals


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 100, dtype=float))
    assert rsi(up).dropna().iloc[-1] == 100.0
    r = rsi(synthetic(500)["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_position_size_respects_risk_and_cap():
    cfg = RiskConfig(risk_per_trade=0.01, atr_stop_mult=2, max_position_pct=0.25)
    qty = position_size(10_000, price=100, atr_value=5, cfg=cfg)
    assert qty * 2 * 5 == pytest.approx(100)  # perte au stop = 1 % du capital
    qty = position_size(10_000, price=100, atr_value=0.01, cfg=cfg)
    assert qty * 100 == pytest.approx(2_500)  # plafonné à 25 % du capital


def test_trailing_stop_only_moves_up():
    cfg = RiskConfig()
    p = Position.open(1, 100, 2, cfg)
    p.update_trailing(110, 2, cfg)
    assert p.stop == pytest.approx(106)
    p.update_trailing(105, 2, cfg)
    assert p.stop == pytest.approx(106)


def test_drawdown_guard():
    g = DrawdownGuard(0.2)
    g.update(100)
    assert not g.update(85)
    assert g.update(79)


def test_signals_have_no_lookahead():
    df = synthetic(600)
    cfg = StrategyConfig()
    full = generate_signals(df, cfg)["signal"]
    partial = generate_signals(df.iloc[:400], cfg)["signal"]
    pd.testing.assert_series_equal(full.iloc[:400], partial)


def test_backtest_accounting_is_consistent():
    df = synthetic(2000)
    res = run_backtest(df, BotConfig(), initial_capital=10_000)
    assert res.trades
    assert res.equity.iloc[-1] == pytest.approx(10_000 + sum(t.pnl for t in res.trades))


def test_no_free_money_on_flat_market():
    n = 500
    df = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1.0},
                      index=pd.date_range("2024", periods=n, freq="1h"))
    res = run_backtest(df, BotConfig())
    assert res.equity.iloc[-1] <= 10_000
