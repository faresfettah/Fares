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
        return {"base": "BTC", "quote": "USDT", "limits": {"amount": {"min": 0.0}}}

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
    trader = LiveTrader(broker, BotConfig(), state_path=str(state))
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
    restored = LiveTrader(PaperBroker(ex, "BTC/USDT", cash=0), BotConfig(), state_path=str(state))
    assert (restored.position is None) == (trader.position is None)
    assert restored.broker.cash == broker.cash
