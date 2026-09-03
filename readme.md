# Bot de signaux MT5 → Telegram

Bot d'analyse technique qui surveille des paires sur Exness via MT5 et envoie
des **signaux** (pas d'exécution automatique) sur Telegram quand un croisement
EMA9/EMA21 est confirmé par le RSI.

⚠️ **Ce bot ne trade pas à ta place.** Il t'envoie une notification ; c'est à toi
de valider et d'exécuter (ou non) le trade sur MT5.

## Prérequis

- **Windows** (le package `MetaTrader5` de Python ne fonctionne que sur Windows,
  car il communique avec le terminal MT5 installé localement — pas d'API cloud)
- Python 3.10+
- Le terminal **MT5 desktop installé et connecté** à ton compte Exness (login fait au moins une fois manuellement)
- Un bot Telegram créé via [@BotFather](https://t.me/BotFather) → récupère le token
- Ton `chat_id` Telegram (envoie un message à ton bot, puis va sur
  `https://api.telegram.org/bot<TON_TOKEN>/getUpdates` pour le trouver)

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env
# Édite .env avec tes vraies infos (login MT5, mot de passe, serveur, token Telegram, chat_id)
```

## Configuration

Modifie `config.py` selon tes besoins :
- `SYMBOLS` : les paires à surveiller (doivent exister exactement comme ça dans ton MT5 — vérifie l'orthographe, ex: certains brokers utilisent "EURUSDm")
- `TIMEFRAME` : unité de temps des bougies analysées
- `EMA_FAST` / `EMA_SLOW` / `RSI_PERIOD` : paramètres des indicateurs
- `CHECK_INTERVAL` : fréquence d'analyse en secondes

## Lancer le bot

```bash
python main.py
```

Le bot tourne en boucle, analyse chaque symbole toutes les `CHECK_INTERVAL` secondes,
et t'envoie un message Telegram dès qu'un signal ACHAT ou VENTE est détecté.

Arrête-le avec `Ctrl+C`.

## Stratégie utilisée (point de départ)

- **Signal ACHAT** : EMA9 croise EMA21 vers le haut ET RSI < 70
- **Signal VENTE** : EMA9 croise EMA21 vers le bas ET RSI > 30

C'est volontairement simple pour avoir une base solide à tester et améliorer.

## Prochaines étapes possibles

- [ ] Backtester la stratégie sur données historiques avant de s'y fier
- [ ] Ajouter d'autres indicateurs / filtres (ATR pour le stop loss, structure de marché...)
- [ ] Ajouter un mode "confirmation manuelle" via boutons Telegram (inline keyboard)
- [x] Logger tous les signaux dans un fichier/CSV pour analyser la performance réelle
- [ ] Déployer sur un VPS Windows pour tourner 24/7 (le marché forex est ouvert en continu du dimanche soir au vendredi soir)
- [ ] Si un jour tu veux automatiser l'exécution : ajouter `mt5.order_send()` avec des règles STRICTES de gestion du risque (taille de position, stop loss obligatoire, limite de pertes journalière)

## Suivi de performance (signals_log.csv)

Chaque signal détecté est automatiquement ajouté à `signals_log.csv` (créé au premier
signal), avec la paire, la direction, le prix d'entrée, le RSI, et l'heure de la bougie.

Pour évaluer si les signaux passés étaient bons, lance périodiquement (ex: une fois par jour) :

```bash
python evaluate_signals.py
```

Ce script compare le prix d'entrée de chaque signal au prix actuel du marché (seulement
pour les signaux ayant au moins 4h d'ancienneté, réglable via `MIN_HOURS_BEFORE_EVAL`
dans `evaluate_signals.py`), et remplit les colonnes `price_after`, `pips_change` et
`result` (GAGNANT/PERDANT) dans le CSV. Un résumé (taux de réussite global) s'affiche
à la fin.

⚠️ C'est une évaluation simplifiée (prix actuel vs prix d'entrée), pas un vrai backtest
avec stop loss/take profit — utile pour un premier ressenti, pas pour une décision finale.

Utilitaire supplémentaire : `python list_symbols.py` affiche tous les symboles
disponibles chez ton broker si tu veux ajouter/changer des paires dans `config.py`.

## ⚠️ Rappels importants

- Ceci génère des **signaux techniques**, pas des garanties de gain
- Teste d'abord sur un **compte démo Exness** avant tout compte réel
- Le RSI/EMA sur une seule timeframe donne beaucoup de faux signaux en marché sans tendance (range) — sois vigilant
- Ne mets jamais en prod avec de l'argent réel sans avoir vérifié le comportement pendant plusieurs semaines en démo