from dataclasses import dataclass, field


@dataclass
class StrategyConfig:
    fast_ema: int = 20
    slow_ema: int = 50
    rsi_period: int = 14
    rsi_entry_min: float = 50.0   # momentum haussier confirmé
    rsi_entry_max: float = 70.0   # pas d'achat en zone de surachat
    rsi_exit: float = 80.0        # sortie si surachat extrême
    atr_period: int = 14


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.005     # 0,5 % du capital risqué par trade
    atr_stop_mult: float = 2.0        # stop-loss à 2 x ATR sous le prix d'entrée
    take_profit_r: float = 3.0        # objectif = 3 x le risque (0 = désactivé)
    trailing_stop: bool = True        # le stop remonte avec le prix
    max_position_pct: float = 0.20    # jamais plus de 20 % du capital sur une position
    max_drawdown: float = 0.10        # arrêt total si le capital chute de 10 % depuis son pic
    fee_rate: float = 0.004           # 0,4 % : frais « taker » de Kraken Pro au premier palier
    slippage: float = 0.0005          # 0,05 % de glissement estimé


@dataclass
class BotConfig:
    symbol: str = "BTC/EUR"
    timeframe: str = "4h"           # moins de trades = moins de frais et de bruit
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
