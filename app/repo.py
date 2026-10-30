"""Zugriff auf Mitglieder, Plätze, Runden und Einstellungen."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from difflib import SequenceMatcher

from .storage import Storage, read_json, read_many, write_json

DEFAULT_SETTINGS = {
    "groups": ["C-Club", "Pinseekers"],
    "allowance": 1.0,  # Anteil des Course Handicaps (1.0 = 100 %, 0.95 = 95 %)
    "missed_round_counts_as_zero": True,
    # Zusatzwertungen innerhalb einer Gruppe; pro Runde wählbar ("Zählt zum C-Club Classic")
    "series": {"C-Club Classic": "C-Club"},
}


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") or "x"


class Repo:
    def __init__(self, st: Storage):
        self.st = st

    # Einstellungen
    def settings(self) -> dict:
        return {**DEFAULT_SETTINGS, **read_json(self.st, "einstellungen.json", {})}

    def save_settings(self, s: dict) -> None:
        write_json(self.st, "einstellungen.json", s)

    # Mitglieder
    def members(self) -> list[dict]:
        return sorted(read_json(self.st, "mitglieder.json", []), key=lambda m: m["name"].lower())

    def member(self, mid: str) -> dict | None:
        return next((m for m in self.members() if m["id"] == mid), None)

    def save_member(self, m: dict) -> dict:
        ms = [x for x in self.members() if x["id"] != m.get("id")]
        m.setdefault("id", new_id())
        ms.append(m)
        write_json(self.st, "mitglieder.json", ms)
        return m

    def save_members(self, ms: list[dict]) -> None:
        """Mehrere Mitglieder auf einmal speichern (eine Dropbox-Datei, ein Schreibvorgang)."""
        by_id = {m["id"]: m for m in self.members()}
        for m in ms:
            m.setdefault("id", new_id())
            by_id[m["id"]] = m
        write_json(self.st, "mitglieder.json", list(by_id.values()))

    def delete_member(self, mid: str) -> None:
        write_json(self.st, "mitglieder.json", [m for m in self.members() if m["id"] != mid])

    def match_member(self, name: str, group: str | None = None) -> tuple[dict | None, float]:
        """Findet das Mitglied, dessen Name (oder Kürzel) am besten passt."""
        cand = [m for m in self.members() if not group or group in m.get("groups", [])] or self.members()
        n = slug(name)
        best, score = None, 0.0
        for m in cand:
            for alias in [m["name"], *m.get("aliases", [])]:
                a = slug(alias)
                s = SequenceMatcher(None, n, a).ratio()
                # Nur Nachname oder Vorname auf der Karte
                parts = a.split("-")
                if n in parts:
                    s = max(s, 0.85)
                if s > score:
                    best, score = m, s
        return best, score

    # Plätze
    def courses(self) -> list[dict]:
        return sorted(read_json(self.st, "plaetze.json", []), key=lambda c: c["name"].lower())

    def course(self, cid: str) -> dict | None:
        return next((c for c in self.courses() if c["id"] == cid), None)

    def save_course(self, c: dict) -> dict:
        cs = [x for x in self.courses() if x["id"] != c.get("id")]
        c.setdefault("id", new_id())
        cs.append(c)
        write_json(self.st, "plaetze.json", cs)
        return c

    def delete_course(self, cid: str) -> None:
        write_json(self.st, "plaetze.json", [c for c in self.courses() if c["id"] != cid])

    # Runden
    def rounds(self, group: str | None = None, year: int | None = None) -> list[dict]:
        out = []
        paths = [f"runden/{name}" for name in self.st.list("runden") if name.endswith(".json")]
        for raw in read_many(self.st, paths):
            r = json.loads(raw) if raw else None
            if r and (not group or r["group"] == group) and (not year or r["date"].startswith(str(year))):
                out.append(r)
        return sorted(out, key=lambda r: (r["date"], r["id"]))

    def round(self, rid: str) -> dict | None:
        return read_json(self.st, f"runden/{rid}.json", None)

    def save_round(self, r: dict) -> dict:
        r.setdefault("id", new_id())
        r.setdefault("players", [])
        write_json(self.st, f"runden/{r['id']}.json", r)
        return r

    def delete_round(self, rid: str) -> None:
        self.st.delete(f"runden/{rid}.json")

    def save_pdf(self, group: str, filename: str, data: bytes) -> str:
        path = f"ranglisten/{slug(group)}/{filename}"
        self.st.write(path, data)
        return path
