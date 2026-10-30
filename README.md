# TradeBot

Bot de trading automatisé en Python. Il se connecte à votre plateforme d'échange via
[ccxt](https://github.com/ccxt/ccxt) (Binance, Kraken, Coinbase, Bybit, OKX, KuCoin et plus de 100 autres),
analyse le marché, prend les décisions d'achat et de vente et gère le risque à votre place.

> ⚠️ **À lire avant tout**
> - **Aucun logiciel ne peut garantir un rendement positif.** Les marchés sont en grande partie imprévisibles.
>   Sur un marché sans tendance, cette stratégie **perd de l'argent** à cause des frais (testé : −9 % en moyenne
>   sur 20 marchés aléatoires). Elle ne gagne que lorsque de vraies tendances se forment.
> - Les bons résultats d'un backtest ne garantissent pas les résultats futurs.
> - N'engagez que de l'argent que vous pouvez vous permettre de perdre entièrement.
> - Ce projet est un outil, pas un conseil en investissement.

## Fonctionnement

| Module | Rôle |
|---|---|
| `strategy.py` | Suivi de tendance (croisement EMA 20/50) filtré par le RSI : achat seulement si la tendance est haussière et le momentum sain (RSI 50-70) ; sortie au retournement ou en surachat extrême (RSI > 80). |
| `risk.py` | Taille de position calculée pour ne risquer que **1 % du capital** par trade, stop-loss à 2×ATR, stop suiveur, objectif à 3× le risque, position plafonnée à 25 % du capital, **coupe-circuit** qui arrête tout si le capital baisse de 20 % depuis son plus haut. |
| `backtest.py` | Simulation sur l'historique, sans biais d'anticipation, avec frais et glissement. Compare le résultat au simple « acheter et garder ». |
| `broker.py` | `PaperBroker` (vraies données de marché, argent fictif) et `LiveBroker` (ordres réels). |
| `live.py` | Boucle continue : analyse à chaque nouvelle bougie, surveillance des stops, état sauvegardé dans un fichier JSON (redémarrage sans perte). |

La stratégie est **uniquement acheteuse** (pas de vente à découvert ni d'effet de levier), ce qui fonctionne sur
n'importe quel compte spot.

## Installation

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

## Utilisation, dans cet ordre

### 1. Backtest sur l'historique réel

```bash
python -m tradebot backtest --exchange binance --symbol BTC/USDT --timeframe 4h --limit 3000 --trades
```

Testez plusieurs actifs et plusieurs unités de temps. Si la stratégie ne bat pas « buy_and_hold » avec un
drawdown acceptable, **ne passez pas en réel**.

### 2. Analyse instantanée

```bash
python -m tradebot analyze --exchange binance --symbol ETH/USDT --timeframe 4h
```

### 3. Paper trading (argent fictif, plusieurs semaines recommandées)

```bash
python -m tradebot run --exchange binance --symbol BTC/USDT --timeframe 4h --capital 1000
```

### 4. Testnet de la plateforme (si disponible), puis réel

1. Sur la plateforme, créez une clé API avec **uniquement** les droits lecture + trading spot.
   **Ne cochez jamais le droit de retrait.** Si possible, limitez la clé à votre adresse IP.
2. `cp .env.example .env` et renseignez la clé.
3. Lancez :

```bash
python -m tradebot run --exchange binance --symbol BTC/USDT --timeframe 4h --live --sandbox --i-accept-the-risk
```

Retirez `--sandbox` pour trader réellement. Commencez avec une petite somme.

Les stops sont surveillés par le bot : il doit **rester allumé** (sur un serveur ou un VPS par exemple) tant
qu'une position est ouverte.

## Options utiles

| Option | Défaut | Description |
|---|---|---|
| `--risk` | `0.01` | part du capital risquée par trade |
| `--max-drawdown` | `0.20` | seuil du coupe-circuit |
| `--fee` | `0.001` | frais de la plateforme par ordre |
| `--timeframe` | `1h` | unité de temps des bougies (`15m`, `1h`, `4h`, `1d`...) |
| `--poll` | `60` | secondes entre deux vérifications |

Les autres paramètres sont dans `tradebot/config.py`.

## Tests

```bash
python -m pytest
```
