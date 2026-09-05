"""
Journalisation des signaux de trading dans un fichier CSV.

Responsabilités :
    - créer automatiquement le fichier CSV ;
    - enregistrer chaque signal détecté ;
    - conserver les volumes suggérés pour 1 % et 2 % de risque ;
    - gérer proprement les valeurs absentes ou invalides ;
    - migrer automatiquement les anciens fichiers CSV ;
    - préparer les colonnes nécessaires à l'évaluation future des signaux.

IMPORTANT :
    Ce module n'envoie aucun message Telegram.
    Il ne place aucun ordre.
    Il enregistre uniquement les signaux produits par analyzer.py.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

LOG_FILE = BASE_DIR / "signals_log.csv"

FIELDNAMES = [
    "logged_at",
    "candle_time",
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
    "pattern",
    "pattern_confluence",
    "trend_h1",
    "mtf_alignment",
    "fib_level",
    "fib_near",
    "price_after",
    "pips_change",
    "result",
]


# ============================================================
# OUTILS DE VALIDATION
# ============================================================

def _safe_value(
    value: Any,
    fallback: str = "",
) -> Any:
    """
    Retourne une valeur exploitable pour le CSV.

    Les valeurs None deviennent une chaîne vide.
    Les chaînes vides deviennent également une chaîne vide.
    """
    if value is None:
        return fallback

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return fallback

        return value

    return value


def _safe_float(
    value: Any,
    fallback: str = "",
) -> Any:
    """
    Convertit une valeur en float lorsque possible.

    Retourne une chaîne vide si la conversion échoue.
    """
    if value is None:
        return fallback

    try:
        return float(value)

    except (TypeError, ValueError):
        return fallback


def _safe_volume(
    value: Any,
) -> Any:
    """
    Nettoie une taille de position avant son enregistrement.

    Aucun arrondi agressif n'est effectué ici afin de conserver
    la précision calculée par position_sizing.py.
    """
    if value is None:
        return ""

    try:
        volume = float(value)

        if volume <= 0:
            return ""

        return volume

    except (TypeError, ValueError):
        return ""


# ============================================================
# CRÉATION DU FICHIER
# ============================================================

def _ensure_file_exists() -> None:
    """
    Crée le fichier CSV avec son en-tête s'il n'existe pas.
    """
    try:
        LOG_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 0:
            return

        with LOG_FILE.open(
            mode="w",
            newline="",
            encoding="utf-8-sig",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=FIELDNAMES,
                extrasaction="ignore",
            )

            writer.writeheader()

        logger.info(
            "Fichier de journalisation créé : %s",
            LOG_FILE,
        )

    except OSError as exc:
        logger.exception(
            "Impossible de créer le fichier de journalisation : %s",
            exc,
        )

        raise


# ============================================================
# VÉRIFICATION DE L'EN-TÊTE
# ============================================================

def _read_csv_header() -> list[str]:
    """
    Lit l'en-tête actuel du fichier CSV.

    Retourne une liste vide si le fichier ne contient pas
    d'en-tête exploitable.
    """
    if not LOG_FILE.exists():
        return []

    try:
        with LOG_FILE.open(
            mode="r",
            newline="",
            encoding="utf-8-sig",
        ) as file:

            reader = csv.reader(file)

            header = next(reader, [])

        return [
            column.strip()
            for column in header
        ]

    except (OSError, csv.Error) as exc:
        logger.warning(
            "Impossible de lire l'en-tête CSV : %s",
            exc,
        )

        return []


def _is_valid_csv_header() -> bool:
    """
    Vérifie si le fichier CSV possède exactement
    la structure actuelle.
    """
    header = _read_csv_header()

    return header == FIELDNAMES


# ============================================================
# MIGRATION DE L'ANCIEN CSV
# ============================================================

def _migrate_csv_file() -> None:
    """
    Migre automatiquement un ancien signals_log.csv
    vers la structure actuelle.

    Les anciennes données sont conservées.

    Les nouvelles colonnes qui n'existaient pas auparavant
    sont ajoutées avec une valeur vide.

    Exemple :

        Ancien :
            logged_at
            candle_time
            symbol
            timeframe
            direction
            price_entry
            rsi
            price_after
            pips_change
            result

        Nouveau :
            logged_at
            candle_time
            symbol
            timeframe
            direction
            price_entry
            stop_loss
            take_profit
            risk_reward
            atr
            volume_1pct
            volume_2pct
            rsi
            pattern
            pattern_confluence
            price_after
            pips_change
            result
    """

    if not LOG_FILE.exists():
        _ensure_file_exists()
        return

    try:
        # ----------------------------------------------------
        # Lecture de l'ancien fichier
        # ----------------------------------------------------

        with LOG_FILE.open(
            mode="r",
            newline="",
            encoding="utf-8-sig",
        ) as file:

            reader = csv.DictReader(file)

            old_fieldnames = reader.fieldnames or []

            rows = list(reader)

        old_fieldnames = [
            field.strip()
            for field in old_fieldnames
        ]

        # ----------------------------------------------------
        # Déjà au bon format
        # ----------------------------------------------------

        if old_fieldnames == FIELDNAMES:
            return

        logger.warning(
            "Ancienne structure CSV détectée."
        )

        logger.info(
            "Migration automatique de %s vers la nouvelle structure.",
            LOG_FILE,
        )

        # ----------------------------------------------------
        # Conversion des anciennes lignes
        # ----------------------------------------------------

        migrated_rows: list[dict[str, Any]] = []

        for old_row in rows:

            new_row = {}

            for field in FIELDNAMES:

                value = old_row.get(field, "")

                if value is None:
                    value = ""

                new_row[field] = value

            migrated_rows.append(new_row)

        # ----------------------------------------------------
        # Fichier temporaire
        # ----------------------------------------------------

        temp_file = LOG_FILE.with_name(
            f"{LOG_FILE.stem}.migration.tmp"
        )

        with temp_file.open(
            mode="w",
            newline="",
            encoding="utf-8-sig",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=FIELDNAMES,
                extrasaction="ignore",
            )

            writer.writeheader()

            writer.writerows(migrated_rows)

        # ----------------------------------------------------
        # Remplacement de l'ancien fichier
        # ----------------------------------------------------

        os.replace(
            temp_file,
            LOG_FILE,
        )

        logger.info(
            "Migration CSV terminée avec succès."
        )

        logger.info(
            "%s signal(s) historique(s) conservé(s).",
            len(migrated_rows),
        )

    except (OSError, csv.Error) as exc:

        logger.exception(
            "Échec de la migration du fichier CSV : %s",
            exc,
        )

        raise


# ============================================================
# PRÉPARATION DU CSV
# ============================================================

def _prepare_csv_file() -> None:
    """
    Prépare le fichier CSV avant toute lecture ou écriture.

    Fonctionnement :

        1. Le fichier n'existe pas :
           -> création automatique.

        2. Le fichier existe et possède le bon format :
           -> aucune modification.

        3. Le fichier existe avec un ancien format :
           -> migration automatique.

        4. Après migration :
           -> vérification de la nouvelle structure.
    """

    # --------------------------------------------------------
    # Fichier inexistant ou vide
    # --------------------------------------------------------

    if (
        not LOG_FILE.exists()
        or LOG_FILE.stat().st_size == 0
    ):
        _ensure_file_exists()
        return

    # --------------------------------------------------------
    # Format déjà correct
    # --------------------------------------------------------

    if _is_valid_csv_header():
        return

    # --------------------------------------------------------
    # Ancien format -> migration
    # --------------------------------------------------------

    _migrate_csv_file()

    # --------------------------------------------------------
    # Vérification finale
    # --------------------------------------------------------

    if not _is_valid_csv_header():

        raise RuntimeError(
            "Impossible de valider la structure de "
            "signals_log.csv après migration."
        )


# ============================================================
# EXTRACTION DES VOLUMES
# ============================================================

def _get_suggested_volume(
    signal: dict[str, Any],
    risk_percent: float,
) -> Any:
    """
    Récupère le volume correspondant au niveau de risque demandé.

    Compatible avec les clés :

        1
        1.0
        "1"
        "1.0"

    Cela évite les problèmes liés au type des clés
    du dictionnaire suggested_volumes.
    """

    volumes = signal.get(
        "suggested_volumes",
        {},
    )

    if not isinstance(volumes, dict):
        return ""

    for key, value in volumes.items():

        try:

            if abs(
                float(key) - risk_percent
            ) < 0.000001:

                return _safe_volume(value)

        except (TypeError, ValueError):
            continue

    return ""


# ============================================================
# CONSTRUCTION D'UNE LIGNE CSV
# ============================================================

def _build_row(
    signal: dict[str, Any],
) -> dict[str, Any]:
    """
    Transforme un signal produit par analyzer.py
    en ligne compatible avec signals_log.csv.
    """

    if not isinstance(signal, dict):
        raise TypeError(
            "Le signal doit être un dictionnaire."
        )

    # --------------------------------------------------------
    # Direction
    # --------------------------------------------------------

    direction = str(
        signal.get(
            "direction",
            "",
        )
    ).upper().strip()

    if direction not in {
        "ACHAT",
        "VENTE",
    }:

        logger.warning(
            "Direction inhabituelle dans le signal : %s",
            direction or "VIDE",
        )

    # --------------------------------------------------------
    # Timestamp UTC
    # --------------------------------------------------------

    now_utc = datetime.now(
        timezone.utc
    )

    logged_at = now_utc.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # --------------------------------------------------------
    # Construction de la ligne
    # --------------------------------------------------------

    row = {

        "logged_at": logged_at,

        "candle_time": _safe_value(
            signal.get("time")
        ),

        "symbol": _safe_value(
            signal.get("symbol")
        ),

        "timeframe": _safe_value(
            signal.get("timeframe")
        ),

        "direction": direction,

        "price_entry": _safe_float(
            signal.get("price")
        ),

        "stop_loss": _safe_float(
            signal.get("stop_loss")
        ),

        "take_profit": _safe_float(
            signal.get("take_profit")
        ),

        "risk_reward": _safe_float(
            signal.get("risk_reward")
        ),

        "atr": _safe_float(
            signal.get("atr")
        ),

        "volume_1pct": _get_suggested_volume(
            signal,
            1.0,
        ),

        "volume_2pct": _get_suggested_volume(
            signal,
            2.0,
        ),

        "rsi": _safe_float(
            signal.get("rsi")
        ),

        "pattern": _safe_value(
            signal.get("pattern")
        ),

        "pattern_confluence": bool(
            signal.get("pattern_confluence", False)
        ),

        "trend_h1": _safe_value(
            signal.get("trend_h1")
        ),

        "mtf_alignment": _safe_value(
            signal.get("mtf_alignment")
        ),

        "fib_level": _safe_value(
            signal.get("fib_level")
        ),

        "fib_near": bool(
            signal.get("fib_near", False)
        ),

        # Ces valeurs seront renseignées plus tard
        # par le système d'évaluation.
        "price_after": "",

        "pips_change": "",

        "result": "EN_ATTENTE",
    }

    return row


# ============================================================
# ENREGISTREMENT D'UN SIGNAL
# ============================================================

def log_signal(
    signal: dict[str, Any],
) -> bool:
    """
    Enregistre un signal dans signals_log.csv.

    Retourne :

        True
            si l'écriture est réussie.

        False
            si une erreur survient.
    """

    try:

        # ----------------------------------------------------
        # Validation
        # ----------------------------------------------------

        if not isinstance(signal, dict):

            logger.error(
                "Impossible de journaliser un signal de type %s.",
                type(signal).__name__,
            )

            return False

        # ----------------------------------------------------
        # Préparation du fichier
        # ----------------------------------------------------

        _prepare_csv_file()

        # ----------------------------------------------------
        # Construction de la ligne
        # ----------------------------------------------------

        row = _build_row(signal)

        # ----------------------------------------------------
        # Écriture
        # ----------------------------------------------------

        with LOG_FILE.open(
            mode="a",
            newline="",
            encoding="utf-8-sig",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=FIELDNAMES,
                extrasaction="ignore",
            )

            writer.writerow(row)

            file.flush()

        # ----------------------------------------------------
        # Log
        # ----------------------------------------------------

        logger.info(
            "Signal enregistré : %s %s | entrée=%s | SL=%s | TP=%s",
            row["symbol"],
            row["direction"],
            row["price_entry"],
            row["stop_loss"],
            row["take_profit"],
        )

        return True

    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:

        logger.exception(
            "Erreur lors de l'enregistrement du signal : %s",
            exc,
        )

        return False

    except Exception as exc:

        logger.exception(
            "Erreur inattendue dans signal_logger.py : %s",
            exc,
        )

        return False


# ============================================================
# LECTURE DES SIGNAUX
# ============================================================

def read_signals() -> list[dict[str, Any]]:
    """
    Retourne tous les signaux présents dans le fichier CSV.

    Cette fonction sera notamment utilisée par le système
    d'évaluation des signaux et le backtest.
    """

    try:

        _prepare_csv_file()

        with LOG_FILE.open(
            mode="r",
            newline="",
            encoding="utf-8-sig",
        ) as file:

            reader = csv.DictReader(file)

            return list(reader)

    except (
        OSError,
        RuntimeError,
        csv.Error,
    ) as exc:

        logger.exception(
            "Impossible de lire les signaux : %s",
            exc,
        )

        return []


# ============================================================
# NOMBRE TOTAL DE SIGNAUX
# ============================================================

def get_signal_count() -> int:
    """
    Retourne le nombre total de signaux enregistrés.
    """

    signals = read_signals()

    return len(signals)


# ============================================================
# SIGNAUX EN ATTENTE
# ============================================================

def get_pending_signal_count() -> int:
    """
    Retourne le nombre de signaux qui n'ont pas encore
    été évalués.
    """

    signals = read_signals()

    return sum(
        1
        for signal in signals
        if str(
            signal.get(
                "result",
                "",
            )
        ).upper()
        == "EN_ATTENTE"
    )


# ============================================================
# STATISTIQUES DES RÉSULTATS
# ============================================================

def get_result_counts() -> dict[str, int]:
    """
    Retourne un résumé des résultats enregistrés.

    Exemple :

        {
            "EN_ATTENTE": 12,
            "TP": 8,
            "SL": 5
        }
    """

    signals = read_signals()

    results: dict[str, int] = {}

    for signal in signals:

        result = str(
            signal.get(
                "result",
                "",
            )
        ).strip().upper()

        if not result:
            result = "INCONNU"

        results[result] = (
            results.get(result, 0) + 1
        )

    return results


# ============================================================
# TEST DU MODULE
# ============================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "[%(levelname)s] "
            "%(message)s"
        ),
    )

    try:

        # ----------------------------------------------------
        # Préparation
        # ----------------------------------------------------

        _prepare_csv_file()

        logger.info(
            "========================================"
        )

        logger.info(
            "Logger CSV opérationnel."
        )

        logger.info(
            "========================================"
        )

        logger.info(
            "Fichier : %s",
            LOG_FILE,
        )

        logger.info(
            "Nombre total de signaux : %s",
            get_signal_count(),
        )

        logger.info(
            "Signaux en attente : %s",
            get_pending_signal_count(),
        )

        logger.info(
            "Résultats : %s",
            get_result_counts(),
        )

        logger.info(
            "========================================"
        )

    except Exception as exc:

        logger.exception(
            "Test du signal_logger échoué : %s",
            exc,
        )