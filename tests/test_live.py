"""Teste la boucle de trading avec une fausse plateforme (aucun réseau)."""
import json

import pandas as pd

from tradebot.broker import PaperBroker
from tradebot.config import BotConfig
from tradebot.data import synthetic
from tradebot.live import LiveTrader


class FakeExchange:
    def __init__(self, df):
        self.df, self.i = df, 300

    def market(self, symbol):
        return {"base": "BTC", "quote": "EUR", "limits": {"amount": {"min": 0.0}}}

    def parse_timeframe(self, tf):
        return 3600

    def milliseconds(self):
        return int(self.df.index[self.i].value // 1_000_000)

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1000):
        window = self.df.iloc[: self.i + 1]
        window = window[window.index >= pd.Timestamp(since, unit="ms")].iloc[:limit]
        return [[int(t.value // 1_000_000), *row] for t, row in zip(window.index, window.values.tolist())]

    def fetch_ticker(self, symbol):
        return {"last": float(self.df["close"].iloc[self.i])}

    def amount_to_precision(self, symbol, qty):
        return f"{qty:.6f}"


def test_paper_trader_trades_and_persists(tmp_path):
    ex = FakeExchange(synthetic(1500))
    broker = PaperBroker(ex, "BTC/USDT", cash=10_000)
    state = tmp_path / "state.json"
    trader = LiveTrader(broker, BotConfig(), budget=10_000, state_path=str(state))
    entries = 0
    for _ in range(1000):
        had = trader.position is not None
        trader.step()
        entries += (not had) and trader.position is not None
        ex.i += 1
    assert entries > 0
    assert broker.cash >= 0 and broker.base_qty >= 0
    saved = json.loads(state.read_text())
    assert saved["paper"] == [broker.cash, broker.base_qty]

    # Redémarrage : l'état (position, soldes) est restauré
    restored = LiveTrader(PaperBroker(ex, "BTC/USDT", cash=0), BotConfig(), budget=10_000, state_path=str(state))
    assert (restored.position is None) == (trader.position is None)
    assert restored.broker.cash == broker.cash
    assert restored.realized_pnl == trader.realized_pnl


def test_bot_never_uses_more_than_its_budget(tmp_path):
    """Compte avec 100 000 € mais budget de 1 000 € : aucune position ne dépasse le budget."""
    ex = FakeExchange(synthetic(1500))
    broker = PaperBroker(ex, "BTC/USDT", cash=100_000)
    trader = LiveTrader(broker, BotConfig(), budget=1_000, state_path=str(tmp_path / "s.json"))
    r = BotConfig().risk
    entries = 0
    for _ in range(1000):
        had = trader.position is not None
        capital = trader.budget + trader.realized_pnl
        trader.step()
        if not had and trader.position is not None:
            entries += 1
            assert trader.position.cost <= capital * r.max_position_pct * (1 + r.fee_rate + r.slippage) + 1e-9
        ex.i += 1
    assert entries > 0
    assert broker.cash > 100_000 - 1_000  # le reste du compte n'est jamais touché
