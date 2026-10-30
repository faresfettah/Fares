"""Pilotage du bot depuis votre téléphone avec Telegram.

Seul le chat dont l'identifiant est TELEGRAM_CHAT_ID peut envoyer des commandes :
les messages de tout autre compte sont ignorés.
"""
import json
import logging
import threading
import urllib.parse
import urllib.request

log = logging.getLogger("tradebot")

HELP = (
    "Commandes :\n"
    "/statut - capital, position, dernière analyse\n"
    "/pause - plus aucun nouvel achat (la position reste protégée par son stop)\n"
    "/reprendre - réautorise les achats\n"
    "/vendre - vend immédiatement la position et met le bot en pause (demande /vendre oui)\n"
    "/aide - cette aide"
)


class Telegram:
    def __init__(self, token: str, chat_id: str, transport=None):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = str(chat_id)
        self._call = transport or self._http
        self._offset = 0

    def _http(self, method: str, params: dict, timeout: float = 35):
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(self.base + method, data=data, timeout=timeout) as resp:
            return json.loads(resp.read())

    def send(self, text: str) -> None:
        try:
            self._call("sendMessage", {"chat_id": self.chat_id, "text": text})
        except Exception as e:  # une notification ratée ne doit jamais arrêter le trading
            log.warning("Envoi Telegram impossible : %s", e)

    def poll_once(self, timeout: int = 30) -> list:
        """Retourne les textes reçus du chat autorisé uniquement."""
        res = self._call("getUpdates", {"offset": self._offset, "timeout": timeout})
        texts = []
        for upd in res.get("result", []):
            self._offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != self.chat_id:
                log.warning("Message Telegram ignoré : chat non autorisé %s", (msg.get("chat") or {}).get("id"))
                continue
            if msg.get("text"):
                texts.append(msg["text"].strip())
        return texts


def handle_command(trader, text: str) -> str:
    cmd, _, arg = text.partition(" ")
    cmd = cmd.lower().split("@")[0]
    if cmd in ("/statut", "/status", "/start"):
        return trader.status()
    if cmd == "/pause":
        trader.pause()
        return "⏸ Pause : aucun nouvel achat. Une position ouverte reste protégée par son stop-loss."
    if cmd in ("/reprendre", "/resume"):
        if trader.guard.tripped:
            return "⛔ Coupe-circuit déclenché : redémarrage manuel nécessaire sur le serveur."
        trader.resume()
        return "▶️ Achats réautorisés."
    if cmd in ("/vendre", "/sell"):
        if trader.position is None:
            return "Aucune position ouverte."
        if arg.strip().lower() != "oui":
            return "Confirmez en envoyant : /vendre oui"
        trader.request_close()
        return "Vente demandée, exécution dans quelques secondes..."
    return HELP


def start_listener(tg: Telegram, trader) -> threading.Thread:
    def loop():
        while True:
            try:
                for text in tg.poll_once():
                    tg.send(handle_command(trader, text))
            except Exception as e:
                log.warning("Réception Telegram : %s", e)
                threading.Event().wait(10)

    t = threading.Thread(target=loop, name="telegram", daemon=True)
    t.start()
    return t


def discover_chat_id(token: str) -> None:
    """Aide à la configuration : affiche l'identifiant du chat après que vous avez écrit au bot."""
    tg = Telegram(token, chat_id="")
    res = tg._call("getUpdates", {"timeout": 0})
    chats = {(u.get("message") or {}).get("chat", {}).get("id"): (u.get("message") or {}).get("chat", {})
             for u in res.get("result", [])}
    chats.pop(None, None)
    if not chats:
        print("Aucun message reçu. Ouvrez votre bot dans Telegram, envoyez-lui « bonjour », puis relancez.")
    for cid, chat in chats.items():
        print(f"TELEGRAM_CHAT_ID={cid}   ({chat.get('first_name', '')} {chat.get('username', '')})")
