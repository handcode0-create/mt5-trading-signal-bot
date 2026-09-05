"""Calendrier ForexFactory et biais indicatif par paire."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

_cache: tuple[datetime, list[dict[str, Any]]] | None = None
_cache_lock = threading.Lock()


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
        for pattern in ("%b %d, %Y %I:%M%p", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(value.strip(), pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _load_events() -> list[dict[str, Any]]:
    global _cache
    now = datetime.now(timezone.utc)
    with _cache_lock:
        if _cache and (now - _cache[0]).total_seconds() < config.ECONOMIC_CALENDAR_CACHE_SECONDS:
            return _cache[1]

    try:
        response = requests.get(config.ECONOMIC_CALENDAR_URL, timeout=8)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Calendrier économique indisponible: %s", exc)
        return []

    events = []
    for raw in payload if isinstance(payload, list) else []:
        event_time = _parse_date(str(raw.get("date", "")))
        country = str(raw.get("country", "")).upper()
        impact = str(raw.get("impact", "")).capitalize()
        if event_time and country and impact in {"High", "Medium"}:
            events.append({
                "time": event_time,
                "country": country,
                "title": str(raw.get("title", "Annonce")),
                "impact": impact,
                "actual": raw.get("actual"),
                "forecast": raw.get("forecast"),
                "previous": raw.get("previous"),
            })

    with _cache_lock:
        _cache = (now, events)
    return events


def _event_score(event: dict[str, Any]) -> float:
    actual = _number(event.get("actual"))
    forecast = _number(event.get("forecast"))
    if actual is None or forecast is None:
        return 0.0
    difference = actual - forecast
    if difference == 0:
        return 0.0
    # Une hausse du chômage/des demandes d'allocation est généralement négative.
    title = event["title"].lower()
    if any(word in title for word in ("unemployment", "jobless", "claims", "layoff")):
        difference = -difference
    return (3.0 if event["impact"] == "High" else 1.0) * (1 if difference > 0 else -1)


def get_calendar_context(symbol: str) -> dict[str, Any]:
    """Retourne un biais indicatif et les annonces proches, sans bloquer le signal."""
    if not config.ECONOMIC_CALENDAR_ENABLED:
        return {"economic_bias": "N/A", "economic_events": [], "economic_note": "désactivé"}

    currencies = symbol.upper().replace("M", "")
    if len(currencies) < 6:
        return {"economic_bias": "N/A", "economic_events": [], "economic_note": "symbole non-forex"}
    base, quote = currencies[:3], currencies[3:6]
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=config.ECONOMIC_CALENDAR_LOOKBACK_HOURS)
    end = now + timedelta(hours=config.ECONOMIC_CALENDAR_LOOKAHEAD_HOURS)
    relevant = [event for event in _load_events() if start <= event["time"] <= end and event["country"] in {base, quote}]

    score = 0.0
    display_events = []
    for event in relevant:
        signed_score = _event_score(event)
        score += signed_score if event["country"] == base else -signed_score
        timing = "à venir" if event["time"] > now else "publiée"
        display_events.append(f"{event['country']} {event['impact']} {event['title']} ({timing})")

    bias = "HAUSSIER" if score > 0 else "BAISSIER" if score < 0 else "NEUTRE"
    return {
        "economic_bias": bias,
        "economic_events": display_events[:3],
        "economic_note": "biais indicatif, non bloquant",
    }
