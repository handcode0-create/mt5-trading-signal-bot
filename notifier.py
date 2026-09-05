"""
Envoi des signaux de trading vers Telegram.

Responsabilités :
    - formater proprement un signal ;
    - afficher les informations techniques ;
    - afficher les volumes suggérés par position_sizing.py ;
    - envoyer le message au bot Telegram ;
    - gérer les erreurs réseau / API Telegram.

IMPORTANT :
    Ce module n'effectue aucun calcul de taille de position.
    Il affiche uniquement les valeurs calculées en amont.
"""

import logging
from typing import Any

import requests

import config


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION TELEGRAM
# ============================================================

TELEGRAM_API_URL = (
    f"https://api.telegram.org/bot"
    f"{config.TELEGRAM_BOT_TOKEN}/sendMessage"
)

TELEGRAM_TIMEOUT = 10


# ============================================================
# UTILITAIRES
# ============================================================

def _format_number(
    value: Any,
    fallback: str = "N/A",
) -> str:
    """
    Convertit une valeur en texte propre.

    Les valeurs None / invalides deviennent fallback.
    """

    if value is None:
        return fallback

    try:
        text = str(value).strip()

        if not text:
            return fallback

        return text

    except Exception:
        return fallback


def _format_volume(
    volume: Any,
) -> str:
    """
    Formate un volume de lot pour Telegram.

    Exemples :
        0.2   -> 0.20
        0.01  -> 0.01
        None  -> N/A
    """

    if volume is None:
        return "N/A"

    try:
        numeric_volume = float(volume)

        if numeric_volume <= 0:
            return "N/A"

        # On évite les affichages du type :
        # 0.20000000000000001
        return f"{numeric_volume:.2f}"

    except (TypeError, ValueError):
        return "N/A"


def _escape_markdown_v2(text: Any) -> str:
    """
    Échappe les caractères spéciaux nécessaires à Telegram
    lorsque MarkdownV2 est utilisé.

    Telegram MarkdownV2 réserve notamment :
        _ * [ ] ( ) ~ ` > # + - = | { } . !

    Cette fonction permet d'éviter qu'un symbole ou une valeur
    provenant de MT5 casse le formatage du message.
    """

    if text is None:
        return ""

    text = str(text)

    special_characters = (
        "_",
        "*",
        "[",
        "]",
        "(",
        ")",
        "~",
        "`",
        ">",
        "#",
        "+",
        "-",
        "=",
        "|",
        "{",
        "}",
        ".",
        "!",
    )

    for character in special_characters:
        text = text.replace(
            character,
            f"\\{character}",
        )

    return text


def escape_text(text: Any) -> str:
    """
    Version publique de l'échappement MarkdownV2, à utiliser pour tout
    message texte brut envoyé via send_telegram_message() (ex: messages
    de démarrage/arrêt du bot dans main.py), qui ne passe pas par
    format_signal_message() et n'est donc pas déjà échappé.
    """
    return _escape_markdown_v2(text)


def _escape_code(text: Any) -> str:
    """
    Prépare une valeur destinée à être affichée
    dans un bloc inline MarkdownV2.

    Les caractères spéciaux sont échappés.
    """

    return _escape_markdown_v2(text)


# ============================================================
# FORMATAGE DU SIGNAL
# ============================================================

