"""
Moteur d'analyse technique du bot.

Responsabilités :
    - connexion à MetaTrader 5 ;
    - reconnexion automatique ;
    - récupération des bougies ;
    - calcul EMA, RSI et ATR ;
    - détection des croisements EMA confirmés par le RSI ;
    - calcul dynamique du SL / TP avec l'ATR ;
    - calcul du Risk/Reward ;
    - calcul des tailles de position suggérées.

IMPORTANT :
    Ce module génère uniquement des signaux.
    Il ne place aucun ordre réel sur MT5.
"""

import logging
import math
import time

from typing import Optional

from datetime import datetime, timezone

import MetaTrader5 as mt5
import pandas as pd
import pandas_ta as ta

import config
from position_sizing import suggest_position_sizes
from patterns import detect_pattern, pattern_confluence
from economic_calendar import get_calendar_context
from tradingview_analysis import get_tradingview_context
from fibonacci import compute_fibonacci_levels, nearest_fib_level


logger = logging.getLogger(__name__)


# ============================================================
# TIMEFRAMES MT5
# ============================================================

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


# ============================================================
# CONNEXION MT5
# ============================================================

def connect_mt5() -> bool:
    """
    Initialise la connexion au terminal MetaTrader 5.

    Les identifiants sont récupérés depuis config.py,
    lui-même alimenté par le fichier .env.
    """

    if config.MT5_LOGIN <= 0:
        logger.error(
            "MT5_LOGIN invalide. Vérifie ton fichier .env."
        )
        return False

    if not config.MT5_PASSWORD:
        logger.error(
            "MT5_PASSWORD absent. Vérifie ton fichier .env."
        )
        return False

    if not config.MT5_SERVER:
        logger.error(
            "MT5_SERVER absent. Vérifie ton fichier .env."
        )
        return False

    initialized = mt5.initialize(
        login=config.MT5_LOGIN,
        password=config.MT5_PASSWORD,
        server=config.MT5_SERVER,
    )

    if not initialized:
        logger.error(
            "Échec initialize() MT5 : %s",
            mt5.last_error(),
        )
        return False

    account = mt5.account_info()

    if account is None:
        logger.error(
            "MT5 initialisé mais impossible de récupérer "
            "les informations du compte : %s",
            mt5.last_error(),
        )
        return False

    logger.info(
        "Connecté à MT5 | compte=%s | serveur=%s | "
        "solde=%.2f %s",
        account.login,
        config.MT5_SERVER,
        account.balance,
        account.currency,
    )

    return True


def is_connected() -> bool:
    """
    Vérifie que le terminal MT5 est toujours accessible.
    """

    try:
        terminal = mt5.terminal_info()

        if terminal is None:
            return False

        return True

    except Exception as exc:
        logger.warning(
            "Erreur lors de la vérification MT5 : %s",
            exc,
        )
        return False


def ensure_connection() -> bool:
    """
    Vérifie la connexion MT5.

    Si elle est perdue, plusieurs tentatives de reconnexion
    sont effectuées avant d'abandonner le cycle.
    """

    if is_connected():
        return True

    logger.warning(
        "Connexion MT5 perdue. Tentative de reconnexion..."
    )

    for attempt in range(
        1,
        config.MAX_RECONNECT_ATTEMPTS + 1,
    ):
        try:
            mt5.shutdown()
        except Exception:
            pass

        if connect_mt5():
            logger.info(
                "Reconnexion MT5 réussie "
                "(tentative %d/%d).",
                attempt,
                config.MAX_RECONNECT_ATTEMPTS,
            )
            return True

        logger.warning(
            "Échec reconnexion MT5 "
            "(tentative %d/%d). "
            "Nouvelle tentative dans %ds...",
            attempt,
            config.MAX_RECONNECT_ATTEMPTS,
            config.RECONNECT_WAIT_SECONDS,
        )

        if attempt < config.MAX_RECONNECT_ATTEMPTS:
            time.sleep(config.RECONNECT_WAIT_SECONDS)

    logger.error(
        "Impossible de rétablir la connexion MT5 après %d tentatives.",
        config.MAX_RECONNECT_ATTEMPTS,
    )

    return False


def shutdown_mt5():
    """
    Ferme proprement la connexion MT5.
    """

    try:
        mt5.shutdown()
        logger.info("Connexion MT5 fermée.")

    except Exception as exc:
        logger.warning(
            "Erreur lors de la fermeture MT5 : %s",
            exc,
        )


