# Presseschau

Baut jeden Morgen eine Übersicht der deutschen Nachrichtenlage: Meldungen,
die mehrere Redaktionen gleichzeitig führen, stehen oben — mit allen
Schlagzeilen und Links nebeneinander.

Läuft kostenlos auf GitHub Actions. Keine KI, keine laufenden Kosten.
Ausgegeben werden nur Überschrift, Medium und Link; es wird kein
Artikeltext übernommen und nichts zusammengefasst.

## Was wo passiert

| Datei | Aufgabe |
|---|---|
| `sources.json` | die Quellenliste — hier änderst du, welche Medien zählen |
| `build.py` | Feeds holen, clustern, Seite und Datenstand schreiben |
| `send_mail.py` | aus dem Datenstand die Mail bauen und über Brevo verschicken |
| `.github/workflows/daily.yml` | der tägliche Lauf |
| `docs/index.html` | die fertige Seite (wird automatisch überschrieben) |
| `docs/data/latest.json` | der Datenstand des Tages, getrennt von der Darstellung |

Die Trennung zwischen `build.py` und `send_mail.py` ist Absicht: Seite, Mail
und alles, was später dazukommt, lesen denselben Datenstand. Wer eine weitere
Ausgabeform will, schreibt ein drittes Skript und ändert am Rest nichts.

## Einrichten

**1. Repository anlegen.** Neues Repository auf GitHub, diese Dateien
hochladen. Öffentlich ist gut: Dann sind die Actions-Minuten unbegrenzt
(bei privaten Repos sind es 2.000 im Monat — für einen Lauf pro Tag reicht
auch das locker).

**2. Schreibrechte für Actions.** Settings → Actions → General →
*Workflow permissions* → **Read and write permissions**. Ohne das kann der
Lauf die gebaute Seite nicht zurückschreiben, und das ist der häufigste
Grund, warum gar nichts passiert.

**3. Erster Lauf von Hand.** Reiter Actions → *Presseschau* → *Run workflow*.
Danach liegt `docs/index.html` im Repository.

**4. Seite veröffentlichen.** Settings → Pages → Source: *Deploy from a
branch*, Branch `main`, Ordner `/docs`. Nach ein, zwei Minuten liegt die
Übersicht unter `https://<dein-name>.github.io/<repo-name>/`.

**5. Mail einschalten** (optional, kann auch später kommen).
In Brevo brauchst du einen API-Schlüssel (Konto → SMTP & API → API Keys) und
eine verifizierte Absenderadresse (Senders & IP → Senders). Brevo verschickt
nur von Adressen, die dort bestätigt sind — mit einer unbestätigten Adresse
gibt der Lauf einen Fehler zurück.

Dann im Repository unter Settings → Secrets and variables → Actions:

| Typ | Name | Wert |
|---|---|---|
| Secret | `BREVO_API_KEY` | der API-Schlüssel aus Brevo |
| Secret | `MAIL_VON` | deine verifizierte Absenderadresse |
| Secret | `MAIL_AN` | wohin die Mail gehen soll |
| Variable | `SEITEN_URL` | die Pages-Adresse aus Schritt 4 |

Solange `BREVO_API_KEY` fehlt, überspringt der Lauf den Mailversand
kommentarlos — die Seite wird trotzdem gebaut.

## Uhrzeit ändern

In `daily.yml` steht `cron: "25 5 * * *"`. Das ist **UTC**, also 7:25 im
Sommer und 6:25 im Winter. GitHub kennt keine Zeitzonen; wenn dir die
Winterzeit wichtiger ist, nimm `25 6 * * *`.

Verspätungen von zehn bis zwanzig Minuten sind bei GitHubs Scheduler normal
und kein Fehler.

## Quellen ändern

`sources.json` bearbeiten — Name, Feed-Adresse, fertig:

```json
{ "name": "NZZ", "url": "https://www.nzz.ch/recent.rss", "kind": "zeitung" }
```

Wenn eine Quelle nicht lädt, steht sie unten auf der Seite unter
*Quellenstatus*. Verlage ändern ihre Feed-Adressen gelegentlich; das ist der
einzige Wartungsaufwand, den das Ding hat.

## Clustering nachjustieren

Zwei Meldungen landen im selben Thema, wenn ihre Überschriften genug
Stichwörter teilen. Zusammengesetzte Wörter zählen halb mit, damit
„Tarifabschluss" und „Tarifverhandlungen" zusammenfinden.

Die Schwelle steht in `build.py` in `gehoert_zusammen`:

- **Zu viel klebt zusammen?** `0.42` erhöhen, etwa auf `0.5`.
- **Offensichtlich Gleiches bleibt getrennt?** auf `0.35` senken.

In `STOPWORDS` stehen Wörter, die für die Zuordnung nichts hergeben. Wenn ein
Wort immer wieder falsche Verbindungen stiftet, gehört es dort hinein.

## Lokal ausprobieren

```bash
pip install feedparser requests
python build.py --open
```

`--hours 48` vergrößert das Zeitfenster, falls an einem ruhigen Tag zu wenig
zusammenkommt.
