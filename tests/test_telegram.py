from tradebot.broker import PaperBroker
from tradebot.config import BotConfig
from tradebot.data import synthetic
from tradebot.live import LiveTrader
from tradebot.telegram import Telegram, handle_command

from test_live import FakeExchange


def make_trader(tmp_path, sent=None):
    ex = FakeExchange(synthetic(1500))
    trader = LiveTrader(PaperBroker(ex, "BTC/EUR", cash=1_000), BotConfig(), budget=1_000,
                        state_path=str(tmp_path / "s.json"), notify=(sent.append if sent is not None else None))
    return trader, ex


def run_until_position(trader, ex):
    for _ in range(1000):
        trader.step()
        ex.i += 1
        if trader.position is not None:
            return
    raise AssertionError("aucune position ouverte")


def test_only_authorized_chat_is_obeyed():
    updates = {"result": [
        {"update_id": 1, "message": {"chat": {"id": 999}, "text": "/vendre oui"}},   # inconnu
        {"update_id": 2, "message": {"chat": {"id": 42}, "text": "/statut"}},
    ]}
    tg = Telegram("t", "42", transport=lambda m, p: updates if m == "getUpdates" else {})
    assert tg.poll_once() == ["/statut"]
    assert tg._offset == 3


def test_pause_blocks_new_buys(tmp_path):
    trader, ex = make_trader(tmp_path)
    handle_command(trader, "/pause")
    for _ in range(1000):
        trader.step()
        ex.i += 1
    assert trader.position is None
    assert "Achats réautorisés" in handle_command(trader, "/reprendre")


def test_sell_requires_confirmation_and_notifies(tmp_path):
    sent = []
    trader, ex = make_trader(tmp_path, sent)
    run_until_position(trader, ex)
    assert any("ACHAT" in m for m in sent)
    assert "Position :" in handle_command(trader, "/statut")
    assert "/vendre oui" in handle_command(trader, "/vendre")
    assert trader.position is not None
    handle_command(trader, "/vendre oui")
    trader.step()
    assert trader.position is None
    assert trader.paused
    assert any("demande manuelle" in m for m in sent)


def test_notification_failure_never_breaks_trading():
    def boom(method, params):
        raise OSError("réseau coupé")
    Telegram("t", "42", transport=boom).send("test")  # ne doit pas lever d'exception
