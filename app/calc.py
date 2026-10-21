"""Handicap- und Stableford-Berechnung nach World Handicap System (WHS)."""

from __future__ import annotations

import math
from dataclasses import dataclass


def round_half_up(x: float) -> int:
    """WHS rundet .5 immer nach oben (auch bei Plus-Handicaps: -2.5 -> -2)."""
    return math.floor(x + 0.5)


def course_handicap_raw(hcp_index: float, slope: float, cr: float, par: int, holes: int = 18) -> float:
    """Unrundeter Course Handicap.

    18 Loch: HI x Slope/113 + (CR - Par)
    9 Loch:  HI/2 x Slope/113 + (CR - Par)   (CR und Par der 9 Loch)
    """
    hi = hcp_index / 2 if holes == 9 else hcp_index
    return hi * slope / 113 + (cr - par)


def course_handicap(hcp_index: float, slope: float, cr: float, par: int, holes: int = 18) -> int:
    return round_half_up(course_handicap_raw(hcp_index, slope, cr, par, holes))


def playing_handicap(hcp_index: float, slope: float, cr: float, par: int,
                     allowance: float = 1.0, holes: int = 18) -> int:
    """Playing Handicap: unrundeter Course Handicap x Handicap-Allowance, dann gerundet."""
    return round_half_up(course_handicap_raw(hcp_index, slope, cr, par, holes) * allowance)


def strokes_received(playing_hcp: int, stroke_indexes: list[int]) -> list[int]:
    """Verteilt die Vorgabeschläge nach Stroke Index auf die Löcher.

    Bei Plus-Handicap werden Schläge auf den leichtesten Löchern (höchster SI)
    zurückgegeben.
    """
    n = len(stroke_indexes)
    # SI auf 1..n normalisieren (bei 9 Loch mit SI 1..18 nach Rang ordnen)
    order = sorted(range(n), key=lambda i: stroke_indexes[i])
    rank = [0] * n
    for r, i in enumerate(order, start=1):
        rank[i] = r

    if playing_hcp >= 0:
        base, extra = divmod(playing_hcp, n)
        return [base + (1 if rank[i] <= extra else 0) for i in range(n)]

    give_back = -playing_hcp
    base, extra = divmod(give_back, n)
    return [-(base + (1 if rank[i] > n - extra else 0)) for i in range(n)]


def hole_points(par: int, score: int | None, received: int = 0) -> int:
    """Stableford-Punkte eines Lochs. score=None heisst gestrichen/aufgehoben -> 0."""
    if score is None or score <= 0:
        return 0
    return max(0, par + received - score + 2)


@dataclass
class CardResult:
    playing_hcp: int
    course_hcp: int
    received: list[int]
    gross_points: list[int]
    net_points: list[int]
    gross_strokes: int | None  # None, wenn ein Loch fehlt

    @property
    def gross_total(self) -> int:
        return sum(self.gross_points)

    @property
    def net_total(self) -> int:
        return sum(self.net_points)

    def countback(self) -> tuple[int, ...]:
        """Stechen: letzte 9, 6, 3, 1 Löcher (Nettopunkte)."""
        pts = self.net_points
        n = len(pts)
        if n == 18:
            return (self.net_total, sum(pts[9:]), sum(pts[12:]), sum(pts[15:]), pts[17])
        # 9 Loch: letzte 6, 3, 1
        return (self.net_total, sum(pts[3:]), sum(pts[6:]), pts[-1])


def score_card(scores: list[int | None], pars: list[int], stroke_indexes: list[int],
               hcp_index: float, slope: float, cr: float,
               allowance: float = 1.0) -> CardResult:
    holes = len(pars)
    if len(scores) != holes or len(stroke_indexes) != holes:
        raise ValueError("Anzahl Löcher stimmt nicht überein")
    par_total = sum(pars)
    ph = playing_handicap(hcp_index, slope, cr, par_total, allowance, holes)
    ch = course_handicap(hcp_index, slope, cr, par_total, holes)
    rec = strokes_received(ph, stroke_indexes)
    gross = [hole_points(p, s) for p, s in zip(pars, scores)]
    net = [hole_points(p, s, r) for p, s, r in zip(pars, scores, rec)]
    total = None if any(s is None or s <= 0 for s in scores) else sum(scores)
    return CardResult(ph, ch, rec, gross, net, total)
