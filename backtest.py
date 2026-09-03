"""
Backtest de la stratégie EMA9/EMA21 + RSI sur données historiques,
avec simulation réelle de Stop Loss / Take Profit (contrairement à
evaluate_signals.py qui compare juste au prix "actuel").

Pour chaque signal détecté dans l'historique, on avance bougie par bougie
et on regarde ce qui est touché en premier : le SL ou le TP.

Lancement : python backtest.py
Résultats : affichés dans le terminal + sauvegardés dans backtest_results.csv
"""

import csv
import logging
from datetime import datetime, timedelta

import MetaTrader5 as mt5
import pandas as pd

import config
from analyzer import TIMEFRAME_MAP, compute_indicators

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RESULTS_FILE = "backtest_results.csv"


def pip_size(symbol: str) -> float:
    """Taille d'un pip selon le type d'actif (approximatif mais suffisant pour ce backtest)."""
    if "JPY" in symbol:
        return 0.01
    if symbol.upper().startswith("XAU"):
        return 0.1
    if symbol.upper().startswith("XAG"):
        return 0.01
    return 0.0001


def fetch_historical(symbol: str, months: int) -> pd.DataFrame | None:
    tf = TIMEFRAME_MAP.get(config.TIMEFRAME)
    date_to = datetime.now()
    date_from = date_to - timedelta(days=30 * months)

    info = mt5.symbol_info(symbol)
    if info is None:
        logger.warning("Symbole '%s' introuvable, ignoré.", symbol)
        return None
    if not info.visible:
        mt5.symbol_select(symbol, True)

    rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)
    if rates is None or len(rates) == 0:
        logger.warning("Pas de données historiques pour %s : %s", symbol, mt5.last_error())
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def find_signals(df: pd.DataFrame) -> list[dict]:
    """
    Rejoue la détection de croisement EMA + RSI sur tout l'historique, bougie par bougie,
    avec le même calcul de SL/TP basé sur l'ATR que le bot en temps réel (analyzer.detect_signal).
    """
    signals = []
    for i in range(2, len(df) - 1):  # -1 pour toujours avoir une bougie "suivante" disponible
        prev = df.iloc[i - 1]
        curr = df.iloc[i]

        if pd.isna(curr["ema_fast"]) or pd.isna(curr["ema_slow"]) or pd.isna(curr["rsi"]) or pd.isna(curr["atr"]):
            continue

        crossed_up = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
        crossed_down = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]

        entry = curr["close"]
        atr = curr["atr"]
        sl_dist = atr * config.ATR_SL_MULTIPLIER
        tp_dist = atr * config.ATR_TP_MULTIPLIER

        if crossed_up and curr["rsi"] < config.RSI_OVERBOUGHT:
            signals.append({
                "index": i, "direction": "ACHAT", "entry_price": entry, "time": curr["time"],
                "sl_dist": sl_dist, "tp_dist": tp_dist,
            })
        elif crossed_down and curr["rsi"] > config.RSI_OVERSOLD:
            signals.append({
                "index": i, "direction": "VENTE", "entry_price": entry, "time": curr["time"],
                "sl_dist": sl_dist, "tp_dist": tp_dist,
            })

    return signals


