# Stableford-App

Web-App fürs Handy, die für die Golfgruppen **C-Club** und **Pinseekers** Stableford-Punkte
berechnet und Ranglisten erstellt.

## Was die App kann

- **Mitglieder** mit Handicap-Index und Gruppe verwalten (inkl. anderer Schreibweisen, wie sie auf Scorekarten stehen).
- **Plätze** mit Par, Stroke Index, Course Rating und Slope je Abschlag. Die App kann die Werte im Netz suchen; das Resultat wird immer in der Eingabemaske zur Kontrolle angezeigt.
- **Scorekarten fotografieren**: Claude liest Namen und Schläge, die App ordnet die Mitglieder zu und holt deren HCP. Vor dem Speichern prüfst du alles in einer Maske. Erfassen von Hand geht auch.
- **Berechnung nach WHS**: Course Handicap = HCP-Index × Slope/113 + (CR − Par), Handicap-Allowance einstellbar (100 % oder 95 %), Schläge nach Stroke Index verteilt, Plus-Handicaps berücksichtigt, 9-Loch-Runden möglich.
- **Tagesrangliste** netto und brutto, Stechen über die letzten 9/6/3/1 Löcher.
- **Jahreswertung** je Gruppe, wahlweise mit Streichresultat.
- **PDF zum Drucken** und **Teilen per WhatsApp** (über das Teilen-Menü des Handys, sonst als Text). Jedes PDF wird automatisch in der Dropbox abgelegt.

## Daten

Alle Daten liegen als Dateien in Dropbox (Ordner `/Stableford`, einstellbar):

```
mitglieder.json, plaetze.json, einstellungen.json
runden/<id>.json
ranglisten/<gruppe>/<datum>_<platz>.pdf, Jahreswertung_<jahr>.pdf
```

Ohne Dropbox-Zugang speichert die App lokal im Ordner `data/` (zum Ausprobieren).

## Einstellungen (Umgebungsvariablen)

| Variable | Zweck |
|---|---|
| `APP_PASSWORD` | Passwort für die App (ohne: kein Login) |
| `SECRET_KEY` | Zufälliger Schlüssel für die Anmeldung (Render erzeugt ihn) |
| `ANTHROPIC_API_KEY` | Für Scorekarten-Erkennung und Platzsuche |
| `CLAUDE_MODEL` | Optional, Standard `claude-opus-5-5` |
| `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN` | Dropbox-Zugang |
| `DROPBOX_FOLDER` | Ordner in Dropbox, Standard `/Stableford` |

### Dropbox einrichten

1. Auf <https://www.dropbox.com/developers/apps> "Create app" → "Scoped access" → "App folder" → Name z.B. `Stableford-Beat`.
2. Unter *Permissions* `files.content.read` und `files.content.write` ankreuzen, "Submit".
3. Unter *Settings* App key und App secret kopieren.
4. App key und App secret bei Render eintragen, dann in der App unter *Einstellungen → Dropbox einrichten* freigeben und den angezeigten Refresh-Token bei Render als `DROPBOX_REFRESH_TOKEN` eintragen.
   (Alternativ ohne App: `python scripts/dropbox_token.py`.)

Mit "App folder" sieht die App nur ihren eigenen Ordner (`Dropbox/Apps/Stableford-Beat/`).

## Auf Render starten

Im Render-Dashboard "New" → "Blueprint" → dieses Repo wählen. `render.yaml` richtet alles ein;
danach die Schlüssel oben unter *Environment* eintragen.

## Entwicklung

```
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload
```
