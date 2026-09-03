"""
Point d'entrée du bot.
Boucle en continu : pour chaque symbole configuré, analyse et notifie sur Telegram
si un signal est détecté.

Lancement : python main.py
Arrêt propre : Ctrl+C
"""

import logging
import time

import config
from analyzer import connect_mt5, shutdown_mt5, ensure_connection, analyze_symbol
from notifier import notify_signal, send_telegram_message
from signal_logger import log_signal
from signal_state import is_new_signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def run_cycle():
    """Un cycle d'analyse sur tous les symboles configurés."""
    if not ensure_connection():
        logger.error("Cycle ignoré : connexion MT5 indisponible.")
        return

    for symbol in config.SYMBOLS:
        try:
            signal = analyze_symbol(symbol)
            if signal and is_new_signal(signal):
                log_signal(signal)
                notify_signal(signal)
            elif signal:
                logger.info("Signal déjà traité (même bougie) sur %s, ignoré.", symbol)
            else:
                logger.info("Aucun signal sur %s", symbol)
        except Exception as e:
            logger.exception("Erreur pendant l'analyse de %s : %s", symbol, e)


def main():
    if not connect_mt5():
        logger.error("Impossible de se connecter à MT5. Arrêt du bot.")
        return

    send_telegram_message("🤖 Bot de signaux démarré. Surveillance en cours...")
    logger.info("Bot démarré. Symboles surveillés : %s", config.SYMBOLS)

    try:
        while True:
            run_cycle()
            time.sleep(config.CHECK_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Arrêt demandé par l'utilisateur.")
    finally:
        shutdown_mt5()
        send_telegram_message("🛑 Bot de signaux arrêté.")


if __name__ == "__main__":
    main()