"""
Calcul de taille de position pour les signaux de trading.

Le volume est calculé à partir de :
    - du solde actuel du compte MT5 ;
    - du pourcentage de risque souhaité ;
    - de la distance réelle entre l'entrée et le Stop Loss ;
    - des spécifications du symbole MT5.

La priorité est donnée à mt5.order_calc_profit(), qui permet à MT5
d'estimer directement la perte monétaire d'un volume donné entre
le prix d'entrée et le Stop Loss.

Un fallback basé sur tick_value / tick_size est utilisé si
order_calc_profit() ne peut pas fournir de résultat.

IMPORTANT :
Ce module calcule uniquement une taille de position suggérée.
Il ne place aucun ordre réel.
"""

import logging
import math
from decimal import Decimal, InvalidOperation

import MetaTrader5 as mt5

import config


logger = logging.getLogger(__name__)


def _get_volume_precision(volume_step: float) -> int:
    """
    Détermine le nombre de décimales nécessaires pour afficher
    correctement un volume en fonction du volume_step du broker.

    Exemples :
        0.1   -> 1
        0.01  -> 2
        0.001 -> 3
        1.0   -> 0
    """
    if volume_step <= 0:
        return 2

    try:
        decimal_step = Decimal(str(volume_step))
        exponent = decimal_step.as_tuple().exponent

        if exponent >= 0:
            return 0

        return abs(exponent)

    except (InvalidOperation, ValueError):
        return 2


def _normalize_volume(
    raw_volume: float,
    volume_min: float,
    volume_max: float,
    volume_step: float,
) -> float | None:
    """
    Adapte un volume brut aux contraintes du broker.

    Le volume est toujours arrondi vers le BAS afin de ne jamais
    augmenter le risque demandé.

    IMPORTANT :
    Si le volume obtenu après arrondi devient inférieur au minimum
    autorisé par le broker, on retourne None plutôt que de forcer
    volume_min, car cela pourrait dépasser le risque souhaité.
    """
    if not all(
        math.isfinite(value)
        for value in (
            raw_volume,
            volume_min,
            volume_max,
            volume_step,
        )
    ):
        logger.warning(
            "Paramètres de volume invalides : raw=%s min=%s max=%s step=%s",
            raw_volume,
            volume_min,
            volume_max,
            volume_step,
        )
        return None

    if raw_volume <= 0:
        return None

    if volume_min <= 0 or volume_max <= 0 or volume_step <= 0:
        logger.warning(
            "Spécifications de volume MT5 invalides : "
            "min=%s max=%s step=%s",
            volume_min,
            volume_max,
            volume_step,
        )
        return None

    if volume_min > volume_max:
        logger.warning(
            "Volume minimum supérieur au maximum : min=%s max=%s",
            volume_min,
            volume_max,
        )
        return None

    # Le broker impose un maximum.
    # Réduire au maximum ne dépasse pas le risque demandé.
    capped_volume = min(raw_volume, volume_max)

    # Arrondi vers le bas au pas du broker.
    steps = math.floor((capped_volume / volume_step) + 1e-12)
    normalized_volume = steps * volume_step

    # Évite les petites erreurs flottantes Python.
    precision = _get_volume_precision(volume_step)
    normalized_volume = round(normalized_volume, precision)

    # Si le volume normalisé est inférieur au minimum du broker,
    # on refuse le trade au lieu de forcer volume_min.
    if normalized_volume < volume_min:
        logger.info(
            "Volume calculé %.8f inférieur au minimum broker %.8f. "
            "Aucun volume suggéré afin de ne pas dépasser le risque.",
            normalized_volume,
            volume_min,
        )
        return None

    # Sécurité finale.
    normalized_volume = min(normalized_volume, volume_max)

    return round(normalized_volume, precision)


def _get_order_type(entry_price: float, stop_loss: float):
    """
    Détermine le type d'ordre à partir de la position du Stop Loss.

    BUY :
        SL < Entry

    SELL :
        SL > Entry

    Retourne :
        mt5.ORDER_TYPE_BUY
        ou
        mt5.ORDER_TYPE_SELL
    """
    if stop_loss < entry_price:
        return mt5.ORDER_TYPE_BUY

    if stop_loss > entry_price:
        return mt5.ORDER_TYPE_SELL

    return None


