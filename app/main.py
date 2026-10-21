"""Web-App: Stableford-Ranglisten für C-Club und Pinseekers."""

from __future__ import annotations

import hmac
import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import ai, importer, pdf
from .rankings import daily_ranking, score_player, season_ranking, tee_of
from .repo import Repo, slug
from .storage import dropbox_token_set, storage_from_env

BASE = Path(__file__).parent
app = FastAPI(title="Stableford")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.filters["datum"] = pdf.fmt_date

PASSWORD = os.environ.get("APP_PASSWORD", "")
repo = Repo(storage_from_env())


def set_repo(r: Repo) -> None:
    """Für Tests: andere Ablage verwenden."""
    global repo
    repo = r


@app.middleware("http")
async def require_login(request: Request, call_next):
    open_paths = ("/login", "/static", "/healthz")
    if PASSWORD and not request.url.path.startswith(open_paths) and not request.session.get("ok"):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


# SessionMiddleware muss nach (= ausserhalb von) require_login registriert werden
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", PASSWORD or "dev"),
                   max_age=60 * 60 * 24 * 180, https_only=bool(PASSWORD))


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("settings", repo.settings())
    ctx.setdefault("ai_available", ai.available())
    ctx.setdefault("dropbox_connected", dropbox_token_set())
    return templates.TemplateResponse(request, name, ctx)


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def to_float(v: str | None, default: float | None = None) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return default


def to_score(v: str | None) -> int | None:
    try:
        n = int(str(v).strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "login.html", error=None)


@app.post("/login")
def login(request: Request, password: str = Form(...)):
    if PASSWORD and hmac.compare_digest(password, PASSWORD):
        request.session["ok"] = True
        return back("/")
    return render(request, "login.html", error="Falsches Passwort")


# Übersicht
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    year = date.today().year
    groups = []
    for g in repo.settings()["groups"]:
        rs = repo.rounds(group=g)
        years = sorted({int(r["date"][:4]) for r in rs} | {year}, reverse=True)
        groups.append({"name": g, "rounds": list(reversed(rs))[:8], "years": years})
    courses = {c["id"]: c for c in repo.courses()}
    return render(request, "home.html", groups=groups, courses=courses, year=year)


# Mitglieder
@app.get("/mitglieder", response_class=HTMLResponse)
def members(request: Request, edit: str | None = None):
    return render(request, "members.html", members=repo.members(), edit=repo.member(edit) if edit else None,
                  info=None)


@app.post("/mitglieder")
def save_member(id: str = Form(""), name: str = Form(...), hcp: str = Form(...),
                groups: list[str] = Form([]), aliases: str = Form(""), ladies: str = Form("")):
    m = repo.member(id) if id else {}
    m = {**(m or {}), "name": name.strip(), "hcp": to_float(hcp, 54.0), "groups": groups,
         "aliases": [a.strip() for a in aliases.split(",") if a.strip()], "ladies": bool(ladies)}
    if id:
        m["id"] = id
    repo.save_member(m)
    return back("/mitglieder")


@app.post("/mitglieder/import", response_class=HTMLResponse)
async def import_members(request: Request, group: str = Form(...), file: UploadFile = File(...)):
    try:
        rows = importer.read_file(file.filename or "", await file.read())
    except Exception as e:  # noqa: BLE001
        rows, error = [], f"Datei konnte nicht gelesen werden ({e})."
    else:
        error = None if rows else "In der Datei wurden keine Namen mit Handicap gefunden."
    by_name = {slug(m["name"]): m for m in repo.members()}
    added = updated = 0
    for name, hcp in rows:
        m = by_name.get(slug(name))
        if m:
            m["hcp"] = hcp
            if group not in m.get("groups", []):
                m.setdefault("groups", []).append(group)
            updated += 1
        else:
            m = {"name": name, "hcp": hcp, "groups": [group], "aliases": []}
            added += 1
        by_name[slug(name)] = repo.save_member(m)
    info = error or f"{added} neu erfasst, {updated} aktualisiert ({group})."
    return render(request, "members.html", members=repo.members(), edit=None, info=info)


@app.post("/mitglieder/{mid}/loeschen")
def delete_member(mid: str):
    repo.delete_member(mid)
    return back("/mitglieder")


