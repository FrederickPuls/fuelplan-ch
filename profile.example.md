# FuelPlan CH – Beispielprofil

Vorlage mit einer erfundenen Person. Für den eigenen Gebrauch diese Datei nach `profile.md` kopieren und anpassen; `profile.md` hat Vorrang, sobald es existiert (siehe `fuelplan/config.py`). Das Profil ist Teil des System-Prompts für den Plan-Schritt und die einzige Quelle für Ziele, Küche, Kochzeiten, Budget, Abneigungen und Vorlieben. Das Körpergewicht für die Bedarfsrechnung steht zusätzlich in `.env` (`FUELPLAN_WEIGHT_KG`).

## Profil
- Weiblich, geboren 01.01.1995 (Beispielperson)
- 70 kg, 172 cm
- Ziel: fit bleiben und stärker werden, **Halbmarathon im Frühling**. Zwei Ziele parallel: Das Laufvolumen braucht genug Kohlenhydrate, das Protein für den Kraftaufbau bleibt hoch.
- Portionen: 1 Person, normale Portion für eine aktive erwachsene Person
- Küche: Herd, Ofen, Airfryer, Kühlschrank, Tiefkühler
- Kochzeit: Abendessen typischerweise um ca. 19 Uhr. Unter der Woche ca. 30 bis 40 Minuten, am Wochenende auch länger. Frühstück und Mittagessen werden nicht geplant.
- Budget: max. **10 CHF pro Mahlzeit**, Ziel **6 bis 7 CHF**. Für "aufwendig" darf das Budget leicht überschritten werden, das aber ausweisen.
- Läden: **Migros, Denner und Coop** für Preise und Einkaufsliste. Preise aller drei über swissgroceries-MCP abfragen und pro Zutat das günstigste passende Produkt bzw. die beste Aktion wählen. Coop-Preise nur über swissgroceries-MCP, nie die Coop-Website direkt scrapen.

### Abneigungen und Unverträglichkeiten
- Keine Pilze
- Kein Rosenkohl

### Vorlieben
- Currys, Ofengemüse, Pasta mit viel Gemüse
