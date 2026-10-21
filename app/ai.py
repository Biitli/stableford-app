"""Claude: Scorekarten lesen und Platzdaten im Netz suchen."""

from __future__ import annotations

import base64
import json
import os

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
BETAS = ["server-side-fallback-2026-07-01"]


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    import anthropic

    return anthropic.Anthropic(api_key="".join(os.environ.get("ANTHROPIC_API_KEY", "").split()))


def _json_text(resp) -> dict:
    if resp.stop_reason == "refusal":
        raise RuntimeError("Die Anfrage wurde abgelehnt.")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


SCORECARD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["players", "course_name", "date", "notes"],
    "properties": {
        "course_name": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"], "description": "YYYY-MM-DD, falls auf der Karte"},
        "notes": {"type": "string", "description": "Unsicherheiten beim Lesen, kurz auf Deutsch"},
        "players": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "scores", "hcp_on_card"],
                "properties": {
                    "name": {"type": "string"},
                    "hcp_on_card": {"type": ["number", "null"]},
                    "scores": {
                        "type": "array",
                        "description": "Schläge pro Loch in Lochreihenfolge, null wenn gestrichen/leer",
                        "items": {"type": ["integer", "null"]},
                    },
                },
            },
        },
    },
}

SCORECARD_PROMPT = """Das ist eine fotografierte Golf-Scorekarte (oft handschriftlich, Schweiz).
Lies für jeden Spieler auf der Karte den Namen und die Anzahl Schläge pro Loch ({holes} Löcher).
- Nimm die Schläge des Spielers, nicht die Spalten für Par, Stroke Index, Punkte oder den Zähler.
- Ein Strich, "X", "-" oder leeres Feld heisst: Loch nicht beendet -> null.
- Ignoriere Summenspalten (OUT/IN/TOT), gib nur die einzelnen Löcher zurück.
- Falls eine Ziffer unsicher ist, nimm die wahrscheinlichste und erwähne es in notes.
Bekannte Spieler dieser Gruppe (zur Orientierung bei der Schreibweise): {names}"""


def read_scorecard(image: bytes, media_type: str, holes: int, known_names: list[str]) -> dict:
    data = base64.standard_b64encode(image).decode()
    resp = _client().beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=BETAS,
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCORECARD_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": SCORECARD_PROMPT.format(holes=holes, names=", ".join(known_names) or "-")},
        ]}],
    )
    result = _json_text(resp)
    for p in result["players"]:
        s = (p["scores"] + [None] * holes)[:holes]
        p["scores"] = s
    return result


COURSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["found", "name", "holes", "tees", "source"],
    "properties": {
        "found": {"type": "boolean"},
        "name": {"type": "string"},
        "source": {"type": "string", "description": "URL der Quelle"},
        "holes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["par", "si"],
                "properties": {"par": {"type": "integer"}, "si": {"type": "integer"}},
            },
        },
        "tees": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "cr", "slope"],
                "properties": {"name": {"type": "string"}, "cr": {"type": "number"}, "slope": {"type": "integer"}},
            },
        },
    },
}


def lookup_course(query: str) -> dict:
    """Sucht Par, Stroke Index, Course Rating und Slope eines Golfplatzes im Netz.

    Das Resultat ist nur ein Vorschlag: es wird in der Eingabemaske angezeigt und muss
    bestätigt werden.
    """
    client = _client()
    messages = [{"role": "user", "content": (
        f"Suche die Platzdaten für den Golfplatz: {query}.\n"
        "Gesucht: Par und Stroke Index (Handicap) aller Löcher sowie Course Rating und Slope "
        "für jeden Abschlag (Herren und Damen, z.B. 'Gelb Herren', 'Rot Damen'). "
        "Bevorzuge offizielle Quellen (Clubwebsite, Scorekarte, Swiss Golf). "
        "Wenn du die Daten nicht verlässlich findest, setze found=false und lass die Listen leer.")}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    for _ in range(5):
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=16000, betas=BETAS, fallbacks="default", tools=tools,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": COURSE_SCHEMA}},
            messages=messages,
        )
        if resp.stop_reason != "pause_turn":
            return _json_text(resp)
        messages.append({"role": "assistant", "content": resp.content})
    raise RuntimeError("Die Suche hat zu lange gedauert.")


CARD_COURSE_PROMPT = """Das ist eine fotografierte Golf-Scorekarte (Schweiz).
Lies die Platzdaten ab, nicht die Schläge der Spieler:
- Name des Golfplatzes (oder Clubs)
- Par und Stroke Index (oft "Hcp", "HCP" oder "Vorgabe" genannt) für jedes Loch in Lochreihenfolge
- falls aufgedruckt: Course Rating (CR) und Slope je Abschlag, mit Abschlagfarbe und Herren/Damen
Gibt es getrennte Par- oder Hcp-Zeilen für Herren und Damen, nimm die Herren-Werte.
Wenn CR oder Slope nicht auf der Karte stehen, lass die Liste tees leer.
Unsicherheiten kurz auf Deutsch in notes."""

CARD_COURSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "holes", "tees", "notes"],
    "properties": {
        "name": {"type": "string"},
        "notes": {"type": "string"},
        "holes": COURSE_SCHEMA["properties"]["holes"],
        "tees": COURSE_SCHEMA["properties"]["tees"],
    },
}


def read_course_card(image: bytes, media_type: str) -> dict:
    """Liest Par, Stroke Index und (falls aufgedruckt) CR/Slope von einer Scorekarte."""
    data = base64.standard_b64encode(image).decode()
    resp = _client().beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=BETAS,
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": CARD_COURSE_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": CARD_COURSE_PROMPT},
        ]}],
    )
    return _json_text(resp)
