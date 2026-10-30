"""Boucle de trading en continu (paper ou réel).

Le stop-loss, le take-profit et le stop suiveur sont surveillés par le bot lui-même :
le bot doit donc rester allumé tant qu'une position est ouverte.
"""
import json
import logging
import os
import threading
from dataclasses import asdict
from typing import Callable, Optional

from .broker import Broker
from .config import BotConfig
from .risk import DrawdownGuard, Position, position_size
from .strategy import BUY, SELL, explain, generate_signals

log = logging.getLogger("tradebot")


class LiveTrader:
    def __init__(self, broker: Broker, cfg: BotConfig, budget: float, state_path: str = "state.json",
                 notify: Optional[Callable[[str], None]] = None):
        """`budget` : somme maximale confiée au bot. Il n'utilisera jamais plus, même si le
        compte contient davantage, et le coupe-circuit se calcule sur ce budget."""
        self.broker, self.cfg, self.state_path = broker, cfg, state_path
        self.budget = budget
        self.realized_pnl = 0.0
        self.position: Optional[Position] = None
        self.last_candle: Optional[str] = None
        self.guard = DrawdownGuard(cfg.risk.max_drawdown, peak=budget)
        self.notify = notify or (lambda msg: None)
        self.paused = False            # pause : plus de nouvel achat, la position reste protégée
        self.last_price: Optional[float] = None
        self.last_analysis = ""
        self._close_requested = False
        self._lock = threading.RLock()  # les commandes Telegram arrivent depuis un autre thread
        self._wake = threading.Event()
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
        self.realized_pnl = s.get("realized_pnl", 0.0)
        self.paused = s.get("paused", False)
        self.guard.peak = s.get("peak", 0.0)
        self.guard.tripped = s.get("tripped", False)
        if "paper" in s and hasattr(self.broker, "cash"):
            self.broker.cash, self.broker.base_qty = s["paper"]

    def _save(self):
        s = {
            "position": asdict(self.position) if self.position else None,
            "last_candle": self.last_candle,
            "realized_pnl": self.realized_pnl,
            "paused": self.paused,
            "peak": self.guard.peak,
            "tripped": self.guard.tripped,
        }
        if hasattr(self.broker, "cash"):
            s["paper"] = [self.broker.cash, self.broker.base_qty]
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, indent=2)
        os.replace(tmp, self.state_path)

    def bot_equity(self, price: float) -> float:
        unrealized = self.position.qty * price - self.position.cost if self.position else 0.0
        return self.budget + self.realized_pnl + unrealized

    def _exit(self, reason: str):
        fill = self.broker.sell(self.position.qty)
        pnl = self.position.qty * fill * (1 - self.cfg.risk.fee_rate) - self.position.cost
        self.realized_pnl += pnl
        log.info("VENTE %.6f @ %.4f (%s) | PnL estimé %+.2f %s",
                 self.position.qty, fill, reason, pnl, self.broker.quote)
        self.notify(f"{'🟢' if pnl > 0 else '🔴'} VENTE {self.cfg.symbol} ({reason})\n"
                    f"{self.position.qty:.6f} @ {fill:.2f}\n"
                    f"Résultat : {pnl:+.2f} {self.broker.quote}\n"
                    f"Capital du bot : {self.budget + self.realized_pnl:.2f} {self.broker.quote}")
        self.position = None

    # --- commandes à distance (Telegram) ---
    def pause(self):
        with self._lock:
            self.paused = True
            self._save()

    def resume(self):
        with self._lock:
            self.paused = False
            self._save()

    def request_close(self):
        """Vente de la position au prochain cycle (déclenché immédiatement), puis mise en pause."""
        self._close_requested = True
        self._wake.set()

    def status(self) -> str:
        with self._lock:
            q = self.broker.quote
            lines = [f"📊 {self.cfg.symbol} ({self.cfg.timeframe}) - {type(self.broker).__name__}"]
            if self.last_price is not None:
                eq = self.bot_equity(self.last_price)
                lines += [f"Prix : {self.last_price:.2f} {q}",
                          f"Capital du bot : {eq:.2f} {q} ({eq / self.budget - 1:+.2%} sur le budget de {self.budget:.2f})"]
            if self.position:
                p = self.position
                pnl = p.qty * (self.last_price or p.entry_price) - p.cost
                lines += [f"Position : {p.qty:.6f} achetée à {p.entry_price:.2f}",
                          f"  latent {pnl:+.2f} {q} | stop {p.stop:.2f}"
                          + (f" | objectif {p.take_profit:.2f}" if p.take_profit else "")]
            else:
                lines.append("Position : aucune")
            if self.guard.tripped:
                lines.append("⛔ Coupe-circuit déclenché : bot arrêté")
            elif self.paused:
                lines.append("⏸ En pause (aucun nouvel achat)")
            if self.last_analysis:
                lines.append(f"Dernière analyse : {self.last_analysis}")
            return "\n".join(lines)

    def step(self):
        with self._lock:
            self._step()

    def _step(self):
        r = self.cfg.risk
        df = self.broker.candles(self.cfg.timeframe, limit=max(300, self.cfg.strategy.slow_ema * 4))
        closed = df.iloc[:-1]  # la dernière bougie est encore en cours : on l'ignore
        data = generate_signals(closed, self.cfg.strategy)
        last = data.iloc[-1]
        candle_id = str(data.index[-1])
        new_candle = candle_id != self.last_candle
        price = self.broker.price()
        self.last_price = price

        if self._close_requested:
            self._close_requested = False
            self.paused = True  # sinon le bot pourrait racheter aussitôt sur le même signal
            if self.position is not None:
                self._exit("demande manuelle")
                self.notify("⏸ Bot mis en pause. Envoyez /reprendre pour réautoriser les achats.")
            else:
                self.notify("Aucune position à vendre.")

        # 1) Gestion de la position ouverte (à chaque passage)
        if self.position is not None:
            self.position.update_trailing(max(price, float(df["high"].iloc[-1])), float(last["atr"]), r)
            if price <= self.position.stop:
                self._exit("stop-loss")
            elif self.position.take_profit is not None and price >= self.position.take_profit:
                self._exit("take-profit")
            elif new_candle and last["signal"] == SELL:
                self._exit("signal")

        # 2) Coupe-circuit, calculé sur le capital du bot uniquement
        equity = self.bot_equity(price)
        was_tripped = self.guard.tripped
        if self.guard.update(equity):
            if self.position is not None:
                self._exit("coupe-circuit")
            if not was_tripped:
                self.notify(f"⛔ COUPE-CIRCUIT : le bot a perdu {100 * r.max_drawdown:.0f} % de son capital. "
                            "Tout est vendu et le bot ne prendra plus de position.")
            log.warning("COUPE-CIRCUIT actif (redémarrage manuel requis : supprimez le fichier d'état)"
                        " : drawdown >= %.0f %%. Aucune nouvelle position.", 100 * r.max_drawdown)

        # 3) Nouvelle entrée, uniquement sur une bougie nouvellement clôturée
        if new_candle:
            self.last_analysis = explain(last)
            log.info("%s %s", candle_id, self.last_analysis)
            if self.position is None and last["signal"] == BUY and not self.guard.tripped and not self.paused:
                quote, _ = self.broker.balances()
                qty = position_size(min(equity, quote), price * (1 + r.slippage), float(last["atr"]), r)
                qty = self.broker.round_amount(qty)
                if qty > 0 and qty >= self.broker.min_amount:
                    fill = self.broker.buy(qty)
                    self.position = Position.open(qty, fill, float(last["atr"]), r)
                    log.info("ACHAT %.6f @ %.4f | stop %.4f | objectif %s",
                             qty, fill, self.position.stop,
                             f"{self.position.take_profit:.4f}" if self.position.take_profit else "-")
                    self.notify(f"🛒 ACHAT {self.cfg.symbol}\n{qty:.6f} @ {fill:.2f} "
                                f"(≈ {self.position.cost:.2f} {self.broker.quote})\n"
                                f"Stop-loss : {self.position.stop:.2f}\n{self.last_analysis}")
                else:
                    log.info("Signal d'achat ignoré : quantité trop faible (%.8f)", qty)
            self.last_candle = candle_id

        log.debug("Capital : %.2f %s", equity, self.broker.quote)
        self._save()

    def run(self, poll_seconds: int = 60):
        log.info("Démarrage %s %s (%s) - Ctrl+C pour arrêter",
                 type(self.broker).__name__, self.cfg.symbol, self.cfg.timeframe)
        self.notify(f"▶️ Bot démarré : {self.cfg.symbol} ({self.cfg.timeframe}), "
                    f"{type(self.broker).__name__}, budget {self.budget:.2f} {self.broker.quote}. Tapez /aide.")
        errors = 0
        while True:
            try:
                self.step()
                errors = 0
            except KeyboardInterrupt:
                raise
            except Exception as e:  # réseau, API... on log et on réessaie au prochain cycle
                errors += 1
                log.exception("Erreur pendant le cycle, nouvelle tentative au prochain passage")
                if errors in (3, 30) or errors % 300 == 0:  # pas de spam pour une coupure passagère
                    self.notify(f"⚠️ {errors} erreurs de suite (dernière : {e}). Le bot réessaie.")
            self._wake.wait(poll_seconds)
            self._wake.clear()
