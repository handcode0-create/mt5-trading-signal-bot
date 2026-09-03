"""
Logique d'analyse technique.
Connexion à MT5, récupération des bougies, calcul des indicateurs,
détection des signaux de croisement EMA9/EMA21 confirmés par le RSI.
"""

import logging
import time
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd
import pandas_ta as ta

import config
from position_sizing import suggest_position_sizes

logger = logging.getLogger(__name__)

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


def connect_mt5() -> bool:
    """Initialise la connexion au terminal MT5 en s'authentifiant directement."""
    initialized = mt5.initialize(
        login=config.MT5_LOGIN,
        password=config.MT5_PASSWORD,
        server=config.MT5_SERVER,
    )
    if not initialized:
        logger.error("Échec initialize() MT5 : %s", mt5.last_error())
        return False

    logger.info("Connecté à MT5 (compte %s, serveur %s)", config.MT5_LOGIN, config.MT5_SERVER)
    return True


def is_connected() -> bool:
    """Vérifie si la connexion au terminal MT5 est toujours active."""
    return mt5.terminal_info() is not None


def ensure_connection() -> bool:
    """
    Vérifie la connexion avant chaque cycle, et tente de la rétablir si elle est
    tombée (coupure réseau, terminal fermé, etc.), avant d'abandonner.
    """
    if is_connected():
        return True

    logger.warning("Connexion MT5 perdue. Tentative de reconnexion...")
    for attempt in range(1, config.MAX_RECONNECT_ATTEMPTS + 1):
        mt5.shutdown()
        if connect_mt5():
            logger.info("Reconnexion MT5 réussie (tentative %d).", attempt)
            return True
        logger.warning(
            "Échec reconnexion MT5 (tentative %d/%d). Nouvelle tentative dans %ds...",
            attempt, config.MAX_RECONNECT_ATTEMPTS, config.RECONNECT_WAIT_SECONDS,
        )
        time.sleep(config.RECONNECT_WAIT_SECONDS)

    logger.error("Impossible de rétablir la connexion MT5 après %d tentatives.", config.MAX_RECONNECT_ATTEMPTS)
    return False


def shutdown_mt5():
    mt5.shutdown()


def fetch_candles(symbol: str, timeframe: str, count: int) -> pd.DataFrame | None:
    """Récupère les N dernières bougies pour un symbole/timeframe donnés."""
    tf = TIMEFRAME_MAP.get(timeframe)
    if tf is None:
        logger.error("Timeframe inconnue : %s", timeframe)
        return None

    # Le symbole doit être visible dans Market Watch pour que copy_rates fonctionne.
    # On tente de l'activer automatiquement s'il ne l'est pas déjà.
    info = mt5.symbol_info(symbol)
    if info is None:
        logger.warning(
            "Symbole '%s' introuvable chez ce broker. Vérifie le nom exact dans "
            "Market Watch (clic droit > Afficher tout) — certains brokers ajoutent "
            "un suffixe, ex: 'EURUSDm', 'EURUSD.a'.",
            symbol,
        )
        return None
    if not info.visible:
        if not mt5.symbol_select(symbol, True):
            logger.warning("Impossible d'activer le symbole '%s' dans Market Watch.", symbol)
            return None

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        logger.warning("Pas de données pour %s (%s) : %s", symbol, timeframe, mt5.last_error())
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes EMA rapide/lente, RSI et ATR au DataFrame."""
    df = df.copy()
    df["ema_fast"] = ta.ema(df["close"], length=config.EMA_FAST)
    df["ema_slow"] = ta.ema(df["close"], length=config.EMA_SLOW)
    df["rsi"] = ta.rsi(df["close"], length=config.RSI_PERIOD)
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=config.ATR_PERIOD)
    return df


def detect_signal(df: pd.DataFrame) -> dict | None:
    """
    Détecte un croisement EMA sur la dernière bougie clôturée, confirmé par le RSI.
    Le SL/TP est calculé à partir de l'ATR (volatilité réelle de la paire) plutôt
    qu'une distance fixe, pour s'adapter à chaque marché.
    Retourne un dict décrivant le signal, ou None si rien à signaler.
    """
    if len(df) < max(config.EMA_SLOW, config.RSI_PERIOD, config.ATR_PERIOD) + 2:
        return None  # pas assez de données

    # On travaille sur les 2 dernières bougies CLÔTURÉES (on ignore la bougie en cours, la dernière ligne)
    prev = df.iloc[-3]
    last = df.iloc[-2]

    if pd.isna(last["ema_fast"]) or pd.isna(last["ema_slow"]) or pd.isna(last["rsi"]) or pd.isna(last["atr"]):
        return None

    crossed_up = prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"]
    crossed_down = prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"]

    entry = last["close"]
    atr = last["atr"]
    sl_dist = atr * config.ATR_SL_MULTIPLIER
    tp_dist = atr * config.ATR_TP_MULTIPLIER
    risk_reward = round(config.ATR_TP_MULTIPLIER / config.ATR_SL_MULTIPLIER, 2)

    if crossed_up and last["rsi"] < config.RSI_OVERBOUGHT:
        return {
            "direction": "ACHAT",
            "price": entry,
            "rsi": round(last["rsi"], 2),
            "atr": round(atr, 5),
            "stop_loss": round(entry - sl_dist, 5),
            "take_profit": round(entry + tp_dist, 5),
            "risk_reward": risk_reward,
            "time": last["time"],
        }

    if crossed_down and last["rsi"] > config.RSI_OVERSOLD:
        return {
            "direction": "VENTE",
            "price": entry,
            "rsi": round(last["rsi"], 2),
            "atr": round(atr, 5),
            "stop_loss": round(entry + sl_dist, 5),
            "take_profit": round(entry - tp_dist, 5),
            "risk_reward": risk_reward,
            "time": last["time"],
        }

    return None


def analyze_symbol(symbol: str) -> dict | None:
    """Pipeline complet pour un symbole : récupération, calcul, détection."""
    df = fetch_candles(symbol, config.TIMEFRAME, config.CANDLES_COUNT)
    if df is None:
        return None

    df = compute_indicators(df)
    signal = detect_signal(df)

    if signal:
        signal["symbol"] = symbol
        signal["timeframe"] = config.TIMEFRAME
        signal["suggested_volumes"] = suggest_position_sizes(symbol, signal["price"], signal["stop_loss"])

    return signal