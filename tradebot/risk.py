from dataclasses import dataclass
from typing import Optional

from .config import RiskConfig


def position_size(equity: float, price: float, atr_value: float, cfg: RiskConfig) -> float:
    """Quantité à acheter pour ne perdre que `risk_per_trade` du capital si le stop est touché."""
    if equity <= 0 or price <= 0 or atr_value <= 0:
        return 0.0
    stop_distance = cfg.atr_stop_mult * atr_value
    qty_by_risk = (equity * cfg.risk_per_trade) / stop_distance
    qty_by_cap = (equity * cfg.max_position_pct) / price
    return max(0.0, min(qty_by_risk, qty_by_cap))


@dataclass
class Position:
    qty: float
    entry_price: float
    stop: float
    take_profit: Optional[float]
    highest: float
    cost: float  # montant total payé, frais inclus

    @classmethod
    def open(cls, qty: float, entry: float, atr_value: float, cfg: RiskConfig) -> "Position":
        risk = cfg.atr_stop_mult * atr_value
        tp = entry + cfg.take_profit_r * risk if cfg.take_profit_r > 0 else None
        cost = qty * entry * (1 + cfg.fee_rate)
        return cls(qty=qty, entry_price=entry, stop=entry - risk, take_profit=tp, highest=entry, cost=cost)

    def update_trailing(self, high: float, atr_value: float, cfg: RiskConfig) -> None:
        if not cfg.trailing_stop or atr_value <= 0:
            return
        self.highest = max(self.highest, high)
        self.stop = max(self.stop, self.highest - cfg.atr_stop_mult * atr_value)


class DrawdownGuard:
    """Coupe-circuit : bloque toute nouvelle position si la perte depuis le pic dépasse le seuil."""

    def __init__(self, max_drawdown: float, peak: float = 0.0):
        self.max_drawdown = max_drawdown
        self.peak = peak
        self.tripped = False

    def update(self, equity: float) -> bool:
        self.peak = max(self.peak, equity)
        if self.peak > 0 and (self.peak - equity) / self.peak >= self.max_drawdown:
            self.tripped = True
        return self.tripped
