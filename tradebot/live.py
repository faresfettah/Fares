"""Boucle de trading en continu (paper ou réel).

Le stop-loss, le take-profit et le stop suiveur sont surveillés par le bot lui-même :
le bot doit donc rester allumé tant qu'une position est ouverte.
"""
import json
import logging
import os
import time
from dataclasses import asdict
from typing import Optional

from .broker import Broker
from .config import BotConfig
from .risk import DrawdownGuard, Position, position_size
from .strategy import BUY, SELL, explain, generate_signals

log = logging.getLogger("tradebot")


class LiveTrader:
    def __init__(self, broker: Broker, cfg: BotConfig, state_path: str = "state.json"):
        self.broker, self.cfg, self.state_path = broker, cfg, state_path
        self.position: Optional[Position] = None
        self.last_candle: Optional[str] = None
        self.guard = DrawdownGuard(cfg.risk.max_drawdown)
        self._load()

    # --- persistance : le bot peut redémarrer sans perdre sa position ---
    def _load(self):
        if not os.path.exists(self.state_path):
            return
        with open(self.state_path) as f:
            s = json.load(f)
        if s.get("position"):
            self.position = Position(**s["position"])
        self.last_candle = s.get("last_candle")
        self.guard.peak = s.get("peak", 0.0)
        self.guard.tripped = s.get("tripped", False)
        if "paper" in s and hasattr(self.broker, "cash"):
            self.broker.cash, self.broker.base_qty = s["paper"]

    def _save(self):
        s = {
            "position": asdict(self.position) if self.position else None,
            "last_candle": self.last_candle,
            "peak": self.guard.peak,
            "tripped": self.guard.tripped,
        }
        if hasattr(self.broker, "cash"):
            s["paper"] = [self.broker.cash, self.broker.base_qty]
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, indent=2)
        os.replace(tmp, self.state_path)

    def _exit(self, reason: str):
        fill = self.broker.sell(self.position.qty)
        pnl = self.position.qty * fill * (1 - self.cfg.risk.fee_rate) - self.position.cost
        log.info("VENTE %.6f @ %.4f (%s) | PnL estimé %+.2f %s",
                 self.position.qty, fill, reason, pnl, self.broker.quote)
        self.position = None

    def step(self):
        r = self.cfg.risk
        df = self.broker.candles(self.cfg.timeframe, limit=max(300, self.cfg.strategy.slow_ema * 4))
        closed = df.iloc[:-1]  # la dernière bougie est encore en cours : on l'ignore
        data = generate_signals(closed, self.cfg.strategy)
        last = data.iloc[-1]
        candle_id = str(data.index[-1])
        new_candle = candle_id != self.last_candle
        price = self.broker.price()

        # 1) Gestion de la position ouverte (à chaque passage)
        if self.position is not None:
            self.position.update_trailing(max(price, float(df["high"].iloc[-1])), float(last["atr"]), r)
            if price <= self.position.stop:
                self._exit("stop-loss")
            elif self.position.take_profit is not None and price >= self.position.take_profit:
                self._exit("take-profit")
            elif new_candle and last["signal"] == SELL:
                self._exit("signal")

        # 2) Coupe-circuit
        equity = self.broker.equity(price)
        if self.guard.update(equity):
            if self.position is not None:
                self._exit("coupe-circuit")
            log.warning("COUPE-CIRCUIT actif : drawdown >= %.0f %%. Aucune nouvelle position.",
                        100 * r.max_drawdown)

        # 3) Nouvelle entrée, uniquement sur une bougie nouvellement clôturée
        if new_candle:
            log.info("%s %s", candle_id, explain(last))
            if self.position is None and last["signal"] == BUY and not self.guard.tripped:
                quote, _ = self.broker.balances()
                qty = position_size(min(equity, quote), price * (1 + r.slippage), float(last["atr"]), r)
                qty = self.broker.round_amount(qty)
                if qty > 0 and qty >= self.broker.min_amount:
                    fill = self.broker.buy(qty)
                    self.position = Position.open(qty, fill, float(last["atr"]), r)
                    log.info("ACHAT %.6f @ %.4f | stop %.4f | objectif %s",
                             qty, fill, self.position.stop,
                             f"{self.position.take_profit:.4f}" if self.position.take_profit else "-")
                else:
                    log.info("Signal d'achat ignoré : quantité trop faible (%.8f)", qty)
            self.last_candle = candle_id

        log.debug("Capital : %.2f %s", equity, self.broker.quote)
        self._save()

    def run(self, poll_seconds: int = 60):
        log.info("Démarrage %s %s (%s) - Ctrl+C pour arrêter",
                 type(self.broker).__name__, self.cfg.symbol, self.cfg.timeframe)
        while True:
            try:
                self.step()
            except KeyboardInterrupt:
                raise
            except Exception:  # réseau, API... on log et on réessaie au prochain cycle
                log.exception("Erreur pendant le cycle, nouvelle tentative au prochain passage")
            time.sleep(poll_seconds)
