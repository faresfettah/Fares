"""Stratégie de suivi de tendance filtrée par le momentum.

Achat  : EMA rapide > EMA lente (tendance haussière) ET RSI dans [rsi_entry_min, rsi_entry_max].
Sortie : EMA rapide < EMA lente (retournement) OU RSI > rsi_exit (surachat extrême).
Le stop-loss / take-profit sont gérés par le moteur de risque.

Les signaux de la bougie i ne sont calculés qu'avec des données jusqu'à i inclus :
ils doivent être exécutés au plus tôt à l'ouverture de la bougie i+1.
"""
import pandas as pd

from .config import StrategyConfig
from .indicators import atr, ema, rsi

BUY, SELL, HOLD = 1, -1, 0


def compute_indicators(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ema(out["close"], cfg.fast_ema)
    out["ema_slow"] = ema(out["close"], cfg.slow_ema)
    out["rsi"] = rsi(out["close"], cfg.rsi_period)
    out["atr"] = atr(out, cfg.atr_period)
    return out


def generate_signals(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = compute_indicators(df, cfg)
    uptrend = out["ema_fast"] > out["ema_slow"]
    entry = uptrend & out["rsi"].between(cfg.rsi_entry_min, cfg.rsi_entry_max)
    exit_ = (~uptrend) | (out["rsi"] > cfg.rsi_exit)

    signal = pd.Series(HOLD, index=out.index)
    signal[entry] = BUY
    signal[exit_] = SELL
    ready = out[["ema_slow", "rsi", "atr"]].notna().all(axis=1)
    signal[~ready] = HOLD
    out["signal"] = signal
    return out


def explain(row: pd.Series) -> str:
    """Explication lisible de la décision sur une bougie."""
    trend = "haussière" if row["ema_fast"] > row["ema_slow"] else "baissière"
    action = {BUY: "ACHAT", SELL: "SORTIE", HOLD: "ATTENTE"}[int(row["signal"])]
    return (
        f"{action} | prix={row['close']:.4f} tendance={trend} "
        f"RSI={row['rsi']:.1f} ATR={row['atr']:.4f}"
    )
