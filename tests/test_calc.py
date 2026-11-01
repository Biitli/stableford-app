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


def test_season_drop_only_from_min_rounds():
    courses = {"c1": COURSE}
    three = [_round("1", [("A", 0)]), _round("2", [("A", 1)]), _round("3", [("A", 0)])]
    rows = season_ranking(three, courses, drop_worst=True, min_rounds_for_drop=4)
    assert rows[0].total == 90 and rows[0].dropped_index is None
    four = three + [_round("4", [("A", 0)])]
    rows = season_ranking(four, courses, drop_worst=True, min_rounds_for_drop=4)
    assert rows[0].total == 108 and rows[0].dropped_index == 1


def test_merge_duplicate_player(tmp_path):
    from app.repo import Repo
    from app.storage import LocalStorage

    repo = Repo(LocalStorage(tmp_path))
    jv = repo.save_member({"name": "Jean-Vincent Kubista", "hcp": 10, "groups": ["C-Club"], "aliases": []})
    jan = repo.save_member({"name": "Jan Kubista", "hcp": 10, "groups": ["C-Club"], "aliases": ["JK"]})
    r1 = _round("1", [("x", 0)]); r1["players"][0].update(name=jv["name"], member_id=jv["id"])
    r2 = _round("2", [("x", 0)]); r2["players"][0].update(name=jan["name"], member_id=jan["id"])
    r3 = {"id": "3", "group": "C-Club", "date": "2026-05-03", "totals_only": True, "course_id": "",
          "players": [{"name": "Kubista Jan", "member_id": None, "net": 30, "gross": 20}]}
    for r in (r1, r2, r3):
        r["group"] = "C-Club"
        repo.save_round(r)
    assert repo.unlinked_names() == ["Kubista Jan"]
    assert repo.merge_into(jv["id"], f"m:{jan['id']}") == 1
    assert repo.merge_into(jv["id"], "n:Kubista Jan") == 1
    assert repo.member(jan["id"]) is None
    assert set(repo.member(jv["id"])["aliases"]) == {"Jan Kubista", "JK", "Kubista Jan"}
    rows = season_ranking(repo.rounds(), {"c1": COURSE})
    assert [(r.name, r.played, r.total) for r in rows] == [("Jean-Vincent Kubista", 3, 102)]


def test_bogey_hole():
    from app.calc import hole_bogey
    assert hole_bogey(4, 3) == 1
    assert hole_bogey(4, 4) == 0
    assert hole_bogey(4, 5) == -1
    assert hole_bogey(4, 5, received=1) == 0
    assert hole_bogey(4, 4, received=1) == 1
    assert hole_bogey(4, None, received=2) == -1  # aufgehoben = verloren


def test_bogey_round_ranking():
    from app.rankings import daily_ranking, season_ranking, team_ranking

    course = {"id": "c", "holes": [{"par": 4, "si": i + 1} for i in range(9)],
              "tees": [{"name": "Gelb", "cr": 36, "slope": 113}]}
    # A: HCP 0, 3 Birdies, 6 Pars -> +3. B: HCP 9 (1 Schlag/Loch), immer 5 -> 0, aber 2 aufgehoben -> -2.
    rnd = {"format": "bogey", "allowance": 1.0, "tee": "Gelb", "course_id": "c", "players": [
        {"name": "A", "hcp_index": 0, "scores": [3, 3, 3] + [4] * 6},
        {"name": "B", "hcp_index": 18, "scores": [5] * 7 + [None, None]},
    ], "team_size": 2, "teams": [{"name": "T", "players": [0, 1]}]}
    rows = daily_ranking(rnd, course)
    assert [(r.name, r.net, r.gross, r.rank) for r in rows] == [("A", 3, 3, 1), ("B", -2, -9, 2)]
    # Jahreswertung in Stableford-Punkten
    assert [r.sf_net for r in rows] == [21, 14]
    assert season_ranking([rnd], {"c": course}) == []  # zählt nicht zur Jahreswertung
    team = team_ranking(rnd, course)[0]
    assert team["holes"] == [1, 1, 1] + [0] * 6 and team["total"] == 3
