import re

import pytest
from fastapi.testclient import TestClient

from app import ai, main
from app.repo import Repo
from app.storage import LocalStorage

PARS = [4, 4, 3, 5, 4, 4, 3, 4, 5, 4, 3, 4, 5, 4, 4, 3, 5, 4]
SIS = [5, 11, 17, 1, 9, 3, 15, 13, 7, 6, 18, 2, 10, 8, 4, 16, 12, 14]


@pytest.fixture
def client(tmp_path):
    main.set_repo(Repo(LocalStorage(tmp_path)))
    return TestClient(main.app)


def course_form():
    f = {"name": "Testplatz", "holes": "18", "tee0": "Gelb Herren", "cr0": "71,2", "slope0": "130",
         "tee1": "Rot Damen", "cr1": "73.0", "slope1": "128"}
    for i, (p, s) in enumerate(zip(PARS, SIS)):
        f[f"par{i}"], f[f"si{i}"] = str(p), str(s)
    return f


def test_full_flow(client, monkeypatch, tmp_path):
    assert client.get("/").status_code == 200
    client.post("/mitglieder", data={"name": "Beat Bieler", "hcp": "18,4", "groups": ["C-Club"]})
    client.post("/mitglieder", data={"name": "Anna Muster", "hcp": "10", "groups": ["C-Club"], "ladies": "1"})
    assert "Beat Bieler" in client.get("/mitglieder").text

    r = client.post("/plaetze", data=course_form())
    assert r.status_code == 200 and "Testplatz" in r.text
    c = main.repo.courses()[0]

    r = client.post("/runden", data={"group": "C-Club", "date": "2026-05-01", "course_tee": f"{c['id']}|Gelb Herren"})
    rid = r.url.path.rsplit("/", 1)[1]

    def fake_read(img, mt, holes, names):
        return {"course_name": None, "date": None, "notes": "",
                "players": [{"name": "Bieler", "hcp_on_card": None, "scores": PARS},
                            {"name": "Anna M.", "hcp_on_card": None, "scores": [p + 1 for p in PARS]}]}

    monkeypatch.setattr(ai, "read_scorecard", fake_read)
    monkeypatch.setattr(ai, "available", lambda: True)
    r = client.post(f"/runden/{rid}/foto", files={"photos": ("k.jpg", b"x", "image/jpeg")})
    assert r.status_code == 200
    assert 'selected>Beat Bieler' in r.text.replace('" selected', ' selected').replace('data-hcp="18.4" ', '')
    assert "Rot Damen" in r.text

    ms = {m["name"]: m for m in main.repo.members()}
    form = {"count": "2", "replace": "",
            "member0": ms["Beat Bieler"]["id"], "hcp0": "18.4", "tee0": "Gelb Herren",
            "member1": ms["Anna Muster"]["id"], "hcp1": "10", "tee1": "Rot Damen"}
    for h, p in enumerate(PARS):
        form[f"s0_{h}"] = str(p)
        form[f"s1_{h}"] = str(p + 1)
    r = client.post(f"/runden/{rid}/spieler", data=form)
    assert r.status_code == 200
    # Beat: Spiel-HCP 20 -> 36 + 20 = 56 Punkte netto
    assert "<b>56</b>" in r.text

    r = client.get(f"/runden/{rid}/pdf")
    assert r.headers["content-type"] == "application/pdf"
    v = client.get(f"/runden/{rid}/pdf/ansicht")
    assert v.status_code == 200 and "Zurück zur App" in v.text and f'href="/runden/{rid}"' in v.text
    v = client.get("/jahr/C-Club/2026/pdf/ansicht?streich=1&brutto=0")
    assert v.status_code == 200 and 'href="/jahr/C-Club/2026?streich=1&amp;brutto=0"' in v.text
    assert list((tmp_path / "ranglisten" / "c-club").iterdir())

    r = client.get("/jahr/C-Club/2026?streich=1")
    assert r.status_code == 200 and "Beat Bieler" in r.text
    assert client.get("/jahr/C-Club/2026/pdf?streich=1").status_code == 200
    assert client.get(f"/runden/{rid}/karte/0").status_code == 200


