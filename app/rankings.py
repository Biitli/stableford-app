"""Tages- und Jahresranglisten."""

from __future__ import annotations

from dataclasses import dataclass, field

from .calc import CardResult, score_card


def tee_of(course: dict, tee_name: str) -> dict:
    for t in course["tees"]:
        if t["name"] == tee_name:
            return t
    raise ValueError(f"Abschlag '{tee_name}' nicht gefunden")


def score_player(player: dict, course: dict, tee_name: str, allowance: float) -> CardResult:
    tee = tee_of(course, tee_name)
    pars = [h["par"] for h in course["holes"]]
    sis = [h["si"] for h in course["holes"]]
    # Abschläge können eigene Par/SI haben (z.B. Damen)
    if tee.get("pars"):
        pars = tee["pars"]
    if tee.get("sis"):
        sis = tee["sis"]
    return score_card(player["scores"], pars, sis, float(player["hcp_index"]),
                      float(tee["slope"]), float(tee["cr"]), allowance)


@dataclass
class DayRow:
    rank: int
    name: str
    member_id: str | None
    hcp_index: float
    playing_hcp: int
    net: int
    gross: int
    strokes: int | None
    countback: tuple
    gross_rank: int = 0


def daily_ranking(rnd: dict, course: dict) -> list[DayRow]:
    allowance = float(rnd.get("allowance", 1.0))
    rows = []
    for p in rnd["players"]:
        res = score_player(p, course, p.get("tee") or rnd["tee"], allowance)
        rows.append(DayRow(0, p["name"], p.get("member_id"), float(p["hcp_index"]), res.playing_hcp,
                           res.net_total, res.gross_total, res.gross_strokes, res.countback()))
    _assign_ranks(rows, key=lambda r: r.countback, attr="rank")
    _assign_ranks(rows, key=lambda r: (r.gross, r.net), attr="gross_rank")
    rows.sort(key=lambda r: r.rank)
    return rows


def _assign_ranks(rows, key, attr):
    ordered = sorted(rows, key=key, reverse=True)
    prev, rank = None, 0
    for i, r in enumerate(ordered, start=1):
        k = key(r)
        if k != prev:
            rank, prev = i, k
        setattr(r, attr, rank)


@dataclass
class SeasonRow:
    rank: int
    name: str
    key: str
    results: list[int | None]  # Nettopunkte je Runde, None = nicht gespielt
    gross_results: list[int | None]
    total: int
    gross_total: int
    played: int
    dropped_index: int | None = None
    best: int = 0
    extra: dict = field(default_factory=dict)


def season_ranking(rounds: list[dict], courses: dict[str, dict], drop_worst: bool = False,
                   missed_counts_as_zero: bool = True, gross: bool = False) -> list[SeasonRow]:
    """Summe der Stableford-Punkte (netto oder brutto) über alle Runden.

    drop_worst: das schlechteste Resultat wird gestrichen (nur wenn mind. 2 Runden gewertet).
    missed_counts_as_zero: eine verpasste Runde zählt als 0 Punkte und ist damit
    das Streichresultat; sonst wird nur unter gespielten Runden gestrichen.
    """
    players: dict[str, SeasonRow] = {}
    n = len(rounds)
    for i, rnd in enumerate(rounds):
        for row in daily_ranking(rnd, courses[rnd["course_id"]]):
            key = row.member_id or row.name.lower()
            sr = players.get(key)
            if not sr:
                sr = SeasonRow(0, row.name, key, [None] * n, [None] * n, 0, 0, 0)
                players[key] = sr
            sr.results[i] = row.gross if gross else row.net
            sr.gross_results[i] = row.gross

    for sr in players.values():
        sr.played = sum(1 for x in sr.results if x is not None)
        sr.best = max((x for x in sr.results if x is not None), default=0)
        counted = list(enumerate(sr.results))
        if drop_worst and n >= 2:
            if missed_counts_as_zero:
                cands = [(i, x or 0) for i, x in counted]
            else:
                cands = [(i, x) for i, x in counted if x is not None]
            if len(cands) >= 2:
                sr.dropped_index = min(cands, key=lambda c: (c[1], -c[0]))[0]
        sr.total = sum(x or 0 for i, x in counted if i != sr.dropped_index)
        sr.gross_total = sum(x or 0 for i, x in enumerate(sr.gross_results) if i != sr.dropped_index)

    rows = list(players.values())
    _assign_ranks(rows, key=lambda r: (r.total, r.best), attr="rank")
    rows.sort(key=lambda r: (r.rank, r.name.lower()))
    return rows
