"""
Calcule la taille de position (en lots) à partir :
- du solde actuel du compte MT5
- du pourcentage de risque souhaité (1% et 2% par défaut)
- de la distance réelle entre le prix d'entrée et le Stop Loss

Utilise les infos symbole de MT5 (tick_value, tick_size, volume_step/min/max)
pour rester correct quel que soit l'actif (forex, or, argent, crypto...).
"""

import logging
import math

import MetaTrader5 as mt5

import config

logger = logging.getLogger(__name__)


def calculate_lot_size(symbol: str, entry_price: float, stop_loss: float, risk_percent: float) -> float | None:
    """Retourne le volume (en lots) à utiliser pour risquer risk_percent% du solde sur ce trade."""
    account = mt5.account_info()
    if account is None:
        logger.warning("Impossible de récupérer les infos du compte MT5.")
        return None

    info = mt5.symbol_info(symbol)
    if info is None:
        logger.warning("Symbole '%s' introuvable pour le calcul de lot.", symbol)
        return None

    distance = abs(entry_price - stop_loss)
    if distance == 0 or info.trade_tick_size == 0:
        return None

    # Valeur monétaire d'un déplacement de 1 unité de prix, pour 1 lot
    value_per_price_unit = info.trade_tick_value / info.trade_tick_size
    loss_per_lot = distance * value_per_price_unit
    if loss_per_lot <= 0:
        return None

    risk_amount = account.balance * (risk_percent / 100)
    raw_volume = risk_amount / loss_per_lot

    # On arrondit VERS LE BAS au pas de volume autorisé par le broker (jamais au-dessus du risque voulu)
    step = info.volume_step
    volume = math.floor(raw_volume / step) * step
    volume = max(info.volume_min, min(volume, info.volume_max))

    return round(volume, 2)


def suggest_position_sizes(symbol: str, entry_price: float, stop_loss: float) -> dict:
    """Retourne les volumes suggérés pour les niveaux de risque configurés (1% et 2% par défaut)."""
    suggestions = {}
    for pct in config.RISK_PERCENT_LEVELS:
        volume = calculate_lot_size(symbol, entry_price, stop_loss, pct)
        suggestions[pct] = volume
    return suggestions