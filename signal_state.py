"""
Empêche de renvoyer le même signal plusieurs fois de suite.

Une bougie M15 dure 15 minutes, mais le bot vérifie toutes les CHECK_INTERVAL
secondes (5 min par défaut) : sans mémoire, le même croisement serait détecté
et notifié 2-3 fois avant que la bougie suivante n'arrive. On garde donc en
mémoire (persistée sur disque) la dernière bougie signalée par symbole, et on
ignore un signal si c'est encore la même bougie + la même direction.
"""

import json
import logging
import os

STATE_FILE = "signal_state.json"

logger = logging.getLogger(__name__)


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Fichier %s corrompu, on repart d'un état vide.", STATE_FILE)
        return {}


def _save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def is_new_signal(signal: dict) -> bool:
    """
    Retourne True si ce signal (même symbole + même bougie + même direction)
    n'a pas déjà été traité, et met à jour l'état en conséquence.
    """
    state = _load_state()
    symbol = signal["symbol"]
    candle_key = f"{signal['time']}|{signal['direction']}"

    if state.get(symbol) == candle_key:
        return False  # déjà traité, on ignore

    state[symbol] = candle_key
    _save_state(state)
    return True