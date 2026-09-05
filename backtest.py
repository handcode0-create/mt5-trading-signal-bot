"""
Backtest de la stratégie EMA9/EMA21 + RSI sur données historiques,
avec simulation réelle de Stop Loss / Take Profit (contrairement à
evaluate_signals.py qui compare juste au prix "actuel").

Pour chaque signal détecté dans l'historique, on avance bougie par bougie
et on regarde ce qui est touché en premier : le SL ou le TP.

Lancement : python backtest.py
Résultats : affichés dans le terminal + sauvegardés dans backtest_results.csv
"""

import argparse
import csv
import logging
from datetime import datetime, timedelta

import MetaTrader5 as mt5
import pandas as pd

import config
from analyzer import TIMEFRAME_MAP, compute_indicators
from patterns import BEARISH_PATTERNS, BULLISH_PATTERNS, detect_pattern_at, pattern_confluence

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RESULTS_FILE = "backtest_results.csv"


def pip_size(symbol: str) -> float:
    """Taille d'un pip selon le type d'actif (approximatif mais suffisant pour ce backtest)."""
    crypto_pips = {
        "BCHUSDm": 0.01,
        "BTCJPYm": 1.0,
        "BTCKRWm": 1.0,
        "BTCUSDm": 1.0,
        "ETHUSDm": 0.1,
        "LTCUSDm": 0.01,
        "XRPUSDm": 0.0001,
        "ADAUSDm": 0.0001,
        "BATUSDm": 0.0001,
        "LINKUSDm": 0.01,
    }
    if symbol in crypto_pips:
        return crypto_pips[symbol]
    if "JPY" in symbol:
        return 0.01
    if symbol.upper().startswith("XAU"):
        return 0.1
    if symbol.upper().startswith("XAG"):
        return 0.01
    return 0.0001


def fetch_historical(symbol: str, timeframe: str, months: int) -> pd.DataFrame | None:
    tf = TIMEFRAME_MAP.get(timeframe)
    if tf is None:
        logger.error("Timeframe inconnu : %s", timeframe)
        return None
    date_to = datetime.now()
    date_from = date_to - timedelta(days=30 * months)

    info = mt5.symbol_info(symbol)
    if info is None:
        logger.warning("Symbole '%s' introuvable, ignoré.", symbol)
        return None
    if info.trade_mode in {
        mt5.SYMBOL_TRADE_MODE_DISABLED,
        mt5.SYMBOL_TRADE_MODE_CLOSEONLY,
    }:
        logger.warning("Symbole '%s' non ouvrable chez le broker, ignoré.", symbol)
        return None
    if not info.visible:
        mt5.symbol_select(symbol, True)

    rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)
    if rates is None or len(rates) == 0:
        logger.warning("Pas de données historiques pour %s : %s", symbol, mt5.last_error())
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    # MT5 fournit le spread de chaque bougie en points. On le convertit
    # avec les propriétés réelles du symbole, y compris pour l'or et le JPY.
    df["spread_pips"] = df["spread"] * info.point / pip_size(symbol)
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
        spread_pips = float(curr.get("spread_pips", 0.0))

        if crossed_up and curr["rsi"] < config.RSI_OVERBOUGHT:
            pattern = detect_pattern_at(df, i)
            signals.append({
                "index": i, "direction": "ACHAT", "entry_price": entry, "time": curr["time"],
                "sl_dist": sl_dist, "tp_dist": tp_dist,
                "spread_pips": spread_pips,
                "pattern": pattern,
                "pattern_confluence": pattern_confluence(pattern, "ACHAT"),
            })
        elif crossed_down and curr["rsi"] > config.RSI_OVERSOLD:
            pattern = detect_pattern_at(df, i)
            signals.append({
                "index": i, "direction": "VENTE", "entry_price": entry, "time": curr["time"],
                "sl_dist": sl_dist, "tp_dist": tp_dist,
                "spread_pips": spread_pips,
                "pattern": pattern,
                "pattern_confluence": pattern_confluence(pattern, "VENTE"),
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


def pattern_status(signal: dict) -> str:
    pattern = signal["pattern"]
    if signal["pattern_confluence"]:
        return "confluence"
    if pattern is None or pattern == "Doji":
        return "sans_confluence"
    if (signal["direction"] == "ACHAT" and pattern in BEARISH_PATTERNS) or (
        signal["direction"] == "VENTE" and pattern in BULLISH_PATTERNS
    ):
        return "contradiction"
    return "sans_confluence"


def run_backtest(months: int, timeframes: list[str], symbols: list[str]):
    if not mt5.initialize(login=config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER):
        logger.error("Échec connexion MT5 : %s", mt5.last_error())
        return

    all_trades = []

    for timeframe in timeframes:
        for symbol in symbols:
            logger.info("Backtest sur %s (%s)...", symbol, timeframe)
            df = fetch_historical(symbol, timeframe, months)
            if df is None or len(df) < 50:
                continue

            df = compute_indicators(df)
            pip = pip_size(symbol)
            signals = find_signals(df)

            for sig in signals:
                trade = simulate_trade(df, sig, pip)
                all_trades.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "direction": sig["direction"],
                    "entry_time": sig["time"],
                    "entry_price": round(sig["entry_price"], 5),
                    "exit_time": trade["exit_time"],
                    "result": trade["result"],
                    "gross_pips": trade["pips"],
                    "spread_pips": round(sig["spread_pips"], 2),
                    "net_pips": round(trade["pips"] - sig["spread_pips"], 1),
                    "pattern": sig["pattern"] or "Aucun",
                    "pattern_status": pattern_status(sig),
                })

    mt5.shutdown()

    if not all_trades:
        print("Aucun trade généré sur la période. Essaie une période plus longue ou d'autres symboles.")
        return

    # Sauvegarde CSV détaillé
    with open(RESULTS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "timeframe", "direction", "entry_time", "entry_price", "exit_time", "result", "gross_pips", "spread_pips", "net_pips", "pattern", "pattern_status"])
        writer.writeheader()
        writer.writerows(all_trades)

    print_summary(all_trades, months)
    print(f"\nDétail complet sauvegardé dans {RESULTS_FILE}")


