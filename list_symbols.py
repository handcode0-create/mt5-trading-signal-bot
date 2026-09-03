"""
Utilitaire : liste tous les symboles disponibles chez ton broker.
Sert à retrouver le nom EXACT à utiliser dans config.py (SYMBOLS).

Lancement : python list_symbols.py
"""

import MetaTrader5 as mt5
import config

if not mt5.initialize(login=config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER):
    print("Échec connexion MT5 :", mt5.last_error())
    exit()

symbols = mt5.symbols_get()
print(f"{len(symbols)} symboles trouvés chez ce broker.\n")

# Filtre pour ne montrer que ceux qui ressemblent à ce qu'on cherche
keywords = ["EUR", "GBP", "XAU", "GOLD", "USD"]
print("--- Symboles correspondant à EUR / GBP / XAU / GOLD / USD ---")
for s in symbols:
    if any(k in s.name.upper() for k in keywords):
        print(s.name)

mt5.shutdown()