def test_course_validation(client):
    f = course_form()
    f["si1"] = "5"  # doppelter SI
    r = client.post("/plaetze", data=f)
    assert "genau einmal" in r.text


def test_member_import(client, tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Handicap C-Club", None])
    ws.append([None, None])
    ws.append(["Hans Schlatter", 16.2])
    ws.append(["Beat Bieler", 13.8])
    ws.append(["Plus Spieler", "+1,2"])
    p = tmp_path / "hcp.xlsx"
    wb.save(p)
    client.post("/mitglieder", data={"name": "Beat Bieler", "hcp": "18", "groups": ["Pinseekers"]})
    r = client.post("/mitglieder/import", data={"group": "C-Club"},
                    files={"file": ("hcp.xlsx", p.read_bytes(), "application/octet-stream")})
    assert "2 neu erfasst, 1 aktualisiert" in r.text
    ms = {m["name"]: m for m in main.repo.members()}
    assert ms["Beat Bieler"]["hcp"] == 13.8
    assert ms["Beat Bieler"]["groups"] == ["Pinseekers", "C-Club"]
    assert ms["Plus Spieler"]["hcp"] == -1.2


def test_gross_views(client):
    client.post("/mitglieder", data={"name": "Beat Bieler", "hcp": "18", "groups": ["C-Club"]})
    client.post("/plaetze", data=course_form())
    c = main.repo.courses()[0]
    r = client.post("/runden", data={"group": "C-Club", "date": "2026-05-01", "course_tee": f"{c['id']}|Gelb Herren"})
    rid = r.url.path.rsplit("/", 1)[1]
    form = {"count": "1", "replace": "", "member0": main.repo.members()[0]["id"], "hcp0": "18", "tee0": "Gelb Herren"}
    form.update({f"s0_{h}": str(p) for h, p in enumerate(PARS)})
    r = client.post(f"/runden/{rid}/spieler", data=form)
    assert "<h2>Brutto</h2>" in r.text and "*Brutto*" in r.text
    r = client.get("/jahr/C-Club/2026?brutto=1")
    assert "<b>36</b>" in r.text
    assert client.get("/jahr/C-Club/2026/pdf?brutto=1&streich=1").status_code == 200


def test_course_from_photo(client, monkeypatch):
    found = {"name": "Wylihof", "notes": "", "tees": [],
             "holes": [{"par": p, "si": s} for p, s in zip(PARS, SIS)]}
    monkeypatch.setattr(ai, "read_course_card", lambda img, mt: found)
    r = client.post("/plaetze/foto", files={"photo": ("k.jpg", b"x", "image/jpeg")})
    assert 'value="Wylihof"' in r.text and "Course Rating und Slope stehen nicht" in r.text
    assert 'name="si3" value="1"' in r.text


def test_tee_must_be_chosen(client, monkeypatch):
    client.post("/mitglieder", data={"name": "Beat Bieler", "hcp": "18", "groups": ["C-Club"]})
    client.post("/plaetze", data=course_form())
    c = main.repo.courses()[0]
    r = client.post("/runden", data={"group": "C-Club", "date": "2026-05-01", "course": c["id"]})
    rid = r.url.path.rsplit("/", 1)[1]
    monkeypatch.setattr(ai, "read_scorecard", lambda *a: {"notes": "", "players": [
        {"name": "Bieler", "hcp_on_card": None, "scores": PARS}, {"name": "Gast X", "hcp_on_card": 20, "scores": PARS}]})
    r = client.post(f"/runden/{rid}/foto", files={"photos": ("k.jpg", b"x", "image/jpeg")})
    radios = re.findall(r'<input type="radio" name="tee0"[^>]*>', r.text)
    assert len(radios) == 2 and not any("checked" in x for x in radios)  # nichts vorausgewählt
    assert "Abschlag für alle Spieler setzen" in r.text
    form = {"count": "1", "replace": "", "member0": main.repo.members()[0]["id"], "hcp0": "18", "tee0": "Rot Damen"}
    form.update({f"s0_{h}": str(p) for h, p in enumerate(PARS)})
    client.post(f"/runden/{rid}/spieler", data=form)
    assert main.repo.round(rid)["players"][0]["tee"] == "Rot Damen"


def test_hcp_list_edit_and_export(client):
    client.post("/mitglieder", data={"name": "Beat Bieler", "hcp": "13.8", "groups": ["C-Club"]})
    client.post("/mitglieder", data={"name": "Pin Seeker", "hcp": "20", "groups": ["Pinseekers"]})
    ms = {m["name"]: m for m in main.repo.members()}
    r = client.get("/mitglieder?gruppe=C-Club")
    assert "Beat Bieler" in r.text and "Pin Seeker" not in r.text
    r = client.post("/mitglieder/hcp", data={"gruppe": "C-Club", f"hcp_{ms['Beat Bieler']['id']}": "12,9"})
    assert "1 Handicap(s) gespeichert" in r.text
    m = main.repo.member(ms["Beat Bieler"]["id"])
    assert m["hcp"] == 12.9 and m["hcp_updated"]
    assert main.repo.member(ms["Pin Seeker"]["id"])["hcp"] == 20
    r = client.get("/mitglieder/excel?gruppe=C-Club")
    assert r.headers["content-type"].startswith("application/vnd.openxml")
    client.post(f"/mitglieder/{ms['Pin Seeker']['id']}/loeschen", data={"gruppe": "Pinseekers"})
    assert len(main.repo.members()) == 1


def test_broken_dropbox_shows_explanation(client):
    from dropbox.exceptions import AuthError

    class Broken(LocalStorage):
        def read(self, path):
            raise AuthError("req", "invalid_grant")

        def list(self, folder):
            raise AuthError("req", "invalid_grant")

    import tempfile
    main.set_repo(Repo(Broken(tempfile.mkdtemp())))
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.get("/")
    assert r.status_code == 500 and "Dropbox neu verbinden" in r.text


def test_classic_series(client):
    client.post("/mitglieder", data={"name": "Beat Bieler", "hcp": "18", "groups": ["C-Club"]})
    client.post("/plaetze", data=course_form())
    c = main.repo.courses()[0]
    mid = main.repo.members()[0]["id"]
    rids = []
    for d, classic in [("2026-05-01", True), ("2026-06-01", False), ("2026-07-01", True)]:
        data = {"group": "C-Club", "date": d, "course": c["id"]}
        if classic:
            data["series"] = "C-Club Classic"
        r = client.post("/runden", data=data)
        rid = r.url.path.rsplit("/", 1)[1]
        rids.append(rid)
        form = {"count": "1", "replace": "", "member0": mid, "hcp0": "18", "tee0": "Gelb Herren"}
        form.update({f"s0_{h}": str(p + (1 if d == "2026-07-01" else 0)) for h, p in enumerate(PARS)})
        client.post(f"/runden/{rid}/spieler", data=form)
    assert main.repo.round(rids[0])["series"] == ["C-Club Classic"]
    assert "Zählt zum C-Club Classic" in client.get(f"/runden/{rids[1]}").text
    r = client.get("/jahr/C-Club/2026?serie=C-Club%20Classic&streich=1")
    # nur die zwei Classic-Runden (Spiel-HCP 20): 56 + 38 Punkte, gestrichen 38 -> Endtotal 56
    assert r.text.count('<th class="num"><a href="/runden/') == 2
    assert '<td class="num">94</td>' in r.text and "−38" in r.text and "<b>56</b>" in r.text
    assert client.get("/jahr/C-Club/2026/pdf?serie=C-Club%20Classic&streich=1").status_code == 200
    # Häkchen nachträglich setzen
    client.post(f"/runden/{rids[1]}/serien", data={"series": "C-Club Classic"})
    r = client.get("/jahr/C-Club/2026?serie=C-Club%20Classic")
    assert r.text.count('<th class="num"><a href="/runden/') == 3
    # Pinseekers haben kein Classic
    client.post(f"/runden/{rids[1]}/serien", data={"series": "Gibt es nicht"})
    assert main.repo.round(rids[1])["series"] == []


def test_team_formats(client):
    from app.rankings import team_ranking

    course = main.repo.save_course({
        "name": "Teamplatz", "holes": [{"par": 4, "si": i + 1} for i in range(9)],
        "tees": [{"name": "Gelb", "cr": 36, "slope": 113}],
    })
    # Wechselnde beste Spieler: 5+2 statt der zwei besten Gesamtkarten.
    scores = [[1, 4] + [4] * 7, [4, 1] + [4] * 7,
              [5] * 9, [2] * 9]
    rnd = main.repo.save_round({
        "group": "C-Club", "date": "2026-10-26", "course_id": course["id"],
        "tee": "Gelb", "allowance": 1.0,
        "players": [{"name": f"Spieler {i}", "hcp_index": 0, "scores": s}
                    for i, s in enumerate(scores)],
    })
    url = f"/runden/{rnd['id']}"
    response = client.post(url + "/teams", data={
        "team_size": "3", "team_0": "Adler", "team_1": "Adler", "team_2": "Adler"})
    assert response.status_code == 200 and "Adler" in response.text
    saved = main.repo.round(rnd["id"])
    result = team_ranking(saved, course)[0]
    assert result["holes"] == [7, 7] + [4] * 7
    assert result["total"] == 42
    # Unvollständige Teams werden abgewiesen, vorhandene Zuordnung bleibt.
    response = client.post(url + "/teams", data={"team_size": "4", "team_0": "Falsch"})
    assert "genau 4 Spieler" in response.text
    assert main.repo.round(rnd["id"])["team_size"] == 3
    response = client.post(url + "/teams", data={
        "team_size": "4", **{f"team_{i}": "Vierer" for i in range(4)}})
    assert response.status_code == 200
    result = team_ranking(main.repo.round(rnd["id"]), course)[0]
    assert result["holes"] == [9, 9] + [6] * 7
    # Änderungen an einer Karte werden sofort neu berechnet.
    saved = main.repo.round(rnd["id"])
    saved["players"][3]["scores"] = [None] * 9
    main.repo.save_round(saved)
    assert team_ranking(main.repo.round(rnd["id"]), course)[0]["total"] == 42
    client.post(url + "/spieler/0/loeschen")
    assert main.repo.round(rnd["id"])["teams"] == []
    assert client.get(url).status_code == 200
    client.post(url + "/teams", data={"team_size": "3"})
    assert main.repo.round(rnd["id"])["teams"] == []


def test_team_gross_pdf_and_text(client):
    from app import pdf
    from app.rankings import best_two, team_ranking

    assert best_two([[2, 0, 3], [1, 4, 3], [3, 1, 0]]) == [5, 5, 6]
    course = main.repo.save_course({
        "name": "Teamplatz", "holes": [{"par": 4, "si": i + 1} for i in range(9)],
        "tees": [{"name": "Gelb", "cr": 36, "slope": 113}],
    })
    rnd = main.repo.save_round({
        "group": "C-Club", "date": "2026-10-26", "course_id": course["id"], "tee": "Gelb", "allowance": 1.0,
        "players": [{"name": f"S{i}", "hcp_index": 0, "scores": [3 + i] * 9} for i in range(6)],
        "team_size": 3, "teams": [{"name": "Hinten", "players": [3, 4, 5]}, {"name": "Vorne", "players": [0, 1, 2]}],
    })
    rows = team_ranking(rnd, course)
    assert [(r["name"], r["rank"], r["total"], r["gross"]) for r in rows] == [("Vorne", 1, 45, 45), ("Hinten", 2, 0, 0)]
    assert "Teamwertung 2 Best of 3" in pdf.day_text("C-Club", rnd, course, [], rows)
    assert client.get(f"/runden/{rnd['id']}/pdf").status_code == 200


def test_better_ball(client):
    from app import pdf
    from app.rankings import team_ranking

    course = main.repo.save_course({
        "name": "Teamplatz", "holes": [{"par": 4, "si": i + 1} for i in range(9)],
        "tees": [{"name": "Gelb", "cr": 36, "slope": 113}],
    })
    # 8 Spieler, 4 Zweierteams. Team A: abwechselnd Birdie/Bogey -> pro Loch 3 Punkte.
    scores = [[3, 5] * 4 + [3], [5, 3] * 4 + [5]] + [[4] * 9] * 6
    rnd = main.repo.save_round({
        "group": "C-Club", "date": "2026-10-30", "course_id": course["id"], "tee": "Gelb", "allowance": 1.0,
        "players": [{"name": f"S{i}", "hcp_index": 0, "scores": s} for i, s in enumerate(scores)],
    })
    url = f"/runden/{rnd['id']}"
    data = {"team_size": "2", **{f"team_{i}": "ABCD"[i // 2] for i in range(8)}}
    response = client.post(url + "/teams", data=data)
    assert response.status_code == 200 and "4-Ball Better Ball" in response.text
    saved = main.repo.round(rnd["id"])
    rows = team_ranking(saved, course)
    assert [(r["name"], r["total"]) for r in rows][0] == ("A", 27)
    assert rows[0]["holes"] == [3] * 9
    assert [r["total"] for r in rows[1:]] == [18, 18, 18]
    assert "Teamwertung 4-Ball Better Ball" in pdf.day_text("C-Club", saved, course, [], rows)
    assert client.get(url + "/pdf").status_code == 200
    # Dreierteam bei Better Ball wird abgewiesen.
    response = client.post(url + "/teams", data={"team_size": "2", "team_0": "X", "team_1": "X", "team_2": "X"})
    assert "genau 2 Spieler" in response.text


def test_totals_only_round(client):
    from app.main import parse_totals

    assert parse_totals("Beat Bieler 32\nHans W. Schlatter\t21*\n\nX 27x") == (
        [("Beat Bieler", 32, None), ("Hans W. Schlatter", 21, None)], ["X 27x"])
    r = client.post("/runden/nachtragen", data={
        "group": "C-Club", "date": "2026-06-01", "course_name": "OSCG", "series": "C-Club Classic",
        "results": "Andreas Holzer 27\nBeat Bieler 32"})
    assert r.status_code == 200 and "Nachgetragene Runde" in r.text and "OSCG" in r.text
    rnd = next(x for x in main.repo.rounds() if x.get("totals_only"))
    assert rnd["series"] == ["C-Club Classic"] and [p["net"] for p in rnd["players"]] == [27, 32]
    assert client.get(f"/runden/{rnd['id']}/pdf").status_code == 200
    r = client.get("/jahr/C-Club/2026?serie=C-Club%20Classic")
    assert "Beat Bieler" in r.text and "32" in r.text
    r = client.post("/runden/nachtragen", data={"group": "C-Club", "date": "2026-06-01",
                                                "course_name": "OSCG", "results": "nur Text"})
    assert "nicht lesen" in r.text
    # Birdies, NTP, LD pro Runde erfassen; Total in der Jahreswertung
    client.post(f"/runden/{rnd['id']}/extras", data={"birdies_1": "1", "ntp_1": "1", "ld_0": "1"})
    saved = main.repo.round(rnd["id"])
    assert [(p["birdies"], p["ntp"], p["ld"]) for p in saved["players"]] == [(None, 0, 1), (1, 1, 0)]
    r = client.get("/jahr/C-Club/2026?serie=C-Club%20Classic")
    assert "<th class=\"num\">NTP</th>" in r.text


def test_bogey_round(client):
    main.repo.save_settings({**main.repo.settings(), "allowance": 0.95})
    client.post("/plaetze", data=course_form())
    c = main.repo.courses()[0]
    r = client.post("/runden", data={"group": "C-Club", "date": "2026-11-01", "course": c["id"], "format": "bogey"})
    rnd = main.repo.round(r.url.path.rsplit("/", 1)[1])
    assert rnd["format"] == "bogey" and rnd["allowance"] == 1.0  # immer voller Handicap
    rnd["players"] = [{"name": "Beat", "hcp_index": 0, "tee": "Gelb Herren", "scores": PARS}]
    main.repo.save_round(rnd)
    r = client.get(f"/runden/{rnd['id']}")
    assert "Bogey Competition" in r.text
    assert client.get(f"/runden/{rnd['id']}/karte/0").status_code == 200
    assert client.get(f"/runden/{rnd['id']}/pdf").status_code == 200
    assert "Beat" not in client.get("/jahr/C-Club/2026").text  # nicht in der Jahreswertung
