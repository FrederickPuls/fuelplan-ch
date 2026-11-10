# FuelPlan CH – Design-Richtung (Phase 2, Block 1)

Stand 08.11.2026. Erstellt mit dem Apple-Design-Skill (Creation Mode); gelesen: `accessibility`, `layout`, `typography`,
`color`, `designing-for-ios`, `cross-platform`, `tab-bars`, `dark-mode`, `lists-and-tables`, `buttons`, `materials`,
`loading`, `progress-indicators`, `feedback`, `writing`, `charting-data`, `sheets`. Web-App, also gelten Prinzipien und
Grundlagen (Barrierefreiheit, Farbe, Typografie, Layout, Sprache), die iOS-Konventionen sinngemäss (Tab-Bar, Sheets, Safe Areas).

## Brief

- **Produkt:** FuelPlan CH macht aus dem Training von heute das Abendessen von heute: drei Rezepte mit echten
  Schweizer Supermarktpreisen und eine Einkaufsliste zum Abhaken.
- **Nutzer:** Frederick, nach dem Training, oft unterwegs oder im Laden, meist einhändig am iPhone, manchmal am Laptop.
- **Aufgabe pro Screen:**
  - *Heute:* sehen, was der Tag verlangt (Tag-Typ, Bedarf fürs Abendessen) und drei Varianten mit echten Preisen holen.
  - *Rezept:* entscheiden, ob das gekocht wird (Zutaten, Schritte, Geräte) und die Variante wählen.
  - *Einkauf:* die richtigen Produkte im richtigen Laden kaufen und abhaken, auch ohne Empfang.
  - *Verlauf:* festhalten, was gekocht wurde und wie gut es war.
  - *Kosten:* sehen, dass die API-Kosten im Monatsbudget bleiben.

**These:** Der Tag entscheidet, was auf den Teller kommt. Die App zeigt das als Treibstoff: so viel braucht das Abendessen,
so viel liefert jedes Rezept.

## Signatur: der Treibstoff-Balken

Ein Balken, zwei Verwendungen, eine Sprache (`charting-data` › Prefer consistency across multiple charts):

1. Auf *Heute*: Spur = Tagesbedarf, Füllung = Anteil fürs Abendessen (40 %). Darüber die grosse Zahl: kcal fürs Abendessen
   in der Treibstoff-Farbe. Das ist die Übersetzung von Training → Treibstoff.
2. Auf jeder Variantenkarte: Spur = Ziel fürs Abendessen, Füllung = was das Rezept pro Portion liefert. Liegt ein Wert über
   dem Ziel, bekommt die Füllung zusätzlich Streifen; die Zahl steht immer daneben (nichts nur über Farbe).

Alles andere bleibt ruhig: Systemschrift, weisse bzw. dunkle Karten, eine Akzentfarbe, Icons aus Lucide (keine SF Symbols).
Die drei Varianten unterscheiden sich über Wort und Symbol (Sparschwein, Timer, Kochmütze), nicht über Farbe.
Die Läden (Migros, Denner, Coop) erscheinen als Text, nie in ihren Markenfarben.

Warum kein Template-Look: keine Creme-Serif-Terracotta-Kombination (Systemschrift, neutrale Flächen), kein Schwarz mit
Neon-Akzent, keine Haarlinien-Zeitung. Die Farbe kommt aus dem Thema (Treibstoff/Energie), nicht aus einer Vorlage.

## Tokens (`src/tokens.css`)

### Farben mit Rolle und berechnetem Kontrast

Berechnung: `npm run contrast` (WCAG 2, aus den Hex-Werten in `tokens.css`); `src/contrast.test.ts` prüft dieselben Paare.

| Rolle | Token | Hell | Dunkel | Kontrast hell | Kontrast dunkel | Untergrenze |
|---|---|---|---|---|---|---|
| Seite | `--bg` | `#F4F3EF` | `#0F0E0D` | – | – | – |
| Karte | `--surface` | `#FFFFFF` | `#1C1B19` | – | – | – |
| Vertiefung, Balkenspur | `--surface-2` | `#ECEAE4` | `#2A2825` | – | – | – |
| Text | `--ink` | `#1B1A17` | `#F3F1EB` | 17.4:1 auf Karte, 15.7:1 auf Seite | 15.2:1 / 17.1:1 | 4.5:1 |
| Nebentext | `--ink-2` | `#5E5B53` | `#ABA79D` | 6.8:1 auf Karte, 5.6:1 auf Vertiefung | 7.2:1 / 6.1:1 | 4.5:1 |
| Treibstoff (Akzent) | `--fuel` | `#A05C00` | `#F0B14D` | 5.2:1 als Text auf Karte, 4.7:1 auf Seite, 4.3:1 Füllung gegen Spur | 9.1:1 / 10.2:1 / 7.8:1 | 4.5:1 Text, 3:1 Element |
| Text auf Treibstoff | `--on-fuel` | `#FFFFFF` | `#1B1A17` | 5.2:1 | 9.2:1 | 4.5:1 |
| Signal (Fehler) | `--signal` | `#B3261E` | `#FF7A70` | 6.5:1 auf Karte | 6.8:1 | 4.5:1 |
| Fokusring | `--focus` | `#1F5FBF` | `#8AB4FF` | 6.1:1 | 8.2:1 | 3:1 |
| Trennlinie | `--line` | `#DDDAD2` | `#37352F` | 1.4:1 (dekorativ) | 1.4:1 | – |

