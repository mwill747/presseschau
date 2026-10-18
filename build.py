#!/usr/bin/env python3
"""
Presseschau – baut aus mehreren deutschen Nachrichten-Feeds eine Tagesuebersicht.

Die Meldungen werden danach sortiert, wie viele Redaktionen dasselbe Thema
fuehren. Es wird nichts zusammengefasst und kein Verlagstext uebernommen:
ausgegeben werden nur Ueberschrift, Medium und Link.

Aufruf:
    python3 build.py              # baut docs/index.html
    python3 build.py --open       # baut und oeffnet die Seite im Browser
    python3 build.py --hours 48   # groesseres Zeitfenster
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests

BERLIN = ZoneInfo("Europe/Berlin")
ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
ARCHIV = DOCS / "archiv"
DATEN = DOCS / "data"

USER_AGENT = (
    "Presseschau/1.0 (persoenlicher Nachrichtenueberblick; "
    "nur Ueberschriften und Links)"
)

# Woerter, die fuer die Themenzuordnung nichts hergeben.
STOPWORDS = {
    "aber", "alle", "allem", "allen", "aller", "alles", "also", "andere",
    "anderen", "auch", "auf", "aus", "bei", "beim", "bereits", "bis", "dabei",
    "dann", "darf", "das", "dass", "davon", "dazu", "dem", "den", "denn",
    "der", "des", "die", "dies", "diese", "diesem", "diesen", "dieser",
    "dieses", "doch", "dort", "durch", "ein", "eine", "einem", "einen",
    "einer", "eines", "etwa", "fuer", "ganz", "geben", "gegen", "gibt",
    "hab", "habe", "haben", "hat", "hatte", "hatten", "hier", "ihr", "ihre",
    "ihrem", "ihren", "ihrer", "immer", "ist", "jetzt", "kann", "kein",
    "keine", "koennen", "laesst", "lassen", "mehr", "mein", "mit", "muss",
    "nach", "nicht", "noch", "nun", "nur", "ober", "oder", "ohne", "schon",
    "sein", "seine", "seinem", "seinen", "seiner", "seit", "sich", "sie",
    "sind", "soll", "sollen", "sondern", "sowie", "ueber", "und", "uns",
    "unter", "vom", "von", "vor", "waehrend", "war", "waren", "was", "weg",
    "weil", "weitere", "weiteren", "welche", "wenn", "werden", "wie",
    "wieder", "wird", "wir", "wurde", "wurden", "zum", "zur", "zwar",
    "zwei", "zwischen",
    # Floskeln aus Nachrichtentiteln
    "news", "newsblog", "liveblog", "live", "ticker", "kommentar",
    "analyse", "interview", "update", "video", "podcast", "eilmeldung",
    "morgen", "heute", "gestern", "jahr", "jahre", "jahren", "uhr",
    "neue", "neuen", "neuer", "neues", "erste", "ersten", "erster",
    "mann", "frau", "menschen", "leute", "deutschland", "deutsche",
    "deutschen", "deutscher",
}


# ---------------------------------------------------------------- Einlesen

def lade_quellen() -> list[dict]:
    with open(ROOT / "sources.json", encoding="utf-8") as f:
        return json.load(f)


def hole_feed(quelle: dict, timeout: int = 20) -> tuple[list[dict], str | None]:
    """Laedt einen Feed. Gibt (Eintraege, Fehlermeldung) zurueck."""
    try:
        antwort = requests.get(
            quelle["url"],
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        antwort.raise_for_status()
    except Exception as fehler:  # Netzfehler, 403, Timeout ...
        return [], f"{type(fehler).__name__}: {fehler}"

    geparst = feedparser.parse(antwort.content)
    if not geparst.entries:
        return [], "Feed enthaelt keine Eintraege"

    eintraege = []
    for eintrag in geparst.entries:
        titel = (eintrag.get("title") or "").strip()
        link = (eintrag.get("link") or "").strip()
        if not titel or not link:
            continue
        eintraege.append(
            {
                "titel": saubere_ueberschrift(titel),
                "link": link,
                "quelle": quelle["name"],
                "art": quelle.get("kind", ""),
                "zeit": lies_zeit(eintrag),
            }
        )
    return eintraege, None


def lies_zeit(eintrag) -> datetime | None:
    for feld in ("published_parsed", "updated_parsed"):
        wert = eintrag.get(feld)
        if wert:
            return datetime(*wert[:6], tzinfo=timezone.utc).astimezone(BERLIN)
    return None


def saubere_ueberschrift(titel: str) -> str:
    """Entfernt Praefixe wie 'Liveblog: ' oder ' +++' aus Titeln."""
    titel = re.sub(r"^\s*(Liveblog|Newsblog|Live|Eilmeldung|Update)\s*[:|–-]\s*",
                   "", titel, flags=re.I)
    titel = re.sub(r"\s*\++\s*$", "", titel)
    return re.sub(r"\s+", " ", titel).strip()


# -------------------------------------------------------------- Clustering

def normalisiere(wort: str) -> str:
    wort = wort.lower()
    wort = (wort.replace("ä", "ae").replace("ö", "oe")
                .replace("ü", "ue").replace("ß", "ss"))
    wort = unicodedata.normalize("NFKD", wort)
    return "".join(z for z in wort if not unicodedata.combining(z))


# Endungen, die im Deutschen dasselbe Wort unterschiedlich aussehen lassen:
# "oeffentlichen" und "oeffentlicher" sollen zusammenfallen.
ENDUNGEN = ("ungen", "erin", "innen", "ung", "nen", "en", "er", "es", "em",
            "ns", "n", "s", "e")


def stamm(wort: str) -> str:
    for endung in ENDUNGEN:
        if wort.endswith(endung) and len(wort) - len(endung) >= 4:
            return wort[: -len(endung)]
    return wort


def schluesselwoerter(titel: str) -> set[str]:
    """Die Wortstaemme eines Titels, die fuer die Themenzuordnung zaehlen."""
    rohe = re.findall(r"[A-Za-zÄÖÜäöüß0-9-]+", titel)
    treffer = set()
    for roh in rohe:
        wort = normalisiere(roh)
        if wort in STOPWORDS or len(wort) < 2:
            continue
        gross_geschrieben = roh[:1].isupper()
        if len(wort) >= 4 or (gross_geschrieben and len(wort) >= 2):
            treffer.add(stamm(wort))
    return treffer


def naehe(a: set[str], b: set[str]) -> float:
    """Punkte fuer Gemeinsamkeiten: ganzes Wort 1, Komposita-Anfang 0,5.

    Deutsche Nachrichtentitel beschreiben dasselbe Thema oft mit
    verschiedenen Zusammensetzungen ("Tarifabschluss" / "Tarifverhandlungen").
    Ein gemeinsamer Wortanfang ab fuenf Zeichen zaehlt deshalb halb mit.
    """
    punkte = float(len(a & b))
    rest_a, rest_b = a - b, b - a
    for wort_a in rest_a:
        for wort_b in rest_b:
            kurz, lang = sorted((wort_a, wort_b), key=len)
            if len(kurz) >= 5 and lang.startswith(kurz):
                punkte += 0.5
                break
    return punkte


def gehoert_zusammen(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    punkte = naehe(a, b)
    if punkte < 2:
        return False
    aehnlichkeit = punkte / min(len(a), len(b))
    # Bei sehr kurzen Titeln strenger sein, sonst klebt alles zusammen.
    if min(len(a), len(b)) <= 3:
        return aehnlichkeit >= 0.65
    return aehnlichkeit >= 0.42


def bilde_cluster(artikel: list[dict]) -> list[list[dict]]:
    """Einfaches Single-Link-Clustering ueber Stichwortueberlappung."""
    woerter = [schluesselwoerter(a["titel"]) for a in artikel]
    eltern = list(range(len(artikel)))

    def wurzel(i: int) -> int:
        while eltern[i] != i:
            eltern[i] = eltern[eltern[i]]
            i = eltern[i]
        return i

    def vereine(i: int, j: int) -> None:
        wi, wj = wurzel(i), wurzel(j)
        if wi != wj:
            eltern[wj] = wi

    for i in range(len(artikel)):
        for j in range(i + 1, len(artikel)):
            if artikel[i]["quelle"] == artikel[j]["quelle"]:
                continue  # dieselbe Redaktion bildet kein Cluster mit sich
            if gehoert_zusammen(woerter[i], woerter[j]):
                vereine(i, j)

    gruppen: dict[int, list[dict]] = defaultdict(list)
    for i, eintrag in enumerate(artikel):
        gruppen[wurzel(i)].append(eintrag)
    return list(gruppen.values())


def sortiere_cluster(cluster: list[list[dict]]) -> list[list[dict]]:
    def schluessel(gruppe: list[dict]):
        medien = len({a["quelle"] for a in gruppe})
        neuste = max((a["zeit"] for a in gruppe if a["zeit"]), default=None)
        return (-medien, -len(gruppe),
                -(neuste.timestamp() if neuste else 0))

    for gruppe in cluster:
        gruppe.sort(key=lambda a: (a["zeit"] is None,
                                   -(a["zeit"].timestamp() if a["zeit"] else 0)))
    return sorted(cluster, key=schluessel)


# ------------------------------------------------------------------ Ausgabe

def e(text: str) -> str:
    return html.escape(text, quote=True)


def baue_seite(cluster: list[list[dict]], pro_quelle: dict[str, list[dict]],
               fehler: dict[str, str], stand: datetime,
               stunden: int) -> str:
    mehrfach = [g for g in cluster if len({a["quelle"] for a in g}) >= 2]
    einzeln = [g for g in cluster if len({a["quelle"] for a in g}) == 1]
    hoechste = max((len({a["quelle"] for a in g}) for g in mehrfach), default=1)

    teile: list[str] = []

    for nummer, gruppe in enumerate(mehrfach, start=1):
        medien = sorted({a["quelle"] for a in gruppe})
        breite = round(len(medien) / hoechste * 100)
        leitartikel = gruppe[0]
        zeilen = "".join(
            f'<li><a href="{e(a["link"])}" target="_blank" rel="noopener">'
            f'<span class="medium">{e(a["quelle"])}</span>'
            f'<span class="schlagzeile">{e(a["titel"])}</span></a></li>'
            for a in gruppe
        )
        teile.append(f"""
      <article class="thema">
        <div class="kopf">
          <span class="nr">{nummer:02d}</span>
          <h3>{e(leitartikel["titel"])}</h3>
          <div class="zaehler">
            <b>{len(medien)}</b>
            <div class="balken"><i style="width:{breite}%"></i></div>
            <span>Medien</span>
          </div>
        </div>
        <ul class="belege">{zeilen}</ul>
      </article>""")

    themenblock = "\n".join(teile) if teile else (
        '<p class="leer">Heute hat kein Thema zwei oder mehr Redaktionen '
        'gleichzeitig beschäftigt. Das ist selten — eher ein Zeichen dafür, '
        'dass ein Feed nicht geladen hat. Siehe Quellenstatus unten.</p>'
    )

    spalten = []
    for quelle, artikel in pro_quelle.items():
        eintraege = "".join(
            f'<li><a href="{e(a["link"])}" target="_blank" rel="noopener">'
            f'{e(a["titel"])}</a></li>'
            for a in artikel[:3]
        ) or '<li class="fehlt">—</li>'
        spalten.append(
            f'<div class="spalte"><h4>{e(quelle)}</h4><ol>{eintraege}</ol></div>'
        )
    spaltenblock = "".join(spalten)

    einzelzeilen = "".join(
        f'<li><a href="{e(g[0]["link"])}" target="_blank" rel="noopener">'
        f'<span class="medium">{e(g[0]["quelle"])}</span>'
        f'<span class="schlagzeile">{e(g[0]["titel"])}</span></a></li>'
        for g in einzeln[:25]
    )

    if fehler:
        status = "".join(
            f'<li><b>{e(name)}</b> — {e(grund)}</li>'
            for name, grund in fehler.items()
        )
        statusblock = (f'<div class="warnung"><p>Diese Quellen haben nicht '
                       f'geantwortet:</p><ul>{status}</ul></div>')
    else:
        statusblock = ('<p class="ok">Alle Quellen haben geantwortet.</p>')

    gesamt = sum(len(g) for g in cluster)

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Presseschau — {stand.strftime('%d.%m.%Y')}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{
  --ground:#F6F7F9;--surface:#FFFFFF;--ink:#161B22;--ink-soft:#4B5563;
  --ink-faint:#7A8592;--line:#DDE2E8;--line-soft:#E9EDF1;--accent:#125C6E;
  --bar-bg:#E4E9EE;--warn:#9A6109;--warn-bg:#F7EEDC;--ok:#2F6B45;
}}
@media (prefers-color-scheme: dark){{
  :root:not([data-theme="light"]){{
    --ground:#101418;--surface:#171C22;--ink:#E8ECF1;--ink-soft:#AAB4C0;
    --ink-faint:#7C8794;--line:#2A323B;--line-soft:#222931;--accent:#63BACC;
    --bar-bg:#252D36;--warn:#D9A441;--warn-bg:#33280F;--ok:#79C295;
  }}
}}
:root[data-theme="dark"]{{
  --ground:#101418;--surface:#171C22;--ink:#E8ECF1;--ink-soft:#AAB4C0;
  --ink-faint:#7C8794;--line:#2A323B;--line-soft:#222931;--accent:#63BACC;
  --bar-bg:#252D36;--warn:#D9A441;--warn-bg:#33280F;--ok:#79C295;
}}
*{{box-sizing:border-box;}}
body{{background:var(--ground);color:var(--ink);margin:0;padding:0 20px 80px;
 font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
 font-size:16.5px;line-height:1.6;}}
.wrap{{max-width:840px;margin:0 auto;}}
header{{padding:48px 0 20px;border-bottom:2px solid var(--ink);margin-bottom:12px;}}
.datum{{font-family:"IBM Plex Mono",monospace;font-size:11.5px;letter-spacing:.14em;
 text-transform:uppercase;color:var(--accent);margin:0 0 14px;}}
h1{{font-family:"Newsreader",Georgia,serif;font-weight:600;
 font-size:clamp(2rem,5.5vw,2.9rem);line-height:1.05;margin:0 0 12px;
 letter-spacing:-.015em;}}
.unterzeile{{font-family:"Newsreader",Georgia,serif;font-size:1.12rem;
 color:var(--ink-soft);margin:0;max-width:60ch;}}
.methode{{font-family:"IBM Plex Mono",monospace;font-size:11px;
 color:var(--ink-faint);padding-top:12px;margin:0 0 44px;}}
section{{margin-bottom:52px;}}
h2{{font-family:"Newsreader",Georgia,serif;font-weight:600;font-size:1.55rem;
 margin:0 0 4px;}}
.hinweis{{font-size:.92rem;color:var(--ink-faint);margin:0 0 24px;
 padding-bottom:12px;border-bottom:1px solid var(--line);max-width:64ch;}}
.thema{{background:var(--surface);border:1px solid var(--line);
 padding:22px 24px;margin-bottom:14px;}}
.kopf{{display:flex;gap:16px;align-items:flex-start;margin-bottom:14px;}}
.nr{{font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--ink-faint);
 padding-top:6px;}}
.thema h3{{font-family:"Newsreader",Georgia,serif;font-weight:600;
 font-size:1.3rem;line-height:1.22;margin:0;flex:1;text-wrap:balance;}}
.zaehler{{display:flex;flex-direction:column;align-items:flex-end;gap:5px;
 min-width:92px;padding-top:4px;}}
.zaehler b{{font-family:"IBM Plex Mono",monospace;font-size:1.1rem;
 font-weight:500;color:var(--accent);line-height:1;
 font-variant-numeric:tabular-nums;}}
.zaehler span{{font-family:"IBM Plex Mono",monospace;font-size:9.5px;
 letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);}}
.balken{{width:92px;height:4px;background:var(--bar-bg);}}
.balken i{{display:block;height:100%;background:var(--accent);}}
ul.belege,ul.einzeln{{list-style:none;margin:0;padding:14px 0 0;
 border-top:1px solid var(--line-soft);display:flex;flex-direction:column;}}
ul.einzeln{{border-top:none;padding-top:0;}}
ul.belege li,ul.einzeln li{{border-bottom:1px solid var(--line-soft);}}
ul.belege li:last-child,ul.einzeln li:last-child{{border-bottom:none;}}
ul.belege a,ul.einzeln a{{display:grid;grid-template-columns:125px 1fr;gap:14px;
 padding:9px 0;text-decoration:none;color:var(--ink-soft);
 transition:color .12s;}}
ul.belege a:hover,ul.einzeln a:hover{{color:var(--accent);}}
ul.belege a:focus-visible,ul.einzeln a:focus-visible{{outline:2px solid var(--accent);
 outline-offset:2px;}}
.medium{{font-family:"IBM Plex Mono",monospace;font-size:11px;
 letter-spacing:.04em;color:var(--ink-faint);padding-top:3px;}}
.schlagzeile{{font-size:.95rem;}}
.spalten{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
 gap:14px;}}
.spalte{{background:var(--surface);border:1px solid var(--line);padding:16px 18px;}}
.spalte h4{{font-family:"IBM Plex Mono",monospace;font-size:10.5px;
 letter-spacing:.1em;text-transform:uppercase;color:var(--accent);
 margin:0 0 10px;font-weight:500;}}
.spalte ol{{margin:0;padding-left:18px;font-size:.9rem;}}
.spalte li{{margin-bottom:8px;}}
.spalte li:last-child{{margin:0;}}
.spalte a{{color:var(--ink-soft);text-decoration:none;}}
.spalte a:hover{{color:var(--accent);}}
.fehlt{{color:var(--ink-faint);list-style:none;margin-left:-18px;}}
.warnung{{background:var(--warn-bg);border-left:3px solid var(--warn);
 padding:16px 20px;font-size:.92rem;}}
.warnung p{{margin:0 0 8px;}}
.warnung ul{{margin:0;padding-left:20px;}}
.ok{{font-size:.92rem;color:var(--ok);margin:0;}}
.leer{{color:var(--ink-soft);}}
footer{{border-top:1px solid var(--line);padding-top:18px;font-size:.83rem;
 color:var(--ink-faint);max-width:66ch;}}
@media (max-width:520px){{
  ul.belege a,ul.einzeln a{{grid-template-columns:1fr;gap:2px;}}
  .medium{{padding-top:0;}}
}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <p class="datum">{stand.strftime('%A, %d. %B %Y')} &middot; {stand.strftime('%H:%M')} Uhr</p>
  <h1>Presseschau</h1>
  <p class="unterzeile">Sortiert danach, wie viele Redaktionen dasselbe Thema führen.</p>
</header>
<p class="methode">{gesamt} Meldungen aus {len(pro_quelle)} Quellen &middot; Zeitfenster {stunden} Stunden</p>

<section>
  <h2>Was mehrere bringen</h2>
  <p class="hinweis">Der Balken zeigt die Zahl der Redaktionen. Darunter jede Schlagzeile einzeln — so siehst du, wie unterschiedlich dieselbe Meldung betitelt wird.</p>
  {themenblock}
</section>

<section>
  <h2>Die Aufmacher je Medium</h2>
  <p class="hinweis">Die jeweils ersten drei Meldungen aus jedem Feed, unabhängig vom Ranking oben.</p>
  <div class="spalten">{spaltenblock}</div>
</section>

<section>
  <h2>Nur bei einem Haus</h2>
  <p class="hinweis">Meldungen, die heute sonst niemand führt.</p>
  <ul class="einzeln">{einzelzeilen}</ul>
</section>

<section>
  <h2>Quellenstatus</h2>
  <p class="hinweis">Damit du merkst, wenn ein Feed stillschweigend ausfällt.</p>
  {statusblock}
</section>

<footer>
  Automatisch erzeugt am {stand.strftime('%d.%m.%Y um %H:%M')} Uhr.
  Ausgegeben werden ausschließlich Überschriften, Medienname und Link —
  kein Artikeltext. Zusammengefasst wird nichts.
</footer>

</div>
</body>
</html>
"""