# ============================================================
# UTILITAIRES SYMBOLES
# ============================================================

def get_symbol_info(symbol: str):
    """
    Retourne les informations MT5 d'un symbole.

    Le symbole est automatiquement activé dans Market Watch
    s'il existe mais n'est pas visible.
    """

    if not symbol:
        logger.warning(
            "Tentative d'accès à un symbole vide."
        )
        return None

    info = mt5.symbol_info(symbol)

    if info is None:
        logger.warning(
            "Symbole '%s' introuvable chez le broker. "
            "Vérifie le nom exact dans Market Watch.",
            symbol,
        )
        return None

    if not info.visible:
        logger.info(
            "Symbole '%s' non visible. Activation dans Market Watch...",
            symbol,
        )

        selected = mt5.symbol_select(
            symbol,
            True,
        )

        if not selected:
            logger.warning(
                "Impossible d'activer le symbole '%s' : %s",
                symbol,
                mt5.last_error(),
            )
            return None

        # Récupération à nouveau des informations après activation.
        info = mt5.symbol_info(symbol)

        if info is None:
            logger.warning(
                "Impossible de récupérer les informations "
                "du symbole '%s' après activation.",
                symbol,
            )
            return None

    unavailable_modes = {
        mt5.SYMBOL_TRADE_MODE_DISABLED,
        mt5.SYMBOL_TRADE_MODE_CLOSEONLY,
    }
    if info.trade_mode in unavailable_modes:
        logger.warning(
            "Symbole '%s' non ouvrable chez le broker (mode=%s), ignoré.",
            symbol, info.trade_mode,
        )
        return None

    return info


def normalize_price(symbol: str, price: float) -> float:
    """
    Arrondit un prix selon le nombre de décimales réel du symbole MT5.

    Exemple :

        EURUSD -> 5 décimales
        USDJPY -> 3 décimales
        XAUUSD -> dépend du broker
    """

    info = mt5.symbol_info(symbol)

    if info is None:
        return round(price, 5)

    digits = int(info.digits)

    return round(price, digits)


# ============================================================
# RÉCUPÉRATION DES BOUGIES
# ============================================================

def fetch_candles(
    symbol: str,
    timeframe: str,
    count: int,
) -> Optional[pd.DataFrame]:
    """
    Récupère les dernières bougies MT5.

    La dernière ligne retournée par MT5 correspond généralement
    à la bougie actuellement en formation.

    Cette fonction récupère les données normalement ; la sélection
    des bougies clôturées est effectuée dans detect_signal().
    """

    if not ensure_connection():
        logger.error(
            "Connexion MT5 indisponible. "
            "Impossible de récupérer %s.",
            symbol,
        )
        return None

    tf = TIMEFRAME_MAP.get(timeframe)

    if tf is None:
        logger.error(
            "Timeframe inconnue : %s",
            timeframe,
        )
        return None

    if count <= 0:
        logger.error(
            "Nombre de bougies invalide : %s",
            count,
        )
        return None

    info = get_symbol_info(symbol)

    if info is None:
        return None

    try:
        rates = mt5.copy_rates_from_pos(
            symbol,
            tf,
            0,
            count,
        )

    except Exception as exc:
        logger.exception(
            "Erreur copy_rates_from_pos() pour %s : %s",
            symbol,
            exc,
        )
        return None

    if rates is None:
        logger.warning(
            "Aucune donnée retournée pour %s (%s) : %s",
            symbol,
            timeframe,
            mt5.last_error(),
        )
        return None

    if len(rates) == 0:
        logger.warning(
            "Aucune bougie disponible pour %s (%s).",
            symbol,
            timeframe,
        )
        return None

    df = pd.DataFrame(rates)

    if df.empty:
        return None

    required_columns = {
        "time",
        "open",
        "high",
        "low",
        "close",
        "tick_volume",
    }

    missing_columns = required_columns.difference(
        df.columns
    )

    if missing_columns:
        logger.warning(
            "Colonnes manquantes pour %s : %s",
            symbol,
            sorted(missing_columns),
        )
        return None

    # Conversion timestamp MT5 -> datetime Python.
    df["time"] = pd.to_datetime(
        df["time"],
        unit="s",
    )

    # Tri chronologique de sécurité.
    df = df.sort_values(
        "time"
    ).reset_index(drop=True)

    logger.debug(
        "%s : %d bougies récupérées sur %s.",
        symbol,
        len(df),
        timeframe,
    )

    return df


