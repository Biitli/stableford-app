"""Tages- und Jahresranglisten."""

from __future__ import annotations

from dataclasses import dataclass, field

from .calc import CardResult, score_card


FORMATS = {"stableford": "Stableford", "bogey": "Bogey Competition"}


def is_bogey(rnd: dict) -> bool:
    return rnd.get("format") == "bogey"


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
    playing_hcp: int | None  # None bei nachgetragenen Totalen
    net: int
    gross: int | None
    strokes: int | None
    countback: tuple
    gross_rank: int = 0
    birdies: int = 0  # Birdies oder besser
    ntp: int = 0  # Nearest to the Pin
    ld: int = 0  # Longest Drive
    sf_net: int | None = None  # Stableford-Punkte für die Jahreswertung (auch bei Bogey-Runden)
    sf_gross: int | None = None


def _count(v) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def extras_of(p: dict, auto_birdies: int = 0) -> dict:
    """Birdies, NTP, LD eines Spielers. Birdies: von Hand erfasst, sonst aus der Scorekarte gezählt."""
    b = p.get("birdies")
    return {"birdies": auto_birdies if b is None else _count(b), "ntp": _count(p.get("ntp")), "ld": _count(p.get("ld"))}


def daily_ranking(rnd: dict, course: dict) -> list[DayRow]:
    allowance = float(rnd.get("allowance", 1.0))
    rows = []
    for p in rnd["players"]:
        if p.get("net") is not None:
            # Nachgetragenes Resultat ohne Scorekarte: nur Totale bekannt
            net = int(p["net"])
            rows.append(DayRow(0, p["name"], p.get("member_id"), float(p.get("hcp_index") or 0), None,
                               net, p.get("gross"), None, (net,), **extras_of(p),
                               sf_net=net, sf_gross=p.get("gross")))
            continue
        res = score_player(p, course, p.get("tee") or rnd["tee"], allowance)
        if is_bogey(rnd):
            net, gross, cb = sum(res.net_bogey), sum(res.gross_bogey), _countback(res.net_bogey)
        else:
            net, gross, cb = res.net_total, res.gross_total, res.countback()
        rows.append(DayRow(0, p["name"], p.get("member_id"), float(p["hcp_index"]), res.playing_hcp,
                           net, gross, res.gross_strokes, cb,
                           **extras_of(p, sum(1 for g in res.gross_points if g >= 3)),
                           sf_net=res.net_total, sf_gross=res.gross_total))
    _assign_ranks(rows, key=lambda r: r.countback, attr="rank")
    _assign_ranks(rows, key=lambda r: (-1 if r.gross is None else r.gross, r.net), attr="gross_rank")
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
    birdies: int = 0
    ntp: int = 0
    ld: int = 0

    @property
    def raw_total(self) -> int:
        """Total aller Runden, vor dem Streichen."""
        return sum(x or 0 for x in self.results)

    @property
    def dropped_value(self) -> int | None:
        if self.dropped_index is None:
            return None
        return self.results[self.dropped_index] or 0


def season_ranking(rounds: list[dict], courses: dict[str, dict], drop_worst: bool = False,
                   missed_counts_as_zero: bool = True, gross: bool = False,
                   min_rounds_for_drop: int = 2) -> list[SeasonRow]:
    """Summe der Stableford-Punkte (netto oder brutto) über alle Runden.

    drop_worst: das schlechteste Resultat wird gestrichen, sobald mind. min_rounds_for_drop
    Runden in der Wertung sind (Standard 2, beim C-Club 4).
    missed_counts_as_zero: eine verpasste Runde zählt als 0 Punkte und ist damit
    das Streichresultat; sonst wird nur unter gespielten Runden gestrichen.
    """
    rounds = [r for r in rounds if not is_bogey(r)]  # Bogey-Runden zählen nicht zur Jahreswertung
    players: dict[str, SeasonRow] = {}
    n = len(rounds)
    for i, rnd in enumerate(rounds):
        for row in daily_ranking(rnd, courses.get(rnd.get("course_id"))):
            key = row.member_id or row.name.lower()
            sr = players.get(key)
            if not sr:
                sr = SeasonRow(0, row.name, key, [None] * n, [None] * n, 0, 0, 0)
                players[key] = sr
            # Jahreswertung immer in Stableford-Punkten, auch für Bogey-Runden
            sr.results[i] = row.sf_gross if gross else row.sf_net
            sr.birdies += row.birdies
            sr.ntp += row.ntp
            sr.ld += row.ld
            sr.gross_results[i] = row.sf_gross

    for sr in players.values():
        sr.played = sum(1 for x in sr.results if x is not None)
        sr.best = max((x for x in sr.results if x is not None), default=0)
        counted = list(enumerate(sr.results))
        if drop_worst and n >= max(2, min_rounds_for_drop):
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


TEAM_FORMATS = {2: "4-Ball Better Ball", 3: "2 Best of 3", 4: "2 Best of 4"}


def counted_per_hole(team_size: int) -> int:
    """Wie viele Resultate pro Loch zählen: Better Ball (Zweierteam) 1, sonst 2."""
    return 1 if team_size == 2 else 2


def best_n(points: list[list[int]], n: int) -> list[int]:
    """Je Loch die Summe der n besten Resultate."""
    return [sum(sorted(values, reverse=True)[:n]) for values in zip(*points)]


def best_two(points: list[list[int]]) -> list[int]:
    """Je Loch die Summe der zwei besten Resultate."""
    return best_n(points, 2)


def _countback(holes: list[int]) -> tuple[int, ...]:
    cuts = (9, 12, 15, 17) if len(holes) == 18 else (3, 6, 8)
    return (sum(holes), *(sum(holes[c:]) for c in cuts))


def team_ranking(rnd: dict, course: dict) -> list[dict]:
    """Je Loch die besten Stableford-Punktzahlen (netto und brutto) addieren.

    4-Ball Better Ball (Zweierteams): das bessere Resultat pro Loch.
    2 Best of 3 / 2 Best of 4: die zwei höchsten Resultate pro Loch.

    Bei gleichem Total entscheiden wie im Einzel die letzten 9, 6, 3 und 1 Löcher.
    """
    if rnd.get("totals_only"):
        return []
    size = rnd.get("team_size", 3)
    rows = []
    for team in rnd.get("teams", []):
        indexes = team["players"]
        if len(indexes) != size or len(set(indexes)) != size:
            continue
        if any(i < 0 or i >= len(rnd["players"]) for i in indexes):
            continue
        players = [rnd["players"][i] for i in indexes]
        results = [score_player(p, course, p.get("tee") or rnd["tee"], float(rnd.get("allowance", 1.0)))
                   for p in players]
        n = counted_per_hole(size)
        if is_bogey(rnd):
            holes = best_n([r.net_bogey for r in results], n)
            gross_holes = best_n([r.gross_bogey for r in results], n)
        else:
            holes = best_n([r.net_points for r in results], n)
            gross_holes = best_n([r.gross_points for r in results], n)
        rows.append({"name": team["name"], "names": [p["name"] for p in players],
                     "holes": holes, "total": sum(holes), "gross_holes": gross_holes, "gross": sum(gross_holes)})
    for attr, key in (("gross_rank", lambda r: (*_countback(r["gross_holes"]), r["total"])),
                      ("rank", lambda r: _countback(r["holes"]))):
        rows.sort(key=lambda r: r["name"].lower())
        rows.sort(key=key, reverse=True)
        previous, rank = None, 0
        for i, row in enumerate(rows, 1):
            if key(row) != previous:
                rank, previous = i, key(row)
            row[attr] = rank
    return rows
