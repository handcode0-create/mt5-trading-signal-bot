"""
Évalue les signaux déjà loggés dans signals_log.csv en comparant le prix
d'entrée au prix actuel du marché.

Un signal n'est évalué que s'il a au moins MIN_HOURS_BEFORE_EVAL heures
d'ancienneté, pour laisser le temps au marché de "confirmer ou infirmer".

Lancement : python evaluate_signals.py
"""

import csv
import logging
from datetime import datetime, timedelta

import MetaTrader5 as mt5

import config
from signal_logger import LOG_FILE, FIELDNAMES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MIN_HOURS_BEFORE_EVAL = 1  # ajusté pour M5 (un signal M5 se joue en dizaines de minutes, pas en 4h)


def get_current_price(symbol: str) -> float | None:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return tick.bid  # prix de vente actuel, référence simple pour comparaison


def evaluate():
    if not mt5.initialize(login=config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER):
        logger.error("Échec connexion MT5 : %s", mt5.last_error())
        return

    rows = []
    try:
        with open(LOG_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        logger.info("Aucun fichier %s trouvé pour l'instant.", LOG_FILE)
        mt5.shutdown()
        return

    updated = 0
    for row in rows:
        if row["result"] != "EN_ATTENTE":
            continue  # déjà évalué

        candle_time = datetime.strptime(row["candle_time"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() - candle_time < timedelta(hours=MIN_HOURS_BEFORE_EVAL):
            continue  # encore trop récent pour juger

        current_price = get_current_price(row["symbol"])
        if current_price is None:
            logger.warning("Impossible de récupérer le prix actuel pour %s", row["symbol"])
            continue

        entry_price = float(row["price_entry"])
        change = current_price - entry_price

        if row["direction"] == "ACHAT":
            result = "GAGNANT" if change > 0 else "PERDANT"
        else:  # VENTE
            result = "GAGNANT" if change < 0 else "PERDANT"

        row["price_after"] = round(current_price, 5)
        row["pips_change"] = round(change, 5)
        row["result"] = result
        updated += 1

    if updated:
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        logger.info("%d signal(aux) évalué(s) et mis à jour dans %s", updated, LOG_FILE)
    else:
        logger.info("Aucun signal à évaluer pour l'instant (soit trop récents, soit déjà traités).")

    # Petit résumé de performance
    evaluated = [r for r in rows if r["result"] in ("GAGNANT", "PERDANT")]
    if evaluated:
        wins = sum(1 for r in evaluated if r["result"] == "GAGNANT")
        total = len(evaluated)
        print(f"\n--- Résumé ---")
        print(f"Signaux évalués : {total}")
        print(f"Gagnants : {wins} ({round(100 * wins / total, 1)}%)")
        print(f"Perdants : {total - wins} ({round(100 * (total - wins) / total, 1)}%)")

    mt5.shutdown()


if __name__ == "__main__":
    evaluate()