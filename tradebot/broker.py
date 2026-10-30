"""Connexion aux plateformes d'échange via ccxt (Binance, Kraken, Coinbase, Bybit, OKX, ...).

- PaperBroker : vraies données de marché, ordres SIMULÉS (aucun argent réel engagé).
- LiveBroker  : ordres RÉELS sur votre compte via l'API de la plateforme.
"""
import os
from typing import Optional

import pandas as pd

from .data import fetch_ohlcv


def make_exchange(name: str, with_keys: bool = False, sandbox: bool = False):
    import ccxt  # import paresseux : le backtest sur CSV ne nécessite pas ccxt

    if not hasattr(ccxt, name):
        raise ValueError(f"Plateforme inconnue pour ccxt : {name}")
    params = {"enableRateLimit": True}
    if with_keys:
        key, secret = os.getenv("EXCHANGE_API_KEY"), os.getenv("EXCHANGE_API_SECRET")
        if not key or not secret:
            raise RuntimeError("EXCHANGE_API_KEY / EXCHANGE_API_SECRET manquants (voir .env.example)")
        params.update(apiKey=key, secret=secret)
        if os.getenv("EXCHANGE_API_PASSWORD"):
            params["password"] = os.getenv("EXCHANGE_API_PASSWORD")
    ex = getattr(ccxt, name)(params)
    if sandbox:
        ex.set_sandbox_mode(True)
    ex.load_markets()
    return ex


class Broker:
    def __init__(self, exchange, symbol: str):
        self.exchange = exchange
        self.symbol = symbol
        market = exchange.market(symbol)
        self.base, self.quote = market["base"], market["quote"]
        self.min_amount = (market.get("limits", {}).get("amount", {}) or {}).get("min") or 0.0

    def candles(self, timeframe: str, limit: int = 300) -> pd.DataFrame:
        return fetch_ohlcv(self.exchange, self.symbol, timeframe, limit)

    def price(self) -> float:
        return float(self.exchange.fetch_ticker(self.symbol)["last"])

    def round_amount(self, qty: float) -> float:
        return float(self.exchange.amount_to_precision(self.symbol, qty))

    # À implémenter par les sous-classes
    def balances(self) -> tuple:  # (quote_libre, base_detenue)
        raise NotImplementedError

    def buy(self, qty: float) -> float:
        raise NotImplementedError

    def sell(self, qty: float) -> float:
        raise NotImplementedError

    def equity(self, price: Optional[float] = None) -> float:
        quote, base = self.balances()
        return quote + base * (price if price is not None else self.price())


class PaperBroker(Broker):
    def __init__(self, exchange, symbol: str, cash: float, base: float = 0.0,
                 fee_rate: float = 0.001, slippage: float = 0.0005):
        super().__init__(exchange, symbol)
        self.cash, self.base_qty = cash, base
        self.fee_rate, self.slippage = fee_rate, slippage

    def balances(self):
        return self.cash, self.base_qty

    def buy(self, qty: float) -> float:
        fill = self.price() * (1 + self.slippage)
        cost = qty * fill * (1 + self.fee_rate)
        if cost > self.cash:
            raise RuntimeError("Solde simulé insuffisant")
        self.cash -= cost
        self.base_qty += qty
        return fill

    def sell(self, qty: float) -> float:
        qty = min(qty, self.base_qty)
        fill = self.price() * (1 - self.slippage)
        self.cash += qty * fill * (1 - self.fee_rate)
        self.base_qty -= qty
        return fill


class LiveBroker(Broker):
    def balances(self):
        bal = self.exchange.fetch_balance()
        quote = float((bal.get(self.quote) or {}).get("free") or 0.0)
        base = float((bal.get(self.base) or {}).get("total") or 0.0)
        return quote, base

    def _fill_price(self, order) -> float:
        return float(order.get("average") or order.get("price") or self.price())

    def buy(self, qty: float) -> float:
        order = self.exchange.create_market_buy_order(self.symbol, self.round_amount(qty))
        return self._fill_price(order)

    def sell(self, qty: float) -> float:
        order = self.exchange.create_market_sell_order(self.symbol, self.round_amount(qty))
        return self._fill_price(order)