# Plätze
@app.get("/plaetze", response_class=HTMLResponse)
def courses(request: Request):
    return render(request, "courses.html", courses=repo.courses())


def blank_course(holes: int = 18) -> dict:
    return {"name": "", "holes": [{"par": 4, "si": i + 1} for i in range(holes)],
            "tees": [{"name": "Gelb Herren", "cr": "", "slope": ""}, {"name": "Rot Damen", "cr": "", "slope": ""}]}


@app.get("/plaetze/neu", response_class=HTMLResponse)
def new_course(request: Request, loecher: int = 18):
    return render(request, "course_form.html", course=blank_course(9 if loecher == 9 else 18), info=None)


@app.post("/plaetze/suchen", response_class=HTMLResponse)
def search_course(request: Request, query: str = Form(...)):
    course, info = blank_course(), None
    course["name"] = query
    try:
        found = ai.lookup_course(query)
        if found["found"] and len(found["holes"]) in (9, 18):
            course = {"name": found["name"], "holes": found["holes"],
                      "tees": found["tees"] or course["tees"], "source": found["source"]}
            info = f"Gefunden (Quelle: {found['source']}). Bitte alle Werte prüfen, bevor du speicherst."
        else:
            info = "Keine verlässlichen Daten gefunden. Bitte von der Scorekarte abtippen."
    except Exception as e:  # noqa: BLE001 - Fehler dem Benutzer zeigen
        info = f"Suche nicht möglich ({e}). Bitte die Werte von Hand eingeben."
    return render(request, "course_form.html", course=course, info=info)


@app.get("/plaetze/{cid}", response_class=HTMLResponse)
def edit_course(request: Request, cid: str):
    return render(request, "course_form.html", course=repo.course(cid), info=None)


@app.post("/plaetze")
async def save_course(request: Request):
    f = await request.form()
    holes = int(f.get("holes", 18))
    course = {
        "name": str(f["name"]).strip(),
        "holes": [{"par": int(f[f"par{i}"]), "si": int(f[f"si{i}"])} for i in range(holes)],
        "tees": [],
    }
    if f.get("id"):
        course["id"] = str(f["id"])
    if f.get("source"):
        course["source"] = str(f["source"])
    for i in range(20):
        name = str(f.get(f"tee{i}", "")).strip()
        cr, sl = to_float(f.get(f"cr{i}")), to_float(f.get(f"slope{i}"))
        if name and cr and sl:
            course["tees"].append({"name": name, "cr": cr, "slope": int(sl)})
    sis = sorted(h["si"] for h in course["holes"])
    errors = []
    if not course["tees"]:
        errors.append("Mindestens ein Abschlag mit Course Rating und Slope ist nötig.")
    if holes == 18 and sis != list(range(1, 19)):
        errors.append("Jeder Stroke Index von 1 bis 18 muss genau einmal vorkommen.")
    if holes == 9 and len(set(sis)) != 9:
        errors.append("Die Stroke Indexe müssen verschieden sein.")
    if errors:
        return render(request, "course_form.html", course=course, info=" ".join(errors))
    repo.save_course(course)
    return back(str(f.get("next") or "/plaetze"))


@app.post("/plaetze/{cid}/loeschen")
def delete_course(cid: str):
    repo.delete_course(cid)
    return back("/plaetze")


# Runden
@app.get("/runden/neu", response_class=HTMLResponse)
def new_round(request: Request, gruppe: str = ""):
    return render(request, "round_new.html", courses=repo.courses(), group=gruppe, today=date.today().isoformat())


@app.post("/runden")
def create_round(group: str = Form(...), date_: str = Form(..., alias="date"), course_tee: str = Form(...),
                 title: str = Form("")):
    cid, tee = course_tee.split("|", 1)
    r = repo.save_round({"group": group, "date": date_, "course_id": cid, "tee": tee, "title": title.strip(),
                         "allowance": repo.settings()["allowance"], "players": []})
    return back(f"/runden/{r['id']}")


def round_ctx(rid: str):
    rnd = repo.round(rid)
    course = repo.course(rnd["course_id"]) if rnd else None
    return rnd, course


@app.get("/runden/{rid}", response_class=HTMLResponse)
def show_round(request: Request, rid: str):
    rnd, course = round_ctx(rid)
    if not rnd:
        return back("/")
    rows = daily_ranking(rnd, course) if rnd["players"] else []
    return render(request, "round.html", rnd=rnd, course=course, rows=rows,
                  share_text=pdf.day_text(rnd["group"], rnd, course, rows))


def default_tee(rnd: dict, course: dict, member: dict | None) -> str:
    """Damen spielen standardmässig vom ersten Abschlag mit 'Damen' im Namen."""
    if member and member.get("ladies"):
        for t in course["tees"]:
            if "dame" in t["name"].lower():
                return t["name"]
    return rnd["tee"]


def review_player(p: dict, rnd: dict, course: dict) -> dict:
    """Ergänzt einen erkannten Spieler mit dem passenden Mitglied und dessen HCP."""
    m, score = repo.match_member(p["name"], rnd["group"])
    if m and score >= 0.6:
        return {**p, "member_id": m["id"], "name": m["name"], "hcp_index": m["hcp"], "match": score,
                "read_name": p["name"], "tee": default_tee(rnd, course, m)}
    return {**p, "member_id": "", "hcp_index": p.get("hcp_on_card") or "", "match": score, "read_name": p["name"],
            "tee": rnd["tee"]}


@app.post("/runden/{rid}/foto", response_class=HTMLResponse)
async def upload_photo(request: Request, rid: str, photos: list[UploadFile] = File(...)):
    rnd, course = round_ctx(rid)
    known = [m["name"] for m in repo.members() if rnd["group"] in m.get("groups", [])]
    players, notes = [], []
    for ph in photos:
        img = await ph.read()
        if not img:
            continue
        try:
            res = ai.read_scorecard(img, ph.content_type or "image/jpeg", len(course["holes"]), known)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{ph.filename}: konnte nicht gelesen werden ({e})")
            continue
        players += [review_player(p, rnd, course) for p in res["players"]]
        if res.get("notes"):
            notes.append(res["notes"])
    return render(request, "review.html", rnd=rnd, course=course, players=players, notes=notes,
                  members=repo.members(), replace=None)


@app.get("/runden/{rid}/spieler", response_class=HTMLResponse)
def manual_player(request: Request, rid: str, idx: int | None = None):
    rnd, course = round_ctx(rid)
    if idx is not None:
        players = [{**rnd["players"][idx], "match": 1}]
    else:
        players = [{"name": "", "member_id": "", "hcp_index": "", "scores": [None] * len(course["holes"]),
                    "match": 1, "tee": rnd["tee"]}]
    return render(request, "review.html", rnd=rnd, course=course, players=players, notes=[],
                  members=repo.members(), replace=idx)


@app.post("/runden/{rid}/spieler")
async def save_players(rid: str, request: Request):
    rnd, course = round_ctx(rid)
    f = await request.form()
    holes = len(course["holes"])
    new = []
    for i in range(int(f.get("count", 0))):
        if f.get(f"skip{i}"):
            continue
        mid = str(f.get(f"member{i}", ""))
        m = repo.member(mid) if mid else None
        name = m["name"] if m else str(f.get(f"name{i}", "")).strip()
        if not name:
            continue
        hcp = to_float(f.get(f"hcp{i}"), m["hcp"] if m else 54.0)
        tee = str(f.get(f"tee{i}") or rnd["tee"])
        new.append({"member_id": mid or None, "name": name, "hcp_index": hcp, "tee": tee,
                    "scores": [to_score(f.get(f"s{i}_{h}")) for h in range(holes)]})
    replace = f.get("replace")
    if replace not in (None, ""):
        rnd["players"][int(replace)] = new[0] if new else rnd["players"][int(replace)]
    else:
        existing = {p.get("member_id") or p["name"].lower(): i for i, p in enumerate(rnd["players"])}
        for p in new:
            k = p["member_id"] or p["name"].lower()
            if k in existing:
                rnd["players"][existing[k]] = p
            else:
                rnd["players"].append(p)
    repo.save_round(rnd)
    return back(f"/runden/{rid}")


@app.post("/runden/{rid}/spieler/{idx}/loeschen")
def delete_player(rid: str, idx: int):
    rnd = repo.round(rid)
    rnd["players"].pop(idx)
    repo.save_round(rnd)
    return back(f"/runden/{rid}")


@app.post("/runden/{rid}/loeschen")
def delete_round(rid: str):
    repo.delete_round(rid)
    return back("/")


@app.get("/runden/{rid}/karte/{idx}", response_class=HTMLResponse)
def show_card(request: Request, rid: str, idx: int):
    rnd, course = round_ctx(rid)
    p = rnd["players"][idx]
    tee = tee_of(course, p.get("tee") or rnd["tee"])
    res = score_player(p, course, tee["name"], float(rnd.get("allowance", 1.0)))
    return render(request, "card.html", rnd=rnd, course=course, p=p, res=res, tee=tee)


@app.get("/runden/{rid}/pdf")
def round_pdf(rid: str):
    rnd, course = round_ctx(rid)
    rows = daily_ranking(rnd, course)
    data = pdf.day_pdf(rnd["group"], rnd, course, rows)
    fname = f"{rnd['date']}_{slug(course['name'])}.pdf"
    repo.save_pdf(rnd["group"], fname, data)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{fname}"'})


# Jahreswertung
def season_data(group: str, year: int, drop: bool):
    rounds = repo.rounds(group=group, year=year)
    courses = {c["id"]: c for c in repo.courses()}
    rounds = [r for r in rounds if r["players"] and r["course_id"] in courses]
    rows = season_ranking(rounds, courses, drop_worst=drop,
                          missed_counts_as_zero=repo.settings()["missed_round_counts_as_zero"])
    return rounds, courses, rows


@app.get("/jahr/{group}/{year}", response_class=HTMLResponse)
def season(request: Request, group: str, year: int, streich: int = 0):
    rounds, courses, rows = season_data(group, year, bool(streich))
    return render(request, "season.html", group=group, year=year, rounds=rounds, courses=courses, rows=rows,
                  drop=bool(streich), share_text=pdf.season_text(group, year, rows, bool(streich)))


@app.get("/jahr/{group}/{year}/pdf")
def season_pdf(group: str, year: int, streich: int = 0):
    rounds, _, rows = season_data(group, year, bool(streich))
    data = pdf.season_pdf(group, year, rounds, rows, bool(streich))
    fname = f"Jahreswertung_{year}{'_Streichresultat' if streich else ''}.pdf"
    repo.save_pdf(group, fname, data)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{fname}"'})


# Dropbox verbinden: liefert den Refresh-Token, der danach bei Render eingetragen wird
def _dropbox_flow():
    from dropbox import DropboxOAuth2FlowNoRedirect

    return DropboxOAuth2FlowNoRedirect(os.environ["DROPBOX_APP_KEY"], os.environ["DROPBOX_APP_SECRET"],
                                       token_access_type="offline")


@app.get("/dropbox", response_class=HTMLResponse)
def dropbox_setup(request: Request):
    ready = bool(os.environ.get("DROPBOX_APP_KEY") and os.environ.get("DROPBOX_APP_SECRET"))
    return render(request, "dropbox.html", ready=ready, url=_dropbox_flow().start() if ready else None,
                  connected=dropbox_token_set(), token=None, error=None)


@app.post("/dropbox", response_class=HTMLResponse)
def dropbox_finish(request: Request, code: str = Form(...)):
    try:
        token, error = _dropbox_flow().finish(code.strip()).refresh_token, None
    except Exception as e:  # noqa: BLE001
        token, error = None, f"Das hat nicht geklappt ({e}). Bitte den Link nochmals öffnen."
    return render(request, "dropbox.html", ready=True, url=_dropbox_flow().start(), connected=False,
                  token=token, error=error)


# Einstellungen
@app.get("/einstellungen", response_class=HTMLResponse)
def settings_form(request: Request):
    return render(request, "settings.html")


@app.post("/einstellungen")
def save_settings(groups: str = Form(...), allowance: str = Form("100"), missed_zero: str = Form("")):
    s = repo.settings()
    s["groups"] = [g.strip() for g in groups.split(",") if g.strip()]
    s["allowance"] = (to_float(allowance, 100.0) or 100.0) / 100
    s["missed_round_counts_as_zero"] = bool(missed_zero)
    repo.save_settings(s)
    return back("/einstellungen")
