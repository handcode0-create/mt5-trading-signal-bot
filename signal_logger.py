"""
Enregistrement de chaque signal détecté dans un fichier CSV,
indépendamment du succès d'envoi Telegram (pour garder un historique fiable
même si Telegram est down).
"""

import csv
import logging
import os
from datetime import datetime

LOG_FILE = "signals_log.csv"
FIELDNAMES = [
    "logged_at",       # heure réelle d'enregistrement par le bot
    "candle_time",     # heure de la bougie qui a généré le signal
    "symbol",
    "timeframe",
    "direction",
    "price_entry",
    "stop_loss",
    "take_profit",
    "risk_reward",
    "atr",
    "volume_1pct",
    "volume_2pct",
    "rsi",
    "price_after",     # rempli plus tard par evaluate_signals.py
    "pips_change",     # rempli plus tard
    "result",          # rempli plus tard : GAGNANT / PERDANT / EN_ATTENTE
]

logger = logging.getLogger(__name__)


def _ensure_file_exists():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def log_signal(signal: dict):
    """Ajoute une ligne au CSV pour le signal détecté."""
    _ensure_file_exists()

    row = {
        "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "candle_time": signal["time"],
        "symbol": signal["symbol"],
        "timeframe": signal["timeframe"],
        "direction": signal["direction"],
        "price_entry": signal["price"],
        "stop_loss": signal["stop_loss"],
        "take_profit": signal["take_profit"],
        "risk_reward": signal["risk_reward"],
        "atr": signal["atr"],
        "volume_1pct": signal.get("suggested_volumes", {}).get(1),
        "volume_2pct": signal.get("suggested_volumes", {}).get(2),
        "rsi": signal["rsi"],
        "price_after": "",
        "pips_change": "",
        "result": "EN_ATTENTE",
    }

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow(row)

    logger.info("Signal loggé dans %s : %s %s", LOG_FILE, signal["symbol"], signal["direction"])