def print_summary(trades: list[dict], months: int):
    df = pd.DataFrame(trades)

    print(f"\n{'='*60}")
    print(f"BACKTEST — {months} mois — SL/TP dynamiques ATR {config.ATR_SL_MULTIPLIER}/{config.ATR_TP_MULTIPLIER}")
    print(f"{'='*60}")

    def summarize(sub_df, label):
        total = len(sub_df)
        if total == 0:
            return
        def metrics(column):
            wins = sub_df[sub_df[column] > 0]
            losses = sub_df[sub_df[column] <= 0]
            gross_win = wins[column].sum()
            gross_loss = abs(losses[column].sum())
            profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf")
            return (
                round(100 * len(wins) / total, 1),
                profit_factor,
                round(sub_df[column].mean(), 2),
                round(sub_df[column].sum(), 1),
            )

        gross = metrics("gross_pips")
        net = metrics("net_pips")

        print(f"\n--- {label} ---")
        print(f"Trades          : {total}")
        print(f"BRUT — réussite/PF/espérance/total : {gross[0]}% / {gross[1]} / {gross[2]} / {gross[3]} pips")
        print(f"NET  — réussite/PF/espérance/total : {net[0]}% / {net[1]} / {net[2]} / {net[3]} pips")

    summarize(df, "GLOBAL (toutes paires)")
    for timeframe in df["timeframe"].unique():
        summarize(df[df["timeframe"] == timeframe], f"TIMEFRAME {timeframe}")
    for symbol in df["symbol"].unique():
        summarize(df[df["symbol"] == symbol], symbol)
    for status in ("confluence", "sans_confluence", "contradiction"):
        summarize(df[df["pattern_status"] == status], f"PATTERN {status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest historique EMA9/EMA21 + RSI + patterns via MT5")
    parser.add_argument("--months", type=int, default=config.BACKTEST_MONTHS)
    parser.add_argument("--timeframes", nargs="+", default=[config.TIMEFRAME], choices=list(TIMEFRAME_MAP))
    parser.add_argument("--symbols", nargs="+", default=config.SYMBOLS)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_backtest(args.months, args.timeframes, args.symbols)