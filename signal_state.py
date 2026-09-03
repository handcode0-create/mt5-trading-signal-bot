"""
Gestion de l'état des signaux déjà traités.

Responsabilités :
    - empêcher l'envoi plusieurs fois du même signal ;
    - mémoriser l'état par symbole ;
    - distinguer une nouvelle bougie d'une ancienne ;
    - conserver l'état après redémarrage du bot ;
    - sauvegarder le fichier JSON de manière robuste.

Un signal est identifié par :

    symbole + bougie + direction

Exemple :
    EURUSDm + 2026-09-03 10:00:00 + ACHAT

IMPORTANT :
    Ce module ne fait aucun calcul technique.
    Il ne communique pas avec MT5.
    Il ne communique pas avec Telegram.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Toujours utiliser le dossier du projet, même si le bot est lancé
# depuis un autre répertoire.
BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "signal_state.json"


def _load_state() -> dict[str, str]:
    """
    Charge l'état sauvegardé.

    Si le fichier n'existe pas ou est invalide, on repart d'un état vide.
    """
    if not STATE_FILE.exists():
        return {}

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            logger.warning(
                "Le fichier %s ne contient pas un objet JSON valide.",
                STATE_FILE,
            )
            return {}

        # On conserve uniquement les paires clé/valeur exploitables.
        state: dict[str, str] = {}

        for symbol, value in data.items():
            if not isinstance(symbol, str):
                continue

            if not isinstance(value, str):
                continue

            symbol = symbol.strip()
            value = value.strip()

            if symbol and value:
                state[symbol] = value

        return state

    except json.JSONDecodeError:
        logger.warning(
            "Fichier %s corrompu, état réinitialisé.",
            STATE_FILE,
        )
        return {}

    except OSError as exc:
        logger.warning(
            "Impossible de lire %s : %s",
            STATE_FILE,
            exc,
        )
        return {}


def _save_state(state: dict[str, str]) -> bool:
    """
    Sauvegarde l'état avec remplacement atomique.

    Le fichier temporaire est écrit complètement avant de remplacer
    l'ancien fichier afin de réduire le risque d'obtenir un JSON
    partiellement écrit en cas d'arrêt brutal.
    """
    temp_file = STATE_FILE.with_name(
        f"{STATE_FILE.stem}.tmp{STATE_FILE.suffix}"
    )

    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        with temp_file.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as file:
            json.dump(
                state,
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_file, STATE_FILE)

        return True

    except OSError as exc:
        logger.exception(
            "Impossible de sauvegarder l'état dans %s : %s",
            STATE_FILE,
            exc,
        )

        try:
            if temp_file.exists():
                temp_file.unlink()
        except OSError:
            pass

        return False


def _normalize_signal(signal: dict[str, Any]) -> tuple[str, str, str] | None:
    """
    Extrait et normalise les informations nécessaires à l'identification
    d'un signal.

    Retourne :
        (symbol, candle_time, direction)

    ou None si le signal est incomplet.
    """
    if not isinstance(signal, dict):
        logger.warning(
            "Signal invalide : type reçu = %s",
            type(signal).__name__,
        )
        return None

    symbol = str(signal.get("symbol", "")).strip()
    candle_time = str(signal.get("time", "")).strip()
    direction = str(signal.get("direction", "")).strip().upper()

    if not symbol:
        logger.warning("Signal ignoré : symbole absent.")
        return None

    if not candle_time:
        logger.warning(
            "Signal ignoré pour %s : heure de bougie absente.",
            symbol,
        )
        return None

    if not direction:
        logger.warning(
            "Signal ignoré pour %s : direction absente.",
            symbol,
        )
        return None

    return symbol, candle_time, direction


def _build_signal_key(candle_time: str, direction: str) -> str:
    """
    Construit la valeur mémorisée pour un symbole.
    """
    return f"{candle_time}|{direction}"


def is_new_signal(signal: dict[str, Any]) -> bool:
    """
    Retourne True si le signal n'a pas encore été traité.

    Un même signal est considéré comme identique lorsqu'il possède :
        - le même symbole ;
        - la même bougie ;
        - la même direction.

    Si le signal est nouveau, son état est immédiatement sauvegardé.

    Exemple :

        Premier appel :
            EURUSDm / 10:00 / ACHAT -> True

        Deuxième appel identique :
            EURUSDm / 10:00 / ACHAT -> False

        Nouvelle bougie :
            EURUSDm / 10:05 / ACHAT -> True

        Même bougie mais direction différente :
            EURUSDm / 10:00 / VENTE -> True
    """
    normalized = _normalize_signal(signal)

    if normalized is None:
        return False

    symbol, candle_time, direction = normalized

    state = _load_state()

    signal_key = _build_signal_key(
        candle_time,
        direction,
    )

    previous_key = state.get(symbol)

    if previous_key == signal_key:
        logger.info(
            "Signal déjà traité : %s | %s | %s",
            symbol,
            candle_time,
            direction,
        )
        return False

    state[symbol] = signal_key

    if not _save_state(state):
        logger.error(
            "État non sauvegardé pour %s. "
            "Le signal sera considéré comme nouveau au prochain appel.",
            symbol,
        )

        # On retourne False pour éviter d'envoyer un signal dont
        # l'état de déduplication n'a pas pu être enregistré.
        return False

    logger.info(
        "Nouveau signal accepté : %s | %s | %s",
        symbol,
        candle_time,
        direction,
    )

    return True


def get_state() -> dict[str, str]:
    """
    Retourne une copie de l'état actuel.

    Utile pour le diagnostic et les tests.
    """
    return _load_state()


def clear_state() -> bool:
    """
    Supprime complètement l'état sauvegardé.

    À utiliser uniquement pour réinitialiser le mécanisme
    anti-duplication.
    """
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()

        logger.info("État des signaux réinitialisé.")

        return True

    except OSError as exc:
        logger.exception(
            "Impossible de supprimer %s : %s",
            STATE_FILE,
            exc,
        )
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logger.info("========================================")
    logger.info("TEST DU GESTIONNAIRE D'ÉTAT")
    logger.info("========================================")
    logger.info("Fichier d'état : %s", STATE_FILE)

    test_signal = {
        "symbol": "TEST_SYMBOL",
        "time": "2026-09-03 14:00:00",
        "direction": "ACHAT",
    }

    logger.info("Test 1 : nouveau signal")
    result_1 = is_new_signal(test_signal)
    logger.info("Résultat : %s", result_1)

    logger.info("Test 2 : même signal")
    result_2 = is_new_signal(test_signal)
    logger.info("Résultat : %s", result_2)

    logger.info("Test 3 : nouvelle bougie")
    new_candle_signal = {
        **test_signal,
        "time": "2026-09-03 14:05:00",
    }
    result_3 = is_new_signal(new_candle_signal)
    logger.info("Résultat : %s", result_3)

    logger.info("Test 4 : même bougie, direction différente")
    opposite_signal = {
        **test_signal,
        "direction": "VENTE",
    }
    result_4 = is_new_signal(opposite_signal)
    logger.info("Résultat : %s", result_4)

    logger.info("État actuel :")
    logger.info("%s", get_state())

    # Nettoyage du signal de test uniquement.
    state = _load_state()

    for symbol in ["TEST_SYMBOL"]:
        state.pop(symbol, None)

    _save_state(state)

    logger.info("Tests terminés.")