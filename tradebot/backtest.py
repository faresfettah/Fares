"""Moteur de backtest bougie par bougie, sans biais d'anticipation.

- Le signal calculé à la clôture de la bougie i-1 est exécuté à l'ouverture de la bougie i.
- Les stops sont vérifiés sur le plus bas de chaque bougie (exécution au pire entre ouverture et stop).
- Frais et glissement sont appliqués à chaque ordre.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from .config import BotConfig
from .risk import DrawdownGuard, Position, position_size
from .strategy import BUY, SELL, generate_signals


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    reason: str


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: List[Trade] = field(default_factory=list)
    initial_capital: float = 0.0
    buy_and_hold_return: float = 0.0
    halted_by_drawdown: bool = False

    def metrics(self, periods_per_year: Optional[float] = None) -> dict:
        eq = self.equity
        total_return = eq.iloc[-1] / self.initial_capital - 1
        returns = eq.pct_change().dropna()
        if periods_per_year is None:
            periods_per_year = _infer_periods_per_year(eq.index)
        sharpe = 0.0
        if len(returns) > 1 and returns.std() > 0:
            sharpe = returns.mean() / returns.std() * np.sqrt(periods_per_year)
        max_dd = float((1 - eq / eq.cummax()).max())
        pnls = [t.pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float("inf") if wins else 0.0
        return {
            "capital_initial": self.initial_capital,
            "capital_final": float(eq.iloc[-1]),
            "rendement_total_%": round(100 * total_return, 2),
            "buy_and_hold_%": round(100 * self.buy_and_hold_return, 2),
            "drawdown_max_%": round(100 * max_dd, 2),
            "sharpe": round(float(sharpe), 2),
            "nb_trades": len(pnls),
            "taux_reussite_%": round(100 * len(wins) / len(pnls), 1) if pnls else 0.0,
            "profit_factor": round(profit_factor, 2) if np.isfinite(profit_factor) else "inf",
            "arret_coupe_circuit": self.halted_by_drawdown,
        }


def _infer_periods_per_year(index: pd.Index) -> float:
    if isinstance(index, pd.DatetimeIndex) and len(index) > 1:
        step = pd.Series(index).diff().median()
        if step and step.total_seconds() > 0:
            return pd.Timedelta(days=365).total_seconds() / step.total_seconds()
    return 252.0


def run_backtest(df: pd.DataFrame, cfg: BotConfig, initial_capital: float = 10_000.0) -> BacktestResult:
    data = generate_signals(df, cfg.strategy)
    r = cfg.risk
    cash = initial_capital
    pos: Optional[Position] = None
    entry_time = None
    guard = DrawdownGuard(r.max_drawdown, peak=initial_capital)
    trades: List[Trade] = []
    equity = []

    def close_position(price: float, time, reason: str):
        nonlocal cash, pos
        fill = price * (1 - r.slippage)
        proceeds = pos.qty * fill * (1 - r.fee_rate)
        cash += proceeds
        trades.append(Trade(entry_time, time, pos.entry_price, fill, pos.qty, proceeds - pos.cost, reason))
        pos = None

    for i in range(len(data)):
        row = data.iloc[i]
        t = data.index[i]

        if i > 0:
            prev = data.iloc[i - 1]
            # 1) Exécution du signal de la bougie précédente à l'ouverture
            if pos is not None and prev["signal"] == SELL:
                close_position(row["open"], t, "signal")
            elif pos is None and prev["signal"] == BUY and not guard.tripped:
                fill = row["open"] * (1 + r.slippage)
                qty = position_size(cash, fill, prev["atr"], r)
                if qty > 0:
                    pos = Position.open(qty, fill, prev["atr"], r)
                    if pos.cost <= cash:
                        cash -= pos.cost
                        entry_time = t
                    else:
                        pos = None

            # 2) Stop-loss / take-profit pendant la bougie
            if pos is not None:
                if row["low"] <= pos.stop:
                    close_position(min(row["open"], pos.stop), t, "stop-loss")
                elif pos.take_profit is not None and row["high"] >= pos.take_profit:
                    close_position(max(row["open"], pos.take_profit), t, "take-profit")
                else:
                    pos.update_trailing(row["high"], row["atr"], r)

        value = cash + (pos.qty * row["close"] if pos is not None else 0.0)
        if guard.update(value) and pos is not None:
            close_position(row["close"], t, "coupe-circuit")
            value = cash
        equity.append(value)

    if pos is not None:
        close_position(data.iloc[-1]["close"], data.index[-1], "fin du test")
        equity[-1] = cash

    bh = data["close"].iloc[-1] / data["close"].iloc[0] - 1
    return BacktestResult(
        equity=pd.Series(equity, index=data.index),
        trades=trades,
        initial_capital=initial_capital,
        buy_and_hold_return=float(bh),
        halted_by_drawdown=guard.tripped,
    )
