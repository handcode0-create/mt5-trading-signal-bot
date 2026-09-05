"""
Configuration du bot.
Ne mets JAMAIS tes vrais identifiants directement dans ce fichier si tu le push sur GitHub.
Utilise un fichier .env (voir .env.example) et python-dotenv.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Identifiants MT5 (compte Exness) ---
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")  # ex: "Exness-MT5Trial8"

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # ton chat_id perso ou celui d'un groupe

# --- Paramètres de trading ---
SYMBOLS = [
    "EURUSDm",
    "GBPUSDm",
    "USDJPYm",
    "USDCHFm",
    "USDCADm",
    "AUDUSDm",
    "NZDUSDm",
    "EURGBPm",
    "EURJPYm",
    "GBPJPYm",
    "XAUUSDm",  # or
    "XAGUSDm",  # argent
]  # paires à surveiller
TIMEFRAME = "M5"  # M1, M5, M15, M30, H1, H4, D1

EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# --- ATR (volatilité) pour un SL/TP dynamique, adapté à chaque paire ---
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.5   # distance du Stop Loss = 1.5x l'ATR
ATR_TP_MULTIPLIER = 2.5   # distance du Take Profit = 2.5x l'ATR (RR ≈ 1:1.67)

# Nombre de bougies récupérées à chaque analyse
CANDLES_COUNT = 200

# --- Gestion du risque / calcul automatique de la taille de position ---
RISK_PERCENT_LEVELS = [1, 2]  # % du solde à afficher comme suggestions dans chaque signal

# --- Reconnexion MT5 ---
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_WAIT_SECONDS = 10

# --- Paramètres de backtest ---
BACKTEST_MONTHS = 1
BACKTEST_SL_PIPS = 20
BACKTEST_TP_PIPS = 20
BACKTEST_MAX_HOLD_CANDLES = 100  # abandon du trade si ni SL ni TP touché après ça (≈8h en M5)

# Intervalle entre chaque cycle d'analyse (en secondes)
# En M5, on vérifie plus souvent qu'en M15 pour ne pas louper une bougie qui vient
# de se fermer (le dédoublonnage dans signal_state.py évite les signaux répétés).
CHECK_INTERVAL = 60  # toutes les 1 minute

# --- Filtre de tendance de fond (évite de trader à contre-tendance) ---
# Rejette un signal ACHAT si le marché est sous sa tendance de fond baissière
# (et inversement pour VENTE), en comparant le prix à une EMA longue sur une
# timeframe supérieure. Réduit les faux signaux en marché sans direction claire.
TREND_FILTER_ENABLED = True
TREND_TIMEFRAME = "H1"
TREND_EMA_PERIOD = 200
TREND_CANDLES_COUNT = 250

# --- Confluence de pattern de chandelier obligatoire ---
# False (par défaut) : le pattern est affiché à titre indicatif seulement.
# True : un signal SANS confluence de pattern est rejeté (plus strict, moins
# de signaux, mais activer seulement après avoir vérifié via le journal que
# la confluence améliore vraiment le taux de réussite).
REQUIRE_PATTERN_CONFLUENCE = False

# --- Filtre de session (heures de forte liquidité, en UTC) ---
# Abidjan est en UTC+0 toute l'année (pas de changement d'heure), ces bornes
# correspondent directement à l'heure locale. Couvre la pré-ouverture de
# Londres jusqu'à la clôture de New York.
SESSION_FILTER_ENABLED = True
SESSION_START_HOUR_UTC = 7
SESSION_END_HOUR_UTC = 21