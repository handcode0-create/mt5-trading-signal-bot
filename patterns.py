"""
Détection de figures de chandeliers japonais (candlestick patterns) sur les
bougies clôturées, pour servir de confluence avec le signal EMA/RSI.

Ne génère aucun signal à lui seul : sert uniquement à enrichir le signal
EMA+RSI existant (ex: "Marteau" détecté sur un signal ACHAT = confluence forte).
"""

import pandas as pd

# Seuils utilisés pour qualifier un "petit corps" ou une "longue mèche",
# exprimés en fraction du range total de la bougie (high - low).
DOJI_BODY_MAX_RATIO = 0.1        # corps <= 10% du range = doji
SMALL_BODY_MAX_RATIO = 0.35      # corps <= 35% du range = "petit corps" (marteau/étoile)
LONG_WICK_MIN_RATIO = 2.0        # mèche >= 2x le corps = "longue mèche"


def _candle_metrics(candle: pd.Series) -> dict:
    body = abs(candle["close"] - candle["open"])
    candle_range = candle["high"] - candle["low"]
    upper_wick = candle["high"] - max(candle["close"], candle["open"])
    lower_wick = min(candle["close"], candle["open"]) - candle["low"]
    return {
        "body": body,
        "range": candle_range,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "bullish": candle["close"] > candle["open"],
    }


def _is_doji(m: dict) -> bool:
    if m["range"] <= 0:
        return False
    return (m["body"] / m["range"]) <= DOJI_BODY_MAX_RATIO


def _is_hammer(m: dict) -> bool:
    """Petit corps en haut, longue mèche basse, mèche haute quasi nulle."""
    if m["range"] <= 0 or m["body"] <= 0:
        return False
    small_body = (m["body"] / m["range"]) <= SMALL_BODY_MAX_RATIO
    long_lower_wick = m["lower_wick"] >= LONG_WICK_MIN_RATIO * m["body"]
    # Tolérance 1.05x pour absorber les arrondis flottants proches de l'égalité.
    small_upper_wick = m["upper_wick"] <= m["body"] * 1.05
    return small_body and long_lower_wick and small_upper_wick


def _is_shooting_star(m: dict) -> bool:
    """Petit corps en bas, longue mèche haute, mèche basse quasi nulle."""
    if m["range"] <= 0 or m["body"] <= 0:
        return False
    small_body = (m["body"] / m["range"]) <= SMALL_BODY_MAX_RATIO
    long_upper_wick = m["upper_wick"] >= LONG_WICK_MIN_RATIO * m["body"]
    small_lower_wick = m["lower_wick"] <= m["body"] * 1.05
    return small_body and long_upper_wick and small_lower_wick


def _is_bullish_engulfing(prev: pd.Series, last: pd.Series) -> bool:
    prev_bearish = prev["close"] < prev["open"]
    last_bullish = last["close"] > last["open"]
    engulfs = last["open"] <= prev["close"] and last["close"] >= prev["open"]
    return prev_bearish and last_bullish and engulfs


def _is_bearish_engulfing(prev: pd.Series, last: pd.Series) -> bool:
    prev_bullish = prev["close"] > prev["open"]
    last_bearish = last["close"] < last["open"]
    engulfs = last["open"] >= prev["close"] and last["close"] <= prev["open"]
    return prev_bullish and last_bearish and engulfs


def detect_pattern(df: pd.DataFrame) -> str | None:
    """
    Détecte un pattern de chandelier sur la dernière bougie CLÔTURÉE (avant-dernière
    ligne du DataFrame, la dernière étant la bougie en cours de formation).
    Retourne le nom du pattern (str) ou None si aucun pattern reconnu.
    Priorité : engulfing (2 bougies, signal le plus fiable) > marteau/étoile > doji.
    """
    if len(df) < 3:
        return None

    prev = df.iloc[-3]
    last = df.iloc[-2]
    m_last = _candle_metrics(last)

    if _is_bullish_engulfing(prev, last):
        return "Engulfing haussier"
    if _is_bearish_engulfing(prev, last):
        return "Engulfing baissier"
    # Marteau/étoile filante d'abord : ce sont des cas plus spécifiques (mèche
    # très asymétrique) qu'un doji générique. Un marteau a aussi un corps
    # minuscule, donc il satisferait le test du doji s'il était vérifié en
    # premier — l'asymétrie de mèche doit avoir priorité.
    if _is_hammer(m_last):
        return "Marteau"
    if _is_shooting_star(m_last):
        return "Étoile filante"
    if _is_doji(m_last):
        return "Doji"

    return None


def detect_pattern_at(df: pd.DataFrame, index: int) -> str | None:
    """Détecte le pattern formé par la bougie à ``index`` sans regarder le futur."""
    if index < 1 or index >= len(df):
        return None

    previous = df.iloc[index - 1]
    last = df.iloc[index]
    metrics = _candle_metrics(last)

    if _is_bullish_engulfing(previous, last):
        return "Engulfing haussier"
    if _is_bearish_engulfing(previous, last):
        return "Engulfing baissier"
    if _is_hammer(metrics):
        return "Marteau"
    if _is_shooting_star(metrics):
        return "Étoile filante"
    if _is_doji(metrics):
        return "Doji"

    return None


# Pattern haussiers vs baissiers, pour savoir si le pattern confirme ou contredit
# le sens du signal EMA/RSI (utile pour juger de la "confluence").
BULLISH_PATTERNS = {"Marteau", "Engulfing haussier"}
BEARISH_PATTERNS = {"Étoile filante", "Engulfing baissier"}


def pattern_confluence(pattern: str | None, direction: str) -> bool:
    """
    True si le pattern détecté va dans le même sens que le signal EMA/RSI
    (ex: Marteau + ACHAT = confluence). Un Doji ou aucun pattern ne compte
    jamais comme confluence (indécision ou absence de figure).
    """
    if pattern is None:
        return False
    if direction == "ACHAT":
        return pattern in BULLISH_PATTERNS
    if direction == "VENTE":
        return pattern in BEARISH_PATTERNS
    return False
