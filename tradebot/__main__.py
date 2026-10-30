"""Interface en ligne de commande.

  python -m tradebot backtest --synthetic
  python -m tradebot backtest --limit 3000
  python -m tradebot analyze  --symbol ETH/EUR
  python -m tradebot run      --capital 1000                                   # paper (argent fictif)
  python -m tradebot run      --live --capital 200 --i-accept-the-risk         # réel, budget plafonné

Par défaut : Kraken, BTC/EUR, bougies de 4h, réglages prudents.
"""
import argparse
import logging
import os
import sys

from .backtest import run_backtest
from .config import BotConfig
from .data import load_csv, synthetic
from .strategy import explain, generate_signals


def _cfg(args) -> BotConfig:
    cfg = BotConfig(symbol=args.symbol, timeframe=args.timeframe)
    cfg.risk.risk_per_trade = args.risk
    cfg.risk.max_drawdown = args.max_drawdown
    cfg.risk.fee_rate = args.fee
    return cfg


def cmd_backtest(args):
    cfg = _cfg(args)
    if args.csv:
        df = load_csv(args.csv)
    elif args.synthetic:
        df = synthetic(n=args.limit)
    else:
        from .broker import make_exchange
        from .data import fetch_ohlcv
        df = fetch_ohlcv(make_exchange(args.exchange), cfg.symbol, cfg.timeframe, args.limit)
    res = run_backtest(df, cfg, initial_capital=args.capital)
    print(f"\nBacktest {cfg.symbol} {cfg.timeframe} : {df.index[0]} -> {df.index[-1]} ({len(df)} bougies)\n")
    for k, v in res.metrics().items():
        print(f"  {k:<22} {v}")
    if args.trades:
        print("\nTrades :")
        for t in res.trades:
            print(f"  {t.entry_time} -> {t.exit_time}  {t.entry_price:.4f} -> {t.exit_price:.4f}"
                  f"  PnL {t.pnl:+.2f}  ({t.reason})")


def cmd_analyze(args):
    from .broker import make_exchange
    from .data import fetch_ohlcv
    cfg = _cfg(args)
    df = fetch_ohlcv(make_exchange(args.exchange), cfg.symbol, cfg.timeframe, 400).iloc[:-1]
    last = generate_signals(df, cfg.strategy).iloc[-1]
    print(f"{cfg.symbol} {cfg.timeframe} @ {df.index[-1]}\n  {explain(last)}")


def cmd_run(args):
    from .broker import LiveBroker, PaperBroker, make_exchange
    from .live import LiveTrader
    cfg = _cfg(args)
    if args.live:
        if not args.i_accept_the_risk:
            sys.exit("Mode réel refusé : ajoutez --i-accept-the-risk après avoir testé en paper trading.")
        ex = make_exchange(args.exchange, with_keys=True, sandbox=args.sandbox)
        broker = LiveBroker(ex, cfg.symbol)
        quote, _ = broker.balances()
        if args.capital > quote:
            sys.exit(f"Budget ({args.capital} {broker.quote}) supérieur au solde disponible ({quote:.2f}).")
        print(f"\n*** MODE RÉEL sur {args.exchange} ***\n"
              f"  Paire              : {cfg.symbol} ({cfg.timeframe})\n"
              f"  Budget du bot      : {args.capital:.2f} {broker.quote} (solde du compte : {quote:.2f})\n"
              f"  Risque par trade   : {100 * cfg.risk.risk_per_trade:.1f} % "
              f"(~{args.capital * cfg.risk.risk_per_trade:.2f} {broker.quote})\n"
              f"  Coupe-circuit      : arrêt si perte de {100 * cfg.risk.max_drawdown:.0f} % "
              f"(~{args.capital * cfg.risk.max_drawdown:.2f} {broker.quote})\n")
        if not args.yes and input("Tapez OUI pour démarrer : ").strip() != "OUI":
            sys.exit("Annulé.")
        state = args.state or "state_live.json"
    else:
        broker = PaperBroker(make_exchange(args.exchange), cfg.symbol, cash=args.capital,
                             fee_rate=cfg.risk.fee_rate, slippage=cfg.risk.slippage)
        state = args.state or "state_paper.json"
    tg = _telegram()
    trader = LiveTrader(broker, cfg, budget=args.capital, state_path=state, notify=tg.send if tg else None)
    if tg:
        from .telegram import start_listener
        start_listener(tg, trader)
        logging.getLogger("tradebot").info("Telegram connecté : pilotage depuis le téléphone actif")
    trader.run(poll_seconds=args.poll)


def _telegram():
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token:
        return None
    if not chat:
        sys.exit("TELEGRAM_CHAT_ID manquant : lancez  python -m tradebot telegram-setup")
    from .telegram import Telegram
    return Telegram(token, chat)


def cmd_telegram_setup(args):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Mettez d'abord TELEGRAM_BOT_TOKEN dans le fichier .env (donné par @BotFather).")
    from .telegram import discover_chat_id
    discover_chat_id(token)


def main(argv=None):
    p = argparse.ArgumentParser(prog="tradebot", description="Bot de trading avec gestion du risque")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        d = BotConfig()
        sp.add_argument("--exchange", default="kraken", help="nom ccxt : kraken, coinbase, bitstamp, binance...")
        sp.add_argument("--symbol", default=d.symbol)
        sp.add_argument("--timeframe", default=d.timeframe)
        sp.add_argument("--capital", type=float, default=1_000.0,
                        help="capital simulé (paper) ou budget MAXIMAL confié au bot (réel)")
        sp.add_argument("--risk", type=float, default=d.risk.risk_per_trade, help="part du capital risquée par trade")
        sp.add_argument("--max-drawdown", type=float, default=d.risk.max_drawdown)
        sp.add_argument("--fee", type=float, default=d.risk.fee_rate)

    b = sub.add_parser("backtest", help="tester la stratégie sur l'historique")
    common(b)
    b.add_argument("--csv")
    b.add_argument("--synthetic", action="store_true", help="données simulées, sans connexion")
    b.add_argument("--limit", type=int, default=2000, help="nombre de bougies")
    b.add_argument("--trades", action="store_true", help="afficher le détail des trades")
    b.set_defaults(func=cmd_backtest)

    a = sub.add_parser("analyze", help="analyse instantanée du marché")
    common(a)
    a.set_defaults(func=cmd_analyze)

    r = sub.add_parser("run", help="trading en continu (paper par défaut)")
    common(r)
    r.add_argument("--live", action="store_true", help="ordres RÉELS")
    r.add_argument("--i-accept-the-risk", action="store_true")
    r.add_argument("--sandbox", action="store_true", help="testnet (si la plateforme en propose un ; pas Kraken spot)")
    r.add_argument("--yes", action="store_true", help="ne pas demander de confirmation (serveur)")
    r.add_argument("--poll", type=int, default=60, help="secondes entre deux vérifications")
    r.add_argument("--state", help="fichier d'état")
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("telegram-setup", help="trouver votre TELEGRAM_CHAT_ID")
    t.set_defaults(func=cmd_telegram_setup)

    args = p.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