# -------------------------------------------------------------------- Lauf

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=26,
                        help="Zeitfenster in Stunden (Standard 26)")
    parser.add_argument("--open", action="store_true",
                        help="Seite danach im Browser oeffnen")
    args = parser.parse_args()

    stand = datetime.now(BERLIN)
    grenze = stand - timedelta(hours=args.hours)

    alle: list[dict] = []
    pro_quelle: dict[str, list[dict]] = {}
    fehler: dict[str, str] = {}

    for quelle in lade_quellen():
        eintraege, problem = hole_feed(quelle)
        if problem:
            fehler[quelle["name"]] = problem
            print(f"  [!] {quelle['name']}: {problem}", file=sys.stderr)
            continue
        frisch = [a for a in eintraege if a["zeit"] is None or a["zeit"] >= grenze]
        pro_quelle[quelle["name"]] = frisch or eintraege[:3]
        alle.extend(frisch)
        print(f"  [+] {quelle['name']}: {len(frisch)} Meldungen")

    if not alle:
        print("Keine Meldungen geladen — Abbruch.", file=sys.stderr)
        return 1

    cluster = sortiere_cluster(bilde_cluster(alle))
    seite = baue_seite(cluster, pro_quelle, fehler, stand, args.hours)

    DOCS.mkdir(exist_ok=True)
    ARCHIV.mkdir(exist_ok=True)
    DATEN.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(seite, encoding="utf-8")
    (ARCHIV / f"{stand:%Y-%m-%d}.html").write_text(seite, encoding="utf-8")

    # Der Datenstand getrennt von der Darstellung: daraus baut send_mail.py
    # die Mail, und jede weitere Ausgabe (RSS, App, ...) koennte es ebenso.
    datenstand = {
        "stand": stand.isoformat(),
        "stunden": args.hours,
        "fehler": fehler,
        "themen": [
            {
                "titel": gruppe[0]["titel"],
                "medien": sorted({a["quelle"] for a in gruppe}),
                "artikel": [
                    {"quelle": a["quelle"], "titel": a["titel"], "link": a["link"]}
                    for a in gruppe
                ],
            }
            for gruppe in cluster
        ],
        "pro_quelle": {
            quelle: [{"titel": a["titel"], "link": a["link"]} for a in liste[:3]]
            for quelle, liste in pro_quelle.items()
        },
    }
    inhalt = json.dumps(datenstand, ensure_ascii=False, indent=2)
    (DATEN / "latest.json").write_text(inhalt, encoding="utf-8")
    (DATEN / f"{stand:%Y-%m-%d}.json").write_text(inhalt, encoding="utf-8")

    mehrfach = sum(1 for g in cluster if len({a['quelle'] for a in g}) >= 2)
    print(f"\n{len(alle)} Meldungen, {len(cluster)} Themen, "
          f"davon {mehrfach} mit mehreren Medien.")
    print(f"Geschrieben: {DOCS / 'index.html'}")

    if args.open:
        import webbrowser
        webbrowser.open((DOCS / "index.html").as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