def format_signal_message(signal: dict) -> str:
    """
    Transforme un dictionnaire signal en message Telegram.

    Structure attendue :

        signal = {
            "direction": "ACHAT",
            "symbol": "EURUSDm",
            "timeframe": "M5",
            "price": ...,
            "stop_loss": ...,
            "take_profit": ...,
            "risk_reward": ...,
            "rsi": ...,
            "atr": ...,
            "time": ...,
            "suggested_volumes": {
                1.0: ...,
                2.0: ...
            }
        }
    """

    if not isinstance(signal, dict):
        raise TypeError(
            "Le signal doit être un dictionnaire."
        )

    direction = str(
        signal.get("direction", "")
    ).upper()

    if direction == "ACHAT":
        emoji = "🟢"
        title = "SIGNAL ACHAT"

    elif direction == "VENTE":
        emoji = "🔴"
        title = "SIGNAL VENTE"

    else:
        emoji = "⚪"
        title = "SIGNAL"

    symbol = _format_number(
        signal.get("symbol")
    )

    timeframe = _format_number(
        signal.get("timeframe")
    )

    price = _format_number(
        signal.get("price")
    )

    stop_loss = _format_number(
        signal.get("stop_loss")
    )

    take_profit = _format_number(
        signal.get("take_profit")
    )

    risk_reward = _format_number(
        signal.get("risk_reward")
    )

    rsi = _format_number(
        signal.get("rsi")
    )

    atr = _format_number(
        signal.get("atr")
    )

    candle_time = _format_number(
        signal.get("time")
    )

    pattern = signal.get("pattern")
    pattern_display = pattern if pattern else "Aucun"
    pattern_confluence = signal.get("pattern_confluence", False)
    confluence_display = "✅ confluence" if (pattern and pattern_confluence) else (
        "⚠️ sens opposé" if pattern else ""
    )

    trend_h1 = signal.get("trend_h1")
    trend_display = trend_h1 if trend_h1 else "N/A"

    # --------------------------------------------------------
    # Volumes suggérés
    # --------------------------------------------------------

    volumes = signal.get(
        "suggested_volumes",
        {},
    )

    if not isinstance(volumes, dict):
        volumes = {}

    volume_1 = None
    volume_2 = None

    # Le dictionnaire peut contenir :
    #
    # 1
    # 1.0
    # "1"
    # "1.0"
    #
    # On accepte donc plusieurs représentations.

    for key, value in volumes.items():

        try:
            risk = float(key)

        except (TypeError, ValueError):
            continue

        if math_is_close(risk, 1.0):
            volume_1 = value

        elif math_is_close(risk, 2.0):
            volume_2 = value

    volume_1_display = _format_volume(
        volume_1
    )

    volume_2_display = _format_volume(
        volume_2
    )

    # --------------------------------------------------------
    # Construction du message
    # --------------------------------------------------------

    message = (
        f"{emoji} *{_escape_markdown_v2(title)}*\n"
        f"\n"
        f"📊 *Marché*\n"
        f"• Paire : `{_escape_code(symbol)}`\n"
        f"• Timeframe : `{_escape_code(timeframe)}`\n"
        f"\n"
        f"📍 *Niveaux*\n"
        f"• Entrée : `{_escape_code(price)}`\n"
        f"• 🛑 Stop Loss : `{_escape_code(stop_loss)}`\n"
        f"• 🎯 Take Profit : `{_escape_code(take_profit)}`\n"
        f"• ⚖️ R:R : `1:{_escape_code(risk_reward)}`\n"
        f"\n"
        f"💰 *Gestion du risque*\n"
        f"• Risque 1 % : `{_escape_code(volume_1_display)} lot`\n"
        f"• Risque 2 % : `{_escape_code(volume_2_display)} lot`\n"
        f"\n"
        f"📈 *Indicateurs*\n"
        f"• RSI : `{_escape_code(rsi)}`\n"
        f"• ATR : `{_escape_code(atr)}`\n"
        f"\n"
        f"🕯️ *Pattern*\n"
        f"• Figure : `{_escape_code(pattern_display)}`"
        + (f" {_escape_markdown_v2(confluence_display)}" if confluence_display else "")
        + f"\n"
        f"• Tendance {_escape_code(config.TREND_TIMEFRAME)} : `{_escape_code(trend_display)}`\n"
        f"\n"
        f"🕐 Bougie : `{_escape_code(candle_time)}`\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *Signal algorithmique*\n"
        f"Basé sur EMA {config.EMA_FAST}/"
        f"{config.EMA_SLOW}, RSI et ATR\\.\n"
        f"Les volumes sont des suggestions basées "
        f"sur le solde MT5 au moment du signal\\.\n"
        f"_Vérifie toujours le marché avant toute exécution\\._"
    )

    return message


def math_is_close(
    value: float,
    target: float,
    tolerance: float = 0.000001,
) -> bool:
    """
    Petite comparaison flottante pour les niveaux de risque.

    Exemple :
        1
        1.0
        0.999999999
    """

    return abs(value - target) <= tolerance


# ============================================================
# ENVOI TELEGRAM
# ============================================================

def send_telegram_message(
    text: str,
) -> bool:
    """
    Envoie un message au chat Telegram configuré.

    Retourne :
        True  -> message envoyé
        False -> échec
    """

    if not config.TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN est absent."
        )
        return False

    if not config.TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_CHAT_ID est absent."
        )
        return False

    if not text:
        logger.warning(
            "Tentative d'envoi d'un message Telegram vide."
        )
        return False

    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            TELEGRAM_API_URL,
            data=payload,
            timeout=TELEGRAM_TIMEOUT,
        )

    except requests.Timeout:
        logger.error(
            "Timeout lors de l'envoi du message Telegram."
        )
        return False

    except requests.ConnectionError as exc:
        logger.error(
            "Erreur de connexion à Telegram : %s",
            exc,
        )
        return False

    except requests.RequestException as exc:
        logger.error(
            "Erreur HTTP Telegram : %s",
            exc,
        )
        return False

    except Exception as exc:
        logger.exception(
            "Erreur inattendue Telegram : %s",
            exc,
        )
        return False

    # --------------------------------------------------------
    # Vérification HTTP
    # --------------------------------------------------------

    if response.status_code != 200:
        logger.error(
            "Telegram a retourné HTTP %s : %s",
            response.status_code,
            response.text,
        )
        return False

    # --------------------------------------------------------
    # Vérification JSON Telegram
    # --------------------------------------------------------

    try:
        data = response.json()

    except ValueError:
        logger.error(
            "Réponse Telegram invalide : %s",
            response.text,
        )
        return False

    if not data.get("ok", False):
        logger.error(
            "Telegram a refusé le message : %s",
            data,
        )
        return False

    logger.debug(
        "Message Telegram envoyé avec succès."
    )

    return True


# ============================================================
# NOTIFICATION D'UN SIGNAL
# ============================================================

def notify_signal(
    signal: dict,
) -> bool:
    """
    Formate et envoie un signal vers Telegram.

    Retourne :
        True  -> envoi réussi
        False -> échec
    """

    if not isinstance(signal, dict):
        logger.error(
            "Signal invalide : %s",
            type(signal).__name__,
        )
        return False

    try:
        message = format_signal_message(
            signal
        )

    except Exception as exc:
        logger.exception(
            "Impossible de formater le signal : %s",
            exc,
        )
        return False

    success = send_telegram_message(
        message
    )

    symbol = signal.get(
        "symbol",
        "UNKNOWN",
    )

    direction = signal.get(
        "direction",
        "UNKNOWN",
    )

    if success:
        logger.info(
            "Signal Telegram envoyé : %s %s",
            symbol,
            direction,
        )

    else:
        logger.error(
            "Signal Telegram NON envoyé : %s %s",
            symbol,
            direction,
        )

    return success