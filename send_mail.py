#!/usr/bin/env python3
"""
Verschickt die Tagesuebersicht per Brevo an eine Adresse.

Liest docs/data/latest.json (von build.py erzeugt) und schickt daraus eine
schlichte HTML-Mail. Die Darstellung ist bewusst anders als auf der Seite:
E-Mail-Programme koennen weder Webfonts noch moderne CSS-Variablen, deshalb
hier nur Inline-Styles.

Erwartete Umgebungsvariablen:
    BREVO_API_KEY     API-Schluessel aus dem Brevo-Konto
    MAIL_VON          Absenderadresse (muss in Brevo verifiziert sein)
    MAIL_AN           Empfaengeradresse
    SEITEN_URL        optional: Link zur Webversion
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from html import escape
from pathlib import Path

import requests

DATEN = Path(__file__).resolve().parent / "docs" / "data" / "latest.json"
BREVO = "https://api.brevo.com/v3/smtp/email"

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
        "Samstag", "Sonntag"]


def baue_mail(daten: dict, seiten_url: str | None) -> str:
    stand = datetime.fromisoformat(daten["stand"])
    datum = (f"{TAGE[stand.weekday()]}, {stand.day}. "
             f"{MONATE[stand.month - 1]} {stand.year}")

    mehrfach = [t for t in daten["themen"] if len(t["medien"]) >= 2]

    bloecke = []
    for nummer, thema in enumerate(mehrfach[:12], start=1):
        belege = "".join(
            f'<div style="margin:0 0 6px;font-size:14px;line-height:1.45;">'
            f'<span style="color:#7A8592;font-family:monospace;font-size:11px;">'
            f'{escape(a["quelle"])}</span><br>'
            f'<a href="{escape(a["link"])}" '
            f'style="color:#125C6E;text-decoration:none;">'
            f'{escape(a["titel"])}</a></div>'
            for a in thema["artikel"]
        )
        bloecke.append(
            f'<div style="border:1px solid #DDE2E8;padding:16px 18px;'
            f'margin:0 0 12px;background:#FFFFFF;">'
            f'<div style="font-family:monospace;font-size:11px;color:#125C6E;'
            f'letter-spacing:1px;margin:0 0 6px;">'
            f'{nummer:02d} &middot; {len(thema["medien"])} MEDIEN</div>'
            f'<div style="font-size:18px;font-weight:600;line-height:1.25;'
            f'margin:0 0 12px;color:#161B22;">{escape(thema["titel"])}</div>'
            f'{belege}</div>'
        )

    if not bloecke:
        bloecke.append(
            '<p style="color:#4B5563;">Heute hat kein Thema zwei oder mehr '
            'Redaktionen gleichzeitig beschäftigt. Vermutlich hat ein Feed '
            'nicht geladen.</p>'
        )

    # Einzelmeldungen knapp darunter
    einzeln = [t for t in daten["themen"] if len(t["medien"]) == 1][:12]
    einzelzeilen = "".join(
        f'<li style="margin:0 0 7px;font-size:14px;">'
        f'<span style="color:#7A8592;font-family:monospace;font-size:11px;">'
        f'{escape(t["artikel"][0]["quelle"])}</span> '
        f'<a href="{escape(t["artikel"][0]["link"])}" '
        f'style="color:#125C6E;text-decoration:none;">'
        f'{escape(t["titel"])}</a></li>'
        for t in einzeln
    )

    hinweis = ""
    if daten.get("fehler"):
        namen = ", ".join(escape(n) for n in daten["fehler"])
        hinweis = (f'<p style="background:#F7EEDC;border-left:3px solid #9A6109;'
                   f'padding:12px 14px;font-size:13px;color:#4B5563;margin:24px 0 0;">'
                   f'Nicht geladen: {namen}</p>')

    weblink = ""
    if seiten_url:
        weblink = (f'<p style="font-size:13px;margin:0 0 24px;">'
                   f'<a href="{escape(seiten_url)}" style="color:#125C6E;">'
                   f'Vollständige Übersicht im Browser</a></p>')

    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px 16px;background:#F6F7F9;
 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;
 color:#161B22;">
<div style="max-width:620px;margin:0 auto;">
  <div style="border-bottom:2px solid #161B22;padding-bottom:14px;margin-bottom:8px;">
    <div style="font-family:monospace;font-size:11px;letter-spacing:1.5px;
     color:#125C6E;text-transform:uppercase;margin-bottom:8px;">📰 {datum}</div>
    <div style="font-size:30px;font-weight:600;line-height:1.1;">Presseschau</div>
  </div>
  <p style="font-size:13px;color:#7A8592;margin:0 0 24px;">
    Sortiert danach, wie viele Redaktionen dasselbe Thema führen.</p>
  {weblink}
  {''.join(bloecke)}
  <div style="font-size:15px;font-weight:600;margin:28px 0 10px;">
    Nur bei einem Haus</div>
  <ul style="padding-left:18px;margin:0;color:#4B5563;">{einzelzeilen}</ul>
  {hinweis}
  <p style="font-size:12px;color:#7A8592;border-top:1px solid #DDE2E8;
   padding-top:14px;margin-top:28px;">
    Automatisch erzeugt am {stand.strftime('%d.%m.%Y um %H:%M')} Uhr.
    Nur Überschriften und Links, kein Artikeltext.</p>
</div></body></html>"""


def main() -> int:
    schluessel = os.environ.get("BREVO_API_KEY")
    von = os.environ.get("MAIL_VON")
    an = os.environ.get("MAIL_AN")
    if not (schluessel and von and an):
        print("BREVO_API_KEY, MAIL_VON und MAIL_AN muessen gesetzt sein.",
              file=sys.stderr)
        return 1

    if not DATEN.exists():
        print(f"Kein Datenstand unter {DATEN} — erst build.py laufen lassen.",
              file=sys.stderr)
        return 1

    daten = json.loads(DATEN.read_text(encoding="utf-8"))
    stand = datetime.fromisoformat(daten["stand"])
    mehrfach = sum(1 for t in daten["themen"] if len(t["medien"]) >= 2)

    antwort = requests.post(
        BREVO,
        headers={"api-key": schluessel, "content-type": "application/json"},
        json={
            "sender": {"email": von, "name": "Presseschau"},
            "to": [{"email": an}],
            "subject": f"Presseschau {stand:%d.%m.} — {mehrfach} Themen",
            "htmlContent": baue_mail(daten, os.environ.get("SEITEN_URL")),
        },
        timeout=30,
    )

    if antwort.status_code >= 300:
        print(f"Brevo antwortete {antwort.status_code}: {antwort.text}",
              file=sys.stderr)
        return 1

    print(f"Mail an {an} verschickt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
