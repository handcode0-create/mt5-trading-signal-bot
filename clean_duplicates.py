"""
Utilitaire ponctuel : supprime les lignes en double dans signals_log.csv
(même symbole + même bougie + même direction).
Lancement : python clean_duplicates.py
"""
import csv
from signal_logger import LOG_FILE, FIELDNAMES

with open(LOG_FILE, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

seen = set()
unique_rows = []
for row in rows:
    key = (row["symbol"], row["candle_time"], row["direction"])
    if key not in seen:
        seen.add(key)
        unique_rows.append(row)

with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    writer.writeheader()
    writer.writerows(unique_rows)

print(f"{len(rows)} lignes -> {len(unique_rows)} lignes après nettoyage.")