def _calculate_loss_per_lot_mt5(
    symbol: str,
    entry_price: float,
    stop_loss: float,
) -> float | None:
    """
    Calcule la perte monétaire estimée pour 1 lot entre l'entrée
    et le Stop Loss en utilisant directement MT5.

    order_calc_profit() est privilégié car MT5 connaît les
    spécifications du symbole et la devise du compte.
    """
    order_type = _get_order_type(entry_price, stop_loss)

    if order_type is None:
        logger.warning(
            "Impossible de déterminer BUY/SELL pour %s : "
            "entrée et SL identiques.",
            symbol,
        )
        return None

    try:
        profit = mt5.order_calc_profit(
            order_type,
            symbol,
            1.0,
            entry_price,
            stop_loss,
        )
    except Exception as exc:
        logger.warning(
            "Erreur order_calc_profit() pour %s : %s",
            symbol,
            exc,
        )
        return None

    if profit is None:
        logger.warning(
            "order_calc_profit() ne retourne aucune valeur pour %s. "
            "Fallback tick_value activé.",
            symbol,
        )
        return None

    if not math.isfinite(profit):
        logger.warning(
            "order_calc_profit() retourne une valeur invalide pour %s : %s",
            symbol,
            profit,
        )
        return None

    loss_per_lot = abs(float(profit))

    if loss_per_lot <= 0:
        logger.warning(
            "Perte par lot invalide pour %s : %s",
            symbol,
            loss_per_lot,
        )
        return None

    return loss_per_lot


def _calculate_loss_per_lot_tick(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    info,
) -> float | None:
    """
    Fallback de calcul utilisant les informations tick de MT5.

    Formule :

        distance prix
        ×
        valeur monétaire d'une unité de prix
        =
        perte pour 1 lot

    avec :

        valeur unité prix =
            tick_value / tick_size
    """
    distance = abs(entry_price - stop_loss)

    if distance <= 0:
        return None

    tick_size = float(getattr(info, "trade_tick_size", 0) or 0)

    if tick_size <= 0:
        logger.warning(
            "trade_tick_size invalide pour %s : %s",
            symbol,
            tick_size,
        )
        return None

    # Pour le calcul de perte, on privilégie la valeur tick côté perte
    # lorsqu'elle est disponible.
    tick_value_loss = float(
        getattr(info, "trade_tick_value_loss", 0) or 0
    )

    tick_value = float(
        getattr(info, "trade_tick_value", 0) or 0
    )

    if tick_value_loss > 0:
        effective_tick_value = tick_value_loss
    elif tick_value > 0:
        effective_tick_value = tick_value
    else:
        logger.warning(
            "Aucune valeur tick valide pour %s : "
            "tick_value=%s, tick_value_loss=%s",
            symbol,
            tick_value,
            tick_value_loss,
        )
        return None

    value_per_price_unit = effective_tick_value / tick_size

    loss_per_lot = distance * value_per_price_unit

    if not math.isfinite(loss_per_lot) or loss_per_lot <= 0:
        logger.warning(
            "Perte par lot invalide avec fallback tick pour %s : %s",
            symbol,
            loss_per_lot,
        )
        return None

    return loss_per_lot