`prefers-contrast: more` verstärkt Nebentext, Linien und Akzent (hell `#7A4600`, dunkel `#FFC76A`). Hell/dunkel nur über
`prefers-color-scheme`, kein App-Schalter (`dark-mode` › Avoid offering an app-specific appearance setting).

### Schrift

Systemschrift (SF Pro auf iPhone und Mac), keine Web-Schrift: offline-fähig, keine Lizenzfrage, Dynamic Type verhält sich
wie nativ. Grosse Zahlen (kcal, Preis) in `ui-rounded`, wo der Browser es hat (Safari), sonst Systemschrift. Alle Grössen
in `rem`, nichts unter 12 px, Fliesstext 17 px wie iOS „Body“ (`typography` › Specifications, Large):

| Token | px | Verwendung |
|---|---|---|
| `--text-caption` | 12 | Tab-Beschriftung, Eyebrow (Versalien, gesperrt) |
| `--text-footnote` | 13 | Fussnoten, Meta, Balken-Bezugsgrösse |
| `--text-callout` | 16 | Beschreibungen, Listentexte |
| `--text-body` | 17 | Fliesstext, Buttons |
| `--text-title3` | 20 | Kartentitel |
| `--text-title2` | 22 | Abschnitte |
| `--text-title1` | 28 | Tag-Typ |
| `--text-large` | 34 | Seitentitel, Preis pro Portion |
| `--text-display` | 44 | kcal fürs Abendessen (Signatur) |

Gewichte Regular, Semibold, Bold; keine leichten Schnitte (`typography` › In general, avoid light font weights).
Zahlen mit `tabular-nums`.

### Abstände, Radien, Masse

4-pt-Raster (`--s-1` 4 px … `--s-10` 40 px). Radien 10 / 14 / 20 px (Pill, Button, Karte). Touch-Ziele mindestens 44 × 44 px
(`accessibility` › Offer sufficiently sized controls). Lesebreite 640 px; ab 896 px Breite stehen die drei Variantenkarten
nebeneinander, die Tab-Bar wird in Block 3 zur Seitenleiste (`layout` › Keep functionality the same as size classes change).

## Layout

Eine Spalte, Karten auf ruhiger Fläche; Tab-Bar unten mit drei Tabs (Heute · Einkauf · Verlauf), sie navigiert nur
(`tab-bars` › Use a tab bar to support navigation, not to provide actions). Glas (Blur) nur auf der Tab-Bar, mit fester Fläche
bei `prefers-reduced-transparency` (`materials` › Don't use Liquid Glass in the content layer). Rezept und Kosten kommen als
Sheets mit klarem Weg zurück. Fehler und Fortschritt stehen im Interface, kein `alert()` (`feedback` › Consider integrating
status feedback into your interface). Safe Areas über `env(safe-area-inset-*)`.

## Bewegung

Eine Bewegung: die Balken füllen sich beim Erscheinen (420 ms). Fortschrittspunkte pulsieren während eines Laufs.
Beides aus bei `prefers-reduced-motion`.

## Sprache

Deutsch, Schweizer Schreibweise (ss). Schaltflächen sagen, was passiert („Vorschläge erstellen“, „Diese Variante kochen“).
Fehler sagen, was zu tun ist („Mac nicht erreichbar – schläft er oder ist er offline? …“). Leere Zustände laden zur nächsten
Aktion ein (`writing` › Provide clear next steps on any blank screens). Kein „wir“, kein „Oops“.

## Komponentenliste (für Block 2–3)

Stand Block 3: `TabBar` (wird ab 56 rem zur Seitenleiste), `FuelBar` (Signatur), `DayGauge`, `TrainingList`, `VariantCard`,
`Notice`, `EmptyState`, `RunProgress`, `Sheet` (Basis), `RecipeSheet`, `CostsSheet`; Screens `Today`, `Shopping` (Summen,
Ladengruppen, Zeilen als Checkbox-Buttons, Offline-Banner), `History` (Gekocht-Pillen, Sterne). Logik ohne Anzeige in
`api.ts`, `sse.ts`, `offline.ts`, `format.ts` (alle mit vitest getestet).