def simulate_trade(df: pd.DataFrame, signal: dict, pip: float) -> dict:
    """Avance bougie par bougie après le signal pour voir si le SL ou le TP (basés ATR) est touché en premier."""
    entry = signal["entry_price"]
    direction = signal["direction"]
    sl_dist = signal["sl_dist"]
    tp_dist = signal["tp_dist"]

    if direction == "ACHAT":
        sl_level = entry - sl_dist
        tp_level = entry + tp_dist
    else:
        sl_level = entry + sl_dist
        tp_level = entry - tp_dist

    start = signal["index"] + 1
    end = min(start + config.BACKTEST_MAX_HOLD_CANDLES, len(df))

    for j in range(start, end):
        high = df.iloc[j]["high"]
        low = df.iloc[j]["low"]

        if direction == "ACHAT":
            hit_tp = high >= tp_level
            hit_sl = low <= sl_level
        else:
            hit_tp = low <= tp_level
            hit_sl = high >= sl_level

        # Si les deux sont techniquement touchés dans la même bougie, on suppose
        # le pire cas (SL touché en premier) — hypothèse prudente, pas garantie exacte.
        if hit_sl and hit_tp:
            return {"result": "PERDANT", "pips": round(-sl_dist / pip, 1), "exit_time": df.iloc[j]["time"]}
        if hit_tp:
            return {"result": "GAGNANT", "pips": round(tp_dist / pip, 1), "exit_time": df.iloc[j]["time"]}
        if hit_sl:
            return {"result": "PERDANT", "pips": round(-sl_dist / pip, 1), "exit_time": df.iloc[j]["time"]}

    # Ni SL ni TP touché dans la fenêtre max : on clôture au prix de la dernière bougie regardée
    last_price = df.iloc[end - 1]["close"]
    pips_moved = (last_price - entry) / pip if direction == "ACHAT" else (entry - last_price) / pip
    result = "GAGNANT" if pips_moved > 0 else "PERDANT"
    return {"result": f"{result} (timeout)", "pips": round(pips_moved, 1), "exit_time": df.iloc[end - 1]["time"]}


def run_backtest():
    if not mt5.initialize(login=config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER):
        logger.error("Échec connexion MT5 : %s", mt5.last_error())
        return

    all_trades = []

    for symbol in config.SYMBOLS:
        logger.info("Backtest sur %s...", symbol)
        df = fetch_historical(symbol, config.BACKTEST_MONTHS)
        if df is None or len(df) < 50:
            continue

        df = compute_indicators(df)
        pip = pip_size(symbol)
        signals = find_signals(df)

        for sig in signals:
            trade = simulate_trade(df, sig, pip)
            all_trades.append({
                "symbol": symbol,
                "direction": sig["direction"],
                "entry_time": sig["time"],
                "entry_price": round(sig["entry_price"], 5),
                "exit_time": trade["exit_time"],
                "result": trade["result"],
                "pips": trade["pips"],
            })

    mt5.shutdown()

    if not all_trades:
        print("Aucun trade généré sur la période. Essaie une période plus longue ou d'autres symboles.")
        return

    # Sauvegarde CSV détaillé
    with open(RESULTS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "direction", "entry_time", "entry_price", "exit_time", "result", "pips"])
        writer.writeheader()
        writer.writerows(all_trades)

    print_summary(all_trades)
    print(f"\nDétail complet sauvegardé dans {RESULTS_FILE}")


def print_summary(trades: list[dict]):
    df = pd.DataFrame(trades)

    print(f"\n{'='*60}")
    print(f"BACKTEST — {config.BACKTEST_MONTHS} mois — SL={config.BACKTEST_SL_PIPS} pips / TP={config.BACKTEST_TP_PIPS} pips")
    print(f"{'='*60}")

    def summarize(sub_df, label):
        total = len(sub_df)
        if total == 0:
            return
        wins = sub_df[sub_df["pips"] > 0]
        losses = sub_df[sub_df["pips"] <= 0]
        win_rate = 100 * len(wins) / total
        gross_win = wins["pips"].sum()
        gross_loss = abs(losses["pips"].sum())
        profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf")
        expectancy = round(sub_df["pips"].mean(), 2)
        total_pips = round(sub_df["pips"].sum(), 1)

        print(f"\n--- {label} ---")
        print(f"Trades          : {total}")
        print(f"Win rate        : {round(win_rate, 1)}%")
        print(f"Profit factor   : {profit_factor}")
        print(f"Espérance/trade : {expectancy} pips")
        print(f"Total pips      : {total_pips}")

    summarize(df, "GLOBAL (toutes paires)")
    for symbol in df["symbol"].unique():
        summarize(df[df["symbol"] == symbol], symbol)


if __name__ == "__main__":
    run_backtest()