"""
Envoi des signaux détectés vers Telegram.
"""

import logging

import requests

import config

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"


def format_signal_message(signal: dict) -> str:
    emoji = "🟢" if signal["direction"] == "ACHAT" else "🔴"

    volumes = signal.get("suggested_volumes", {})
    volume_lines = ""
    for pct, vol in volumes.items():
        vol_display = vol if vol is not None else "N/A"
        volume_lines += f"💰 Volume ({pct}% risque) : `{vol_display} lot`\n"

    return (
        f"{emoji} *Signal {signal['direction']}*\n"
        f"Paire : `{signal['symbol']}`\n"
        f"Timeframe : `{signal['timeframe']}`\n"
        f"Entrée : `{signal['price']}`\n"
        f"🛑 SL : `{signal['stop_loss']}`\n"
        f"🎯 TP : `{signal['take_profit']}`\n"
        f"⚖️ R:R : `1:{signal['risk_reward']}`\n"
        f"{volume_lines}"
        f"RSI : `{signal['rsi']}`\n"
        f"Heure bougie : `{signal['time']}`\n\n"
        f"_Signal algorithmique basé sur la volatilité (ATR) — pas une garantie de résultat. "
        f"Vérifie toujours avant d'exécuter._"
    )


def send_telegram_message(text: str) -> bool:
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        response = requests.post(TELEGRAM_API_URL, data=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Échec envoi Telegram : %s", e)
        return False


def notify_signal(signal: dict):
    message = format_signal_message(signal)
    success = send_telegram_message(message)
    if success:
        logger.info("Signal envoyé : %s %s", signal["symbol"], signal["direction"])
    else:
        logger.error("Signal NON envoyé : %s %s", signal["symbol"], signal["direction"])