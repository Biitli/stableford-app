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