def calculate_lot_size(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    risk_percent: float,
) -> float | None:
    """
    Retourne le volume en lots correspondant au risque demandé.

    Paramètres :
        symbol :
            Nom exact du symbole MT5, ex. EURUSDm ou XAUUSDm.

        entry_price :
            Prix d'entrée du signal.

        stop_loss :
            Prix du Stop Loss.

        risk_percent :
            Pourcentage du solde à risquer.
            Exemple :
                1  -> 1 %
                2  -> 2 %

    Retour :
        float :
            volume normalisé selon les contraintes du broker.

        None :
            si le calcul est impossible ou si le volume minimum
            du broker entraînerait un risque supérieur au risque demandé.
    """

    # ---------------------------------------------------------
    # Validation des paramètres
    # ---------------------------------------------------------

    if not symbol:
        logger.warning("Symbole vide pour le calcul de position.")
        return None

    if not math.isfinite(entry_price) or not math.isfinite(stop_loss):
        logger.warning(
            "Prix invalides pour %s : entry=%s SL=%s",
            symbol,
            entry_price,
            stop_loss,
        )
        return None

    if entry_price <= 0 or stop_loss <= 0:
        logger.warning(
            "Prix négatifs ou nuls pour %s : entry=%s SL=%s",
            symbol,
            entry_price,
            stop_loss,
        )
        return None

    if not math.isfinite(risk_percent) or risk_percent <= 0:
        logger.warning(
            "Pourcentage de risque invalide pour %s : %s%%",
            symbol,
            risk_percent,
        )
        return None

    # ---------------------------------------------------------
    # Informations du compte
    # ---------------------------------------------------------

    account = mt5.account_info()

    if account is None:
        logger.warning(
            "Impossible de récupérer les informations du compte MT5."
        )
        return None

    balance = float(account.balance)

    if not math.isfinite(balance) or balance <= 0:
        logger.warning(
            "Solde MT5 invalide : %s",
            balance,
        )
        return None

    # ---------------------------------------------------------
    # Informations du symbole
    # ---------------------------------------------------------

    info = mt5.symbol_info(symbol)

    if info is None:
        logger.warning(
            "Symbole '%s' introuvable pour le calcul de lot.",
            symbol,
        )
        return None

    volume_min = float(getattr(info, "volume_min", 0) or 0)
    volume_max = float(getattr(info, "volume_max", 0) or 0)
    volume_step = float(getattr(info, "volume_step", 0) or 0)

    if volume_min <= 0 or volume_max <= 0 or volume_step <= 0:
        logger.warning(
            "Contraintes de volume invalides pour %s : "
            "min=%s max=%s step=%s",
            symbol,
            volume_min,
            volume_max,
            volume_step,
        )
        return None

    # ---------------------------------------------------------
    # Montant monétaire à risquer
    # ---------------------------------------------------------

    risk_amount = balance * (risk_percent / 100.0)

    if not math.isfinite(risk_amount) or risk_amount <= 0:
        logger.warning(
            "Montant de risque invalide pour %s : %.2f",
            symbol,
            risk_amount,
        )
        return None

    # ---------------------------------------------------------
    # Perte pour 1 lot
    # ---------------------------------------------------------

    loss_per_lot = _calculate_loss_per_lot_mt5(
        symbol,
        entry_price,
        stop_loss,
    )

    # Fallback si order_calc_profit() n'a pas fonctionné.
    if loss_per_lot is None:
        loss_per_lot = _calculate_loss_per_lot_tick(
            symbol,
            entry_price,
            stop_loss,
            info,
        )

    if loss_per_lot is None or loss_per_lot <= 0:
        logger.warning(
            "Impossible de déterminer la perte pour 1 lot sur %s.",
            symbol,
        )
        return None

    # ---------------------------------------------------------
    # Calcul du volume brut
    # ---------------------------------------------------------

    raw_volume = risk_amount / loss_per_lot

    if not math.isfinite(raw_volume) or raw_volume <= 0:
        logger.warning(
            "Volume brut invalide pour %s : %s",
            symbol,
            raw_volume,
        )
        return None

    # ---------------------------------------------------------
    # Normalisation selon le broker
    # ---------------------------------------------------------

    volume = _normalize_volume(
        raw_volume=raw_volume,
        volume_min=volume_min,
        volume_max=volume_max,
        volume_step=volume_step,
    )

    if volume is None:
        logger.info(
            "Aucun volume valide pour %s à %.2f%% de risque. "
            "Balance=%.2f, risque=%.2f, perte/lot=%.2f, "
            "volume brut=%.6f, min=%.6f, step=%.6f, max=%.6f",
            symbol,
            risk_percent,
            balance,
            risk_amount,
            loss_per_lot,
            raw_volume,
            volume_min,
            volume_step,
            volume_max,
        )
        return None

    logger.debug(
        "Sizing %s | risque=%.2f%% | balance=%.2f | "
        "risque=%.2f | perte/lot=%.2f | "
        "raw=%.6f | volume=%.6f",
        symbol,
        risk_percent,
        balance,
        risk_amount,
        loss_per_lot,
        raw_volume,
        volume,
    )

    return volume


def suggest_position_sizes(
    symbol: str,
    entry_price: float,
    stop_loss: float,
) -> dict:
    """
    Retourne les volumes suggérés pour les niveaux de risque
    configurés dans config.RISK_PERCENT_LEVELS.

    Exemple :

        {
            1: 0.20,
            2: 0.40
        }

    Si le volume minimum du broker est incompatible avec le risque
    demandé :

        {
            1: None,
            2: 0.01
        }
    """

    suggestions = {}

    for risk_percent in config.RISK_PERCENT_LEVELS:
        try:
            risk_percent = float(risk_percent)

            volume = calculate_lot_size(
                symbol=symbol,
                entry_price=entry_price,
                stop_loss=stop_loss,
                risk_percent=risk_percent,
            )

            suggestions[risk_percent] = volume

        except (TypeError, ValueError) as exc:
            logger.warning(
                "Niveau de risque invalide '%s' pour %s : %s",
                risk_percent,
                symbol,
                exc,
            )

            suggestions[risk_percent] = None

    return suggestions