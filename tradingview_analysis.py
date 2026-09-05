"""Analyse technique TradingView facultative et non bloquante."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import config

logger = logging.getLogger(__name__)

try:
    from tradingview_ta import TA_Handler, Interval
except ImportError:  # Le bot MT5 doit continuer même sans l'extension TradingView.
    TA_Handler = None
    Interval = None

_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
_cache_lock = threading.Lock()

_INTERVALS = {
    "M1": "INTERVAL_1_MINUTE",
    "M5": "INTERVAL_5_MINUTES",
    "M15": "INTERVAL_15_MINUTES",
    "M30": "INTERVAL_30_MINUTES",
    "H1": "INTERVAL_1_HOUR",
    "H4": "INTERVAL_4_HOURS",
    "D1": "INTERVAL_1_DAY",
}


def _default_context(note: str) -> dict[str, Any]:
    return {
        "tradingview_recommendation": "N/A",
        "tradingview_alignment": "N/A",
        "tradingview_oscillators": "N/A",
        "tradingview_moving_averages": "N/A",
        "tradingview_note": note,
    }


def _source(symbol: str) -> tuple[str, str]:
    clean_symbol = symbol.upper().removesuffix("M")
    if clean_symbol.startswith(("XAU", "XAG")):
        return clean_symbol, "cfd"
    if clean_symbol.startswith(("BCH", "BTC", "ETH", "LTC", "XRP", "ADA", "BAT", "LINK")):
        return clean_symbol, "crypto"
    return clean_symbol, "forex"


def get_tradingview_context(symbol: str, timeframe: str, direction: str) -> dict[str, Any]:
    """Retourne le résumé TradingView sans jamais bloquer la génération du signal."""
    if not config.TRADINGVIEW_ENABLED:
        return _default_context("désactivé")
    if TA_Handler is None or Interval is None:
        return _default_context("package tradingview-ta absent")

    interval_name = _INTERVALS.get(timeframe)
    if interval_name is None:
        return _default_context("timeframe non supporté")

    cache_key = (symbol, timeframe)
    now = datetime.now(timezone.utc)
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and (now - cached[0]).total_seconds() < config.TRADINGVIEW_CACHE_SECONDS:
            context = dict(cached[1])
        else:
            tv_symbol, screener = _source(symbol)
            try:
                handler = TA_Handler(
                    symbol=tv_symbol,
                    screener=screener,
                    exchange=(
                        config.TRADINGVIEW_CRYPTO_EXCHANGE
                        if screener == "crypto"
                        else config.TRADINGVIEW_EXCHANGE
                    ),
                    interval=getattr(Interval, interval_name),
                    timeout=config.TRADINGVIEW_TIMEOUT_SECONDS,
                )
                analysis = handler.get_analysis()
                summary = analysis.summary
                context = {
                    "tradingview_recommendation": summary.get("RECOMMENDATION", "N/A"),
                    "tradingview_alignment": "N/A",
                    "tradingview_oscillators": summary.get("BUY", 0),
                    "tradingview_moving_averages": summary.get("SELL", 0),
                    "tradingview_note": "analyse TradingView",
                }
                _cache[cache_key] = (now, context)
            except Exception as exc:
                logger.warning("Analyse TradingView indisponible pour %s: %s", symbol, exc)
                return _default_context("source indisponible")

    recommendation = context["tradingview_recommendation"]
    if recommendation == "BUY":
        context["tradingview_alignment"] = "favorable" if direction == "ACHAT" else "contraire"
    elif recommendation == "SELL":
        context["tradingview_alignment"] = "favorable" if direction == "VENTE" else "contraire"
    else:
        context["tradingview_alignment"] = "neutre"
    return context