# ============================================================
# INDICATEURS
# ============================================================

def compute_indicators(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Ajoute au DataFrame :

        ema_fast
        ema_slow
        rsi
        atr
    """

    df = df.copy()

    df["ema_fast"] = ta.ema(
        df["close"],
        length=config.EMA_FAST,
    )

    df["ema_slow"] = ta.ema(
        df["close"],
        length=config.EMA_SLOW,
    )

    df["rsi"] = ta.rsi(
        df["close"],
        length=config.RSI_PERIOD,
    )

    df["atr"] = ta.atr(
        df["high"],
        df["low"],
        df["close"],
        length=config.ATR_PERIOD,
    )

    return df


# ============================================================
# VALIDATION DES INDICATEURS
# ============================================================

def _valid_indicator_values(
    row: pd.Series,
) -> bool:
    """
    Vérifie que les indicateurs nécessaires existent
    et ne contiennent pas NaN / inf.
    """

    required = (
        "ema_fast",
        "ema_slow",
        "rsi",
        "atr",
    )

    for column in required:
        value = row.get(column)

        if value is None:
            return False

        try:
            value = float(value)
        except (TypeError, ValueError):
            return False

        if not math.isfinite(value):
            return False

    return True


# ============================================================
# FILTRE DE SESSION (heures de forte liquidité)
# ============================================================

def is_within_trading_session() -> bool:
    """
    Vérifie si l'heure actuelle (UTC) est dans la plage de session
    configurée (config.SESSION_START_HOUR_UTC -> SESSION_END_HOUR_UTC).

    Abidjan étant en UTC+0 toute l'année, ces bornes correspondent
    directement à l'heure locale ivoirienne.
    """

    if not config.SESSION_FILTER_ENABLED:
        return True

    current_hour = datetime.now(timezone.utc).hour

    return config.SESSION_START_HOUR_UTC <= current_hour < config.SESSION_END_HOUR_UTC


# ============================================================
# FILTRE DE TENDANCE DE FOND (timeframe supérieure)
# ============================================================

def get_trend_direction(
    symbol: str,
) -> Optional[str]:
    """
    Détermine la tendance de fond sur une timeframe supérieure
    (config.TREND_TIMEFRAME) à partir de la position du prix de
    clôture par rapport à une EMA longue (config.TREND_EMA_PERIOD).

    Retourne "HAUSSIER", "BAISSIER", ou None si indéterminable
    (pas assez de données, ou erreur MT5).
    """

    df = fetch_candles(
        symbol=symbol,
        timeframe=config.TREND_TIMEFRAME,
        count=config.TREND_CANDLES_COUNT,
    )

    if df is None or len(df) < config.TREND_EMA_PERIOD + 3:
        logger.debug(
            "%s : pas assez de données sur %s pour le filtre de tendance.",
            symbol,
            config.TREND_TIMEFRAME,
        )
        return None

    df["trend_ema"] = ta.ema(
        df["close"],
        length=config.TREND_EMA_PERIOD,
    )

    # Dernière bougie clôturée (la dernière ligne est en formation).
    last = df.iloc[-2]

    trend_ema = last.get("trend_ema")
    close = last.get("close")

    if trend_ema is None or close is None:
        return None

    try:
        trend_ema = float(trend_ema)
        close = float(close)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(trend_ema):
        return None

    if close > trend_ema:
        return "HAUSSIER"
    if close < trend_ema:
        return "BAISSIER"

    return None


# ============================================================
# ANALYSE MULTI-TIMEFRAME (confluence informative)
# ============================================================

def get_multi_timeframe_bias(symbol: str) -> dict:
    """
    Calcule le biais EMA9/EMA21 (HAUSSIER si EMA rapide > EMA lente,
    BAISSIER sinon) sur chacune des timeframes de config.MTF_TIMEFRAMES,
    à partir de la dernière bougie CLÔTURÉE de chaque timeframe.

    Retourne un dict {timeframe: "HAUSSIER"|"BAISSIER"|None}. None signifie
    que les données n'étaient pas disponibles ou insuffisantes pour ce
    timeframe (ex: erreur MT5, symbole indisponible sur cette période).
    """
    biases: dict = {}

    for tf in config.MTF_TIMEFRAMES:
        df = fetch_candles(
            symbol=symbol,
            timeframe=tf,
            count=config.CANDLES_COUNT,
        )

        if df is None or len(df) < config.EMA_SLOW + 3:
            biases[tf] = None
            continue

        df["ema_fast"] = ta.ema(df["close"], length=config.EMA_FAST)
        df["ema_slow"] = ta.ema(df["close"], length=config.EMA_SLOW)

        last = df.iloc[-2]
        fast = last.get("ema_fast")
        slow = last.get("ema_slow")

        try:
            fast = float(fast)
            slow = float(slow)
        except (TypeError, ValueError):
            biases[tf] = None
            continue

        if not (math.isfinite(fast) and math.isfinite(slow)):
            biases[tf] = None
            continue

        biases[tf] = "HAUSSIER" if fast > slow else "BAISSIER"

    return biases


def summarize_mtf(biases: dict, direction: str) -> dict:
    """
    Résume l'alignement multi-timeframe par rapport au sens du signal :
    combien de timeframes (parmi celles avec des données valides) vont
    dans le même sens que le signal détecté sur la timeframe principale.
    """
    target_bias = "HAUSSIER" if direction == "ACHAT" else "BAISSIER"

    valid = {tf: bias for tf, bias in biases.items() if bias is not None}
    aligned = sum(1 for bias in valid.values() if bias == target_bias)
    total = len(valid)

    detail = " / ".join(
        f"{tf}:{biases.get(tf) or 'N/A'}" for tf in config.MTF_TIMEFRAMES
    )

    return {
        "mtf_alignment": f"{aligned}/{total}" if total else "N/A",
        "mtf_detail": detail,
    }


# ============================================================
# DÉTECTION DU SIGNAL
# ============================================================

def detect_signal(
    df: pd.DataFrame,
    symbol: str,
) -> Optional[dict]:
    """
    Détecte un signal sur la dernière bougie clôturée.

    Stratégie :

        ACHAT :
            EMA rapide croise EMA lente vers le haut
            ET RSI < seuil de surachat.

        VENTE :
            EMA rapide croise EMA lente vers le bas
            ET RSI > seuil de survente.

    SL / TP :

        SL = ATR × ATR_SL_MULTIPLIER
        TP = ATR × ATR_TP_MULTIPLIER

    La bougie actuellement en formation est ignorée.
    """

    minimum_rows = (
        max(
            config.EMA_SLOW,
            config.RSI_PERIOD,
            config.ATR_PERIOD,
        )
        + 3
    )

    if len(df) < minimum_rows:
        logger.debug(
            "%s : pas assez de bougies (%d/%d).",
            symbol,
            len(df),
            minimum_rows,
        )
        return None

    # --------------------------------------------------------
    # IMPORTANT :
    #
    # df[-1] = bougie actuellement en formation
    # df[-2] = dernière bougie clôturée
    # df[-3] = bougie clôturée précédente
    #
    # Le croisement est donc comparé entre [-3] et [-2].
    # --------------------------------------------------------

    previous = df.iloc[-3]
    last = df.iloc[-2]

    if not _valid_indicator_values(previous):
        logger.debug(
            "%s : indicateurs invalides sur la bougie précédente.",
            symbol,
        )
        return None

    if not _valid_indicator_values(last):
        logger.debug(
            "%s : indicateurs invalides sur la dernière bougie clôturée.",
            symbol,
        )
        return None

    entry = float(last["close"])
    atr = float(last["atr"])
    rsi = float(last["rsi"])

    if entry <= 0:
        logger.warning(
            "%s : prix d'entrée invalide : %s",
            symbol,
            entry,
        )
        return None

    if atr <= 0:
        logger.debug(
            "%s : ATR invalide : %s",
            symbol,
            atr,
        )
        return None

    # --------------------------------------------------------
    # Détection du croisement EMA
    # --------------------------------------------------------

    crossed_up = (
        previous["ema_fast"] <= previous["ema_slow"]
        and
        last["ema_fast"] > last["ema_slow"]
    )

    crossed_down = (
        previous["ema_fast"] >= previous["ema_slow"]
        and
        last["ema_fast"] < last["ema_slow"]
    )

    if not crossed_up and not crossed_down:
        return None

    # --------------------------------------------------------
    # Distances SL / TP
    # --------------------------------------------------------

    sl_multiplier = float(
        config.ATR_SL_MULTIPLIER
    )

    tp_multiplier = float(
        config.ATR_TP_MULTIPLIER
    )

    if sl_multiplier <= 0:
        logger.error(
            "ATR_SL_MULTIPLIER doit être supérieur à 0."
        )
        return None

    if tp_multiplier <= 0:
        logger.error(
            "ATR_TP_MULTIPLIER doit être supérieur à 0."
        )
        return None

    sl_distance = atr * sl_multiplier
    tp_distance = atr * tp_multiplier

    if sl_distance <= 0 or tp_distance <= 0:
        logger.warning(
            "%s : distances SL/TP invalides.",
            symbol,
        )
        return None

    # --------------------------------------------------------
    # Risk / Reward
    # --------------------------------------------------------

    risk_reward = round(
        tp_distance / sl_distance,
        2,
    )

    # --------------------------------------------------------
    # Pattern de chandelier (confluence, n'influence pas la
    # détection du signal, juste une info supplémentaire)
    # --------------------------------------------------------

    pattern = detect_pattern(df)

    # --------------------------------------------------------
    # SIGNAL ACHAT
    # --------------------------------------------------------

    if (
        crossed_up
        and
        rsi < config.RSI_OVERBOUGHT
    ):
        stop_loss = entry - sl_distance
        take_profit = entry + tp_distance

        signal = {
            "direction": "ACHAT",
            "price": normalize_price(
                symbol,
                entry,
            ),
            "rsi": round(
                rsi,
                2,
            ),
            "atr": atr,
            "stop_loss": normalize_price(
                symbol,
                stop_loss,
            ),
            "take_profit": normalize_price(
                symbol,
                take_profit,
            ),
            "risk_reward": risk_reward,
            "time": last["time"],
            "pattern": pattern,
            "pattern_confluence": pattern_confluence(pattern, "ACHAT"),
        }

        logger.info(
            "Signal ACHAT détecté | %s | %s | "
            "entrée=%s | SL=%s | TP=%s | RSI=%.2f | ATR=%s",
            symbol,
            config.TIMEFRAME,
            signal["price"],
            signal["stop_loss"],
            signal["take_profit"],
            signal["rsi"],
            signal["atr"],
        )

        return signal

    # --------------------------------------------------------
    # SIGNAL VENTE
    # --------------------------------------------------------

    if (
        crossed_down
        and
        rsi > config.RSI_OVERSOLD
    ):
        stop_loss = entry + sl_distance
        take_profit = entry - tp_distance

        signal = {
            "direction": "VENTE",
            "price": normalize_price(
                symbol,
                entry,
            ),
            "rsi": round(
                rsi,
                2,
            ),
            "atr": atr,
            "stop_loss": normalize_price(
                symbol,
                stop_loss,
            ),
            "take_profit": normalize_price(
                symbol,
                take_profit,
            ),
            "risk_reward": risk_reward,
            "time": last["time"],
            "pattern": pattern,
            "pattern_confluence": pattern_confluence(pattern, "VENTE"),
        }

        logger.info(
            "Signal VENTE détecté | %s | %s | "
            "entrée=%s | SL=%s | TP=%s | RSI=%.2f | ATR=%s",
            symbol,
            config.TIMEFRAME,
            signal["price"],
            signal["stop_loss"],
            signal["take_profit"],
            signal["rsi"],
            signal["atr"],
        )

        return signal

    return None


# ============================================================
# ANALYSE D'UN SYMBOLE
# ============================================================

def analyze_symbol(
    symbol: str,
) -> Optional[dict]:
    """
    Pipeline complet pour un symbole :

        1. Vérification MT5
        2. Récupération des bougies
        3. Calcul des indicateurs
        4. Détection du signal
        5. Calcul des volumes suggérés
    """

    if not symbol:
        logger.warning(
            "analyze_symbol() appelé avec un symbole vide."
        )
        return None

    # --------------------------------------------------------
    # Filtre de session (évite d'analyser hors des heures de
    # forte liquidité, où les faux signaux sont plus fréquents)
    # --------------------------------------------------------

    if not is_within_trading_session():
        logger.debug(
            "%s : hors session de trading configurée, analyse ignorée.",
            symbol,
        )
        return None

    if not ensure_connection():
        logger.error(
            "Impossible d'analyser %s : MT5 non connecté.",
            symbol,
        )
        return None

    # --------------------------------------------------------
    # Récupération des données
    # --------------------------------------------------------

    df = fetch_candles(
        symbol=symbol,
        timeframe=config.TIMEFRAME,
        count=config.CANDLES_COUNT,
    )

    if df is None:
        return None

    # --------------------------------------------------------
    # Calcul des indicateurs
    # --------------------------------------------------------

    try:
        df = compute_indicators(df)

    except Exception as exc:
        logger.exception(
            "Erreur pendant le calcul des indicateurs "
            "pour %s : %s",
            symbol,
            exc,
        )
        return None

    # --------------------------------------------------------
    # Détection
    # --------------------------------------------------------

    signal = detect_signal(
        df,
        symbol,
    )

    if signal is None:
        return None

    # Le calendrier enrichit le signal mais ne le bloque jamais.
    economic_context = get_calendar_context(symbol)
    signal.update(economic_context)
    if economic_context["economic_bias"] == "NEUTRE":
        signal["economic_alignment"] = "neutre"
    elif (
        economic_context["economic_bias"] == "HAUSSIER"
        and signal["direction"] == "ACHAT"
    ) or (
        economic_context["economic_bias"] == "BAISSIER"
        and signal["direction"] == "VENTE"
    ):
        signal["economic_alignment"] = "favorable"
    else:
        signal["economic_alignment"] = "contraire"

    # NOTE : cet appel doit rester en dehors du bloc if/elif/else
    # ci-dessus — sinon TradingView n'est interrogé que lorsque le
    # biais économique est "contraire", ce qui le rend silencieux
    # dans la majorité des cas (bug corrigé ici).
    signal.update(
        get_tradingview_context(
            symbol,
            config.TIMEFRAME,
            signal["direction"],
        )
    )

    # --------------------------------------------------------
    # Analyse multi-timeframe (informatif, ne bloque jamais)
    # --------------------------------------------------------

    if config.MTF_ENABLED:
        biases = get_multi_timeframe_bias(symbol)
        signal.update(summarize_mtf(biases, signal["direction"]))

    # --------------------------------------------------------
    # Retracements de Fibonacci (informatif, ne bloque jamais)
    # --------------------------------------------------------

    if config.FIBONACCI_ENABLED:
        fib_data = compute_fibonacci_levels(df, config.FIBONACCI_SWING_CANDLES)
        signal.update(
            nearest_fib_level(
                signal["price"],
                fib_data,
                config.FIBONACCI_PROXIMITY_RATIO,
            )
        )

    # --------------------------------------------------------
    # Confluence de pattern obligatoire (optionnel, désactivé
    # par défaut — voir config.REQUIRE_PATTERN_CONFLUENCE)
    # --------------------------------------------------------

    if config.REQUIRE_PATTERN_CONFLUENCE and not signal.get("pattern_confluence"):
        logger.info(
            "%s : signal %s rejeté (pas de confluence de pattern, "
            "pattern=%s).",
            symbol,
            signal["direction"],
            signal.get("pattern"),
        )
        return None

    # --------------------------------------------------------
    # Filtre de tendance de fond (timeframe supérieure)
    # --------------------------------------------------------

    if config.TREND_FILTER_ENABLED:
        trend = get_trend_direction(symbol)

        if trend == "BAISSIER" and signal["direction"] == "ACHAT":
            logger.info(
                "%s : signal ACHAT rejeté, tendance de fond baissière sur %s.",
                symbol,
                config.TREND_TIMEFRAME,
            )
            return None

        if trend == "HAUSSIER" and signal["direction"] == "VENTE":
            logger.info(
                "%s : signal VENTE rejeté, tendance de fond haussière sur %s.",
                symbol,
                config.TREND_TIMEFRAME,
            )
            return None

        signal["trend_h1"] = trend

    # --------------------------------------------------------
    # Informations générales du signal
    # --------------------------------------------------------

    signal["symbol"] = symbol
    signal["timeframe"] = config.TIMEFRAME

    # --------------------------------------------------------
    # Taille de position
    # --------------------------------------------------------

    try:
        suggested_volumes = suggest_position_sizes(
            symbol=symbol,
            entry_price=signal["price"],
            stop_loss=signal["stop_loss"],
        )

    except Exception as exc:
        logger.exception(
            "Erreur pendant le calcul des volumes "
            "pour %s : %s",
            symbol,
            exc,
        )

        suggested_volumes = {
            float(pct): None
            for pct in config.RISK_PERCENT_LEVELS
        }

    signal["suggested_volumes"] = suggested_volumes

    # --------------------------------------------------------
    # Retour final
    # --------------------------------------------------------

    logger.info(
        "Signal prêt | %s %s | volumes=%s",
        symbol,
        signal["direction"],
        suggested_volumes,
    )

    return signal