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

La liste inclut aussi les crypto actuellement ouvrables dans ce compte Exness :
`BTCUSDm` et `ETHUSDm`. Les autres crypto visibles dans la Market Watch peuvent
être désactivées ou en clôture uniquement; le moteur vérifie automatiquement le
mode de trading MT5 avant de produire un signal. Le suffixe `m` est spécifique
au broker.

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

### Détection de patterns de chandeliers (confluence)

Chaque signal EMA/RSI est désormais enrichi d'une détection de figure de chandelier
sur la dernière bougie clôturée (`patterns.py`) : Doji, Marteau, Étoile filante,
Engulfing haussier/baissier. Ce n'est **pas** un filtre qui bloque le signal — le
pattern est juste affiché en plus, avec un tag :

- ✅ *confluence* : le pattern va dans le même sens que le signal (ex: Marteau + ACHAT)
- ⚠️ *sens opposé* : le pattern détecté contredit le signal — sois plus prudent

Ces infos sont aussi loggées dans `signals_log.csv` (colonnes `pattern` et
`pattern_confluence`) pour pouvoir comparer plus tard le taux de réussite des
signaux avec confluence vs sans, comme dans ton journal de trading Excel.

### Filtres de rentabilité (session, tendance, confluence)

Trois filtres supplémentaires réduisent le nombre de faux signaux, réglables
dans `config.py` :

- **`SESSION_FILTER_ENABLED`** (défaut `False`) : n'analyse les marchés que
  pendant les heures de forte liquidité (`SESSION_START_HOUR_UTC` →
  `SESSION_END_HOUR_UTC`, en UTC = heure d'Abidjan toute l'année). Hors
  session, les mouvements sont souvent erratiques et peu fiables.
- **`TREND_FILTER_ENABLED`** (défaut `False`) : rejette un signal ACHAT si le
  marché est sous sa tendance de fond (EMA `TREND_EMA_PERIOD` sur
  `TREND_TIMEFRAME`, ex: EMA200 en H1), et inversement pour VENTE. Évite de
  trader à contre-tendance. Le résultat (`HAUSSIER`/`BAISSIER`) est affiché
  dans le message Telegram et loggé dans le CSV (`trend_h1`).
- **`REQUIRE_PATTERN_CONFLUENCE`** (défaut `False`) : si activé, un signal
  SANS confluence de pattern de chandelier est rejeté au lieu d'être juste
  affiché avec un avertissement. À activer seulement après avoir vérifié,
  via le journal, que la confluence améliore vraiment le taux de réussite —
  pas de raison de couper des signaux sur une hypothèse non testée.

Ces filtres réduisent mécaniquement le nombre de signaux envoyés — c'est
voulu : l'objectif est un meilleur taux de réussite, pas plus de volume.

### Calendrier économique ForexFactory

Le bot récupère facultativement les annonces à impact moyen/fort via le flux
ForexFactory. Les événements des devises de la paire, publiés récemment ou
prévus dans les 24 prochaines heures, sont ajoutés au message Telegram avec un
biais indicatif (`HAUSSIER`, `BAISSIER` ou `NEUTRE`). Ce contexte ne bloque
aucun signal et ne remplace pas l'analyse du marché. Le flux est mis en cache
15 minutes; si le site est indisponible, le signal technique continue de partir.

### Analyse TradingView

Chaque signal peut aussi inclure la recommandation TradingView (`BUY`, `SELL`
ou `NEUTRAL`) et les compteurs BUY/SELL de son résumé technique, sur le même
timeframe que le bot. Cette donnée est une confirmation externe, non un filtre:
elle ne bloque aucun signal. La bibliothèque `tradingview-ta` interroge un
service non officiel; si ce service échoue, le message indique `N/A` et le bot
continue avec MT5.

## Backtest historique MT5

Le backtester utilise les bougies historiques réelles du terminal MT5 et simule
le SL/TP dynamique basé sur l'ATR. Le spread de chaque bougie est également
lu dans le champ `spread` fourni par MT5, puis converti en pips avec le `point`
réel du symbole. Le coût historique est donc dynamique selon l'heure et la
liquidité, sans valeur fixe dans la configuration. Le résumé affiche BRUT et
NET côte à côte; le CSV conserve le spread appliqué à chaque trade.

```bash
# Test rapide sur le timeframe configuré
python backtest.py --months 6

# Comparaison des 12 symboles sur plusieurs timeframes
python backtest.py --months 6 --timeframes M5 M15 M30 H1 H4 D1

# Sous-ensemble utile pour un contrôle ciblé
python backtest.py --months 12 --timeframes H1 H4 --symbols EURUSDm XAUUSDm
```

Le résumé affiche le taux de réussite, le profit factor, l'espérance et les
pips totaux par timeframe, symbole et statut de pattern. `confluence` désigne
un pattern dans le même sens que le signal; `contradiction` le sens opposé;
`sans_confluence` inclut l'absence de pattern et le Doji. Compare surtout
l'espérance et le profit factor, avec le nombre de trades, avant d'activer un
filtre de confluence.

## Prochaines étapes possibles

- [x] Backtester la stratégie sur données historiques avant de s'y fier
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