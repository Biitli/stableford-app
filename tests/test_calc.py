from app.calc import (course_handicap, hole_points, playing_handicap, round_half_up,
                      score_card, strokes_received)
from app.rankings import daily_ranking, season_ranking

PARS = [4, 4, 3, 5, 4, 4, 3, 4, 5, 4, 3, 4, 5, 4, 4, 3, 5, 4]
SIS = [5, 11, 17, 1, 9, 3, 15, 13, 7, 6, 18, 2, 10, 8, 4, 16, 12, 14]
COURSE = {"id": "c1", "name": "Test", "holes": [{"par": p, "si": s} for p, s in zip(PARS, SIS)],
          "tees": [{"name": "Gelb", "cr": 72.0, "slope": 113}]}


def test_round_half_up():
    assert round_half_up(2.5) == 3
    assert round_half_up(-2.5) == -2
    assert round_half_up(2.49) == 2


def test_course_handicap_whs():
    # 18.4 x 130/113 + (71.2 - 72) = 20.37 -> 20
    assert course_handicap(18.4, 130, 71.2, 72) == 20
    assert course_handicap(0, 113, 72, 72) == 0
    # 95 % Allowance wird auf den unrundeten Wert angewendet
    assert playing_handicap(18.4, 130, 71.2, 72, 0.95) == 19


def test_nine_hole_handicap_halves_index():
    assert course_handicap(20.0, 113, 36.0, 36, holes=9) == 10


def test_strokes_distribution():
    rec = strokes_received(20, SIS)
    assert sum(rec) == 20
    assert rec[SIS.index(1)] == 2 and rec[SIS.index(2)] == 2 and rec[SIS.index(3)] == 1
    assert rec[SIS.index(18)] == 1


def test_plus_handicap_gives_back_on_easiest_holes():
    rec = strokes_received(-2, SIS)
    assert sum(rec) == -2
    assert rec[SIS.index(18)] == -1 and rec[SIS.index(17)] == -1


def test_hole_points():
    assert hole_points(4, 4) == 2
    assert hole_points(4, 3) == 3
    assert hole_points(4, 7) == 0
    assert hole_points(4, 5, received=1) == 2
    assert hole_points(4, None, received=1) == 0


def test_score_card_par_round():
    res = score_card(PARS, PARS, SIS, 18.0, 113, 72.0)
    assert res.playing_hcp == 18
    assert res.gross_total == 36
    assert res.net_total == 54
    assert res.gross_strokes == 72


def test_daily_ranking_with_countback():
    a = [p for p in PARS]
    b = [p for p in PARS]
    # beide 36 brutto mit HCP 0; A spielt Bogey vorne, Birdie hinten -> besser im Stechen
    a[0] += 1
    a[17] -= 1
    b[17] += 1
    b[0] -= 1
    rnd = {"tee": "Gelb", "allowance": 1.0, "players": [
        {"name": "B", "member_id": "b", "hcp_index": 0, "scores": b},
        {"name": "A", "member_id": "a", "hcp_index": 0, "scores": a}]}
    rows = daily_ranking(rnd, COURSE)
    assert [r.name for r in rows] == ["A", "B"]
    assert rows[0].net == rows[1].net == 36


def _round(rid, players):
    return {"id": rid, "course_id": "c1", "tee": "Gelb", "allowance": 1.0, "date": "2026-05-0" + rid,
            "players": [{"name": n, "member_id": n, "hcp_index": 0, "scores": [p + d for p in PARS]}
                        for n, d in players]}


def test_season_ranking_drop_worst():
    # d = Schläge über Par auf jedem Loch: 0 -> 36 Punkte, 1 -> 18 Punkte
    rounds = [_round("1", [("A", 0), ("B", 1)]),
              _round("2", [("A", 1), ("B", 0)]),
              _round("3", [("A", 0)])]
    courses = {"c1": COURSE}
    rows = season_ranking(rounds, courses)
    assert [(r.name, r.total) for r in rows] == [("A", 90), ("B", 54)]
    rows = season_ranking(rounds, courses, drop_worst=True)
    # A streicht 18, B streicht die verpasste Runde (0)
    assert [(r.name, r.total) for r in rows] == [("A", 72), ("B", 54)]
    rows = season_ranking(rounds, courses, drop_worst=True, missed_counts_as_zero=False)
    assert [(r.name, r.total) for r in rows] == [("A", 72), ("B", 36)]
