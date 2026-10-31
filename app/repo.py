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
    # Ab wie vielen Runden das Streichresultat abgezogen wird, pro Gesamtwertung bzw. Serie (sonst 2)
    "drop_min_rounds": {"C-Club": 4},
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

    def unlinked_names(self) -> list[str]:
        """Spielernamen aus Runden, die keinem Mitglied zugeordnet sind."""
        names = {}
        for r in self.rounds():
            for p in r.get("players", []):
                if not p.get("member_id") and p.get("name"):
                    names.setdefault(slug(p["name"]), p["name"])
        return sorted(names.values(), key=str.lower)

    def merge_into(self, target_id: str, source: str) -> int:
        """Legt einen doppelten Eintrag mit dem Mitglied target_id zusammen.

        source = "m:<Mitglied-ID>" (anderes Mitglied, wird danach gelöscht) oder
        "n:<Name>" (nicht zugeordneter Name in Runden). Alle Runden werden umgeschrieben,
        der alte Name wird als andere Schreibweise gespeichert. Gibt die Anzahl Runden zurück.
        """
        target = self.member(target_id)
        kind, _, value = source.partition(":")
        if not target or not value:
            return 0
        src_member = self.member(value) if kind == "m" else None
        if kind == "m" and (not src_member or value == target_id):
            return 0
        old_name = src_member["name"] if src_member else value

        def is_source(p: dict) -> bool:
            if src_member:
                return p.get("member_id") == src_member["id"]
            return not p.get("member_id") and slug(p.get("name", "")) == slug(old_name)

        changed = 0
        for r in self.rounds():
            hit = False
            for p in r.get("players", []):
                if is_source(p):
                    p.setdefault("name_in_list", p.get("name"))
                    p["member_id"], p["name"] = target["id"], target["name"]
                    hit = True
            if hit:
                self.save_round(r)
                changed += 1
        aliases = target.setdefault("aliases", [])
        for a in [old_name, *(src_member or {}).get("aliases", [])]:
            if slug(a) != slug(target["name"]) and slug(a) not in {slug(x) for x in aliases}:
                aliases.append(a)
        if src_member:
            for g in src_member.get("groups", []):
                if g not in target.setdefault("groups", []):
                    target["groups"].append(g)
        self.save_member(target)
        if src_member:
            self.delete_member(src_member["id"])
        return changed

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
