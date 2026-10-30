"""Interface en ligne de commande.

  python -m tradebot backtest --synthetic
  python -m tradebot backtest --exchange binance --symbol BTC/USDT --timeframe 4h --limit 3000
  python -m tradebot analyze  --exchange binance --symbol ETH/USDT
  python -m tradebot run      --exchange binance --symbol BTC/USDT --capital 1000          # paper
  python -m tradebot run      --exchange binance --symbol BTC/USDT --live --i-accept-the-risk
"""
import argparse
import logging
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
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        ex = make_exchange(args.exchange, with_keys=True, sandbox=args.sandbox)
        broker = LiveBroker(ex, cfg.symbol)
        state = args.state or "state_live.json"
    else:
        broker = PaperBroker(make_exchange(args.exchange), cfg.symbol, cash=args.capital,
                             fee_rate=cfg.risk.fee_rate, slippage=cfg.risk.slippage)
        state = args.state or "state_paper.json"
    LiveTrader(broker, cfg, state_path=state).run(poll_seconds=args.poll)


def main(argv=None):
    p = argparse.ArgumentParser(prog="tradebot", description="Bot de trading avec gestion du risque")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--exchange", default="binance", help="nom ccxt : binance, kraken, coinbase, bybit, okx...")
        sp.add_argument("--symbol", default="BTC/USDT")
        sp.add_argument("--timeframe", default="1h")
        sp.add_argument("--capital", type=float, default=10_000.0)
        sp.add_argument("--risk", type=float, default=0.01, help="part du capital risquée par trade")
        sp.add_argument("--max-drawdown", type=float, default=0.20)
        sp.add_argument("--fee", type=float, default=0.001)

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
    r.add_argument("--sandbox", action="store_true", help="utiliser le testnet de la plateforme")
    r.add_argument("--poll", type=int, default=60, help="secondes entre deux vérifications")
    r.add_argument("--state", help="fichier d'état")
    r.set_defaults(func=cmd_run)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
