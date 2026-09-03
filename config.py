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