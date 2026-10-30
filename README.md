# TradeBot

Bot de trading automatisé en Python. Il se connecte à votre plateforme d'échange via
[ccxt](https://github.com/ccxt/ccxt) (Binance, Kraken, Coinbase, Bybit, OKX, KuCoin et plus de 100 autres),
analyse le marché, prend les décisions d'achat et de vente et gère le risque à votre place.

**Configuration par défaut : la plus prudente.** Plateforme Kraken, paire BTC/EUR, bougies de 4 h,
0,5 % de risque par trade, coupe-circuit à −10 %, budget plafonné.

> ⚠️ **À lire avant tout**
> - **Aucun logiciel ne peut garantir un rendement positif.** Les marchés sont en grande partie imprévisibles.
>   Sur un marché sans tendance, cette stratégie **perd de l'argent** à cause des frais (testé : −9 % en moyenne
>   sur 20 marchés aléatoires). Elle ne gagne que lorsque de vraies tendances se forment.
> - Les bons résultats d'un backtest ne garantissent pas les résultats futurs.
> - N'engagez que de l'argent que vous pouvez vous permettre de perdre entièrement.
> - Ce projet est un outil, pas un conseil en investissement.

## Pourquoi Kraken

- Plateforme fondée en 2011, **jamais piratée** à ce jour, avec des contrôles réguliers prouvant qu'elle détient bien les fonds de ses clients.
- **Agréée en Europe (MiCA)** et enregistrée auprès de l'AMF en France.
- Dépôts et retraits en **euros** par virement SEPA, d'où la paire BTC/EUR plutôt que BTC/USDT.
- Clés API très fines : on peut autoriser le trading sans autoriser les retraits.

Coinbase est aussi un bon choix (`--exchange coinbase`). Vérifiez vous-même le statut d'une plateforme sur la
liste de l'AMF avant d'y déposer de l'argent : https://www.amf-france.org (rubrique « listes blanches »).

## Les sécurités du bot

| Sécurité | Effet |
|---|---|
| **Budget plafonné** (`--capital`) | Le bot n'utilise jamais plus que cette somme, même si votre compte contient davantage. |
| Risque par trade 0,5 % | Avec 1 000 € de budget, un stop-loss touché coûte environ 5 €. |
| Position max 20 % | Jamais plus de 200 € engagés sur un trade avec 1 000 € de budget. |
| **Coupe-circuit −10 %** | Si le bot perd 10 % de son budget depuis son plus haut, il vend tout et s'arrête. Il ne repart pas sans votre intervention. |
| Stop-loss + stop suiveur | Chaque position est protégée dès l'achat. |
| Achat seulement | Pas d'effet de levier, pas de vente à découvert : impossible de perdre plus que la mise. |
| Confirmation | En réel, le bot affiche un récapitulatif et attend que vous tapiez `OUI`. |
| Clé API sans retrait | Même si la clé était volée, personne ne pourrait retirer votre argent. |

## Fonctionnement

| Module | Rôle |
|---|---|
| `strategy.py` | Suivi de tendance (croisement EMA 20/50) filtré par le RSI : achat seulement si la tendance est haussière et le momentum sain (RSI 50-70) ; sortie au retournement ou en surachat extrême (RSI > 80). |
| `risk.py` | Taille de position, stop-loss à 2×ATR, stop suiveur, objectif à 3× le risque, coupe-circuit. |
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
python -m tradebot backtest --limit 3000 --trades
```

Testez plusieurs actifs et plusieurs unités de temps. Si la stratégie ne bat pas « buy_and_hold » avec un
drawdown acceptable, **ne passez pas en réel**.

### 2. Analyse instantanée

```bash
python -m tradebot analyze --symbol ETH/EUR
```

### 3. Paper trading (argent fictif, plusieurs semaines recommandées)

```bash
python -m tradebot run --capital 1000
```

Kraken ne propose pas de compte de test pour le spot : le paper trading est l'étape de test.

### 4. Réel, avec un petit budget

1. Activez la **double authentification (2FA)** sur votre compte Kraken.
2. Kraken → Paramètres → API → *Créer une clé*. Cochez **uniquement** : *Interroger les fonds*,
   *Interroger les ordres ouverts et clôturés*, *Créer et modifier des ordres*, *Annuler/fermer des ordres*.
   **Ne cochez jamais « Retirer des fonds »** (*Withdraw Funds*). Si vous avez une IP fixe, restreignez la clé à cette IP.
3. `cp .env.example .env` et renseignez la clé (ce fichier n'est jamais envoyé sur GitHub).
4. Lancez avec un budget que vous acceptez de perdre, par exemple 200 € :

```bash
python -m tradebot run --live --capital 200 --i-accept-the-risk
```

Les stops sont surveillés par le bot : il doit **rester allumé** (sur un serveur ou un VPS par exemple) tant
qu'une position est ouverte.

## Options utiles

| Option | Défaut | Description |
|---|---|---|
| `--capital` | `1000` | capital simulé (paper) ou budget maximal du bot (réel) |
| `--risk` | `0.005` | part du capital risquée par trade |
| `--max-drawdown` | `0.10` | seuil du coupe-circuit |
| `--fee` | `0.004` | frais de la plateforme par ordre (Kraken Pro, premier palier) |
| `--timeframe` | `4h` | unité de temps des bougies (`1h`, `4h`, `1d`...) |
| `--poll` | `60` | secondes entre deux vérifications |

Les autres paramètres sont dans `tradebot/config.py`.

## Tests

```bash
python -m pytest
```
