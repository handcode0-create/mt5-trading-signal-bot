"""
Calcule les niveaux de retracement de Fibonacci sur les N dernières bougies
clôturées, pour servir de confluence informative avec le signal EMA/RSI
(comme les patterns de chandeliers, mais basé sur des niveaux de prix).

Ne bloque jamais un signal — vient juste enrichir l'information affichée
et loggée. Les niveaux de Fibonacci sont des zones où un rebond ou un rejet
du prix est statistiquement plus fréquent (support/résistance psychologique),
mais ce n'est pas une garantie.
"""

import pandas as pd

FIB_RATIOS = [0.236, 0.382, 0.5, 0.618, 0.786]


def compute_fibonacci_levels(df: pd.DataFrame, lookback: int) -> dict | None:
    """
    Calcule les niveaux de Fibonacci à partir du plus haut et du plus bas
    des `lookback` dernières bougies CLÔTURÉES (la bougie en cours de
    formation, dernière ligne du DataFrame, est exclue — même convention
    que patterns.detect_pattern()).

    Retourne None si pas assez de données ou si le swing est nul (marché
    parfaitement plat, cas dégénéré).
    """
    if len(df) < lookback + 2:
        return None

    window = df.iloc[-(lookback + 1):-1]
    swing_high = float(window["high"].max())
    swing_low = float(window["low"].min())
    swing_range = swing_high - swing_low

    if swing_range <= 0:
        return None

    # Sens du swing : est-ce que le marché est globalement monté (retracement
    # attendu depuis le haut) ou descendu (retracement depuis le bas) sur
    # cette fenêtre ?
    is_uptrend_swing = window["close"].iloc[-1] >= window["close"].iloc[0]

    levels = {}
    for ratio in FIB_RATIOS:
        if is_uptrend_swing:
            levels[ratio] = swing_high - swing_range * ratio
        else:
            levels[ratio] = swing_low + swing_range * ratio

    return {
        "swing_high": swing_high,
        "swing_low": swing_low,
        "swing_range": swing_range,
        "swing_direction": "HAUSSIER" if is_uptrend_swing else "BAISSIER",
        "levels": levels,
    }


def nearest_fib_level(price: float, fib_data: dict | None, proximity_ratio: float) -> dict:
    """
    Retourne le niveau de Fibonacci le plus proche du prix donné, et si
    le prix est "proche" (distance <= proximity_ratio * swing_range).
    """
    if fib_data is None:
        return {
            "fib_level": None,
            "fib_price": None,
            "fib_near": False,
            "fib_note": "swing indisponible",
        }

    swing_range = fib_data["swing_range"]
    tolerance = swing_range * proximity_ratio

    closest_ratio = min(
        fib_data["levels"],
        key=lambda r: abs(fib_data["levels"][r] - price),
    )
    closest_price = fib_data["levels"][closest_ratio]
    distance = abs(closest_price - price)
    is_near = distance <= tolerance

    percent_label = f"{int(round(closest_ratio * 100))}%"

    return {
        "fib_level": percent_label,
        "fib_price": round(closest_price, 5),
        "fib_near": is_near,
        "fib_note": (
            f"proche du niveau {percent_label}"
            if is_near
            else f"niveau le plus proche : {percent_label} (hors tolérance)"
        ),
    }
