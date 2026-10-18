"""Testlauf ohne Netz: simuliert Feeds und prueft Clustering + Ausgabe."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

JETZT = datetime.now(build.BERLIN)

# Dieselbe Nachricht, unterschiedlich betitelt, plus ein paar Einzelmeldungen.
ROH = [
    ("tagesschau", "Bundestag beschließt Reform der Krankenhausfinanzierung"),
    ("ZDFheute", "Krankenhausreform: Bundestag beschließt neue Finanzierung"),
    ("Spiegel", "Bundestag beschließt Krankenhausreform gegen Widerstand der Länder"),
    ("Süddeutsche", "Krankenhausreform im Bundestag beschlossen"),
    ("FAZ", "Bundestag stimmt für Krankenhausreform"),

    ("tagesschau", "Merz kündigt Gespräche mit Frankreich über Verteidigung an"),
    ("Welt", "Merz reist nach Paris: Gespräche über europäische Verteidigung"),
    ("Zeit Online", "Verteidigung: Merz trifft Macron in Paris"),

    ("taz", "Streit um Tarifabschluss im öffentlichen Dienst"),
    ("Deutschlandfunk", "Öffentlicher Dienst: Tarifverhandlungen vertagt"),

    ("Spiegel", "Vulkanausbruch auf Island zwingt Hunderte zur Flucht"),
    ("taz", "Debatte über Lieferkettengesetz geht weiter"),
    ("FAZ", "Dax schließt leichter"),
    ("Welt", "Neue Studie zu Schlafmangel bei Jugendlichen"),
    ("Zeit Online", "Wie sich das Rentenniveau bis 2040 entwickeln könnte"),
]

artikel = []
pro_quelle = {}
for i, (quelle, titel) in enumerate(ROH):
    eintrag = {
        "titel": titel,
        "link": f"https://example.org/{i}",
        "quelle": quelle,
        "art": "test",
        "zeit": JETZT - timedelta(minutes=i * 17),
    }
    artikel.append(eintrag)
    pro_quelle.setdefault(quelle, []).append(eintrag)

cluster = build.sortiere_cluster(build.bilde_cluster(artikel))

print("=== Cluster ===")
for gruppe in cluster:
    medien = sorted({a["quelle"] for a in gruppe})
    print(f"[{len(medien)}] {gruppe[0]['titel']}")
    for a in gruppe[1:]:
        print(f"      + {a['quelle']}: {a['titel']}")

seite = build.baue_seite(
    cluster, pro_quelle,
    {"Süddeutsche": "HTTPError: 403 Client Error"},
    JETZT, 26,
)
ziel = Path(__file__).resolve().parent / "docs" / "test.html"
ziel.parent.mkdir(exist_ok=True)
ziel.write_text(seite, encoding="utf-8")
print(f"\nHTML: {ziel} ({len(seite)} Zeichen)")
