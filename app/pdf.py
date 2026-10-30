"""PDF- und Textausgabe der Ranglisten (zum Drucken und für WhatsApp)."""

from __future__ import annotations

from datetime import date

from fpdf import FPDF

from .rankings import TEAM_FORMATS, DayRow, SeasonRow

FONT = 8  # Schriftgrösse der Tabellen
ROW_H = 5


def fmt_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def _latin(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")


class _Pdf(FPDF):
    """A4 Hochformat."""

    def __init__(self, title: str, subtitle: str):
        super().__init__(orientation="P", format="A4")
        self.title_text, self.subtitle = _latin(title), _latin(subtitle)
        self.set_margins(15, 12, 15)
        self.set_auto_page_break(True, 12)
        self.add_page()

    def header(self):
        self.set_font("Helvetica", "B", 13)
        self.cell(0, 7, self.title_text, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, self.subtitle, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def heading(self, text: str):
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 6, _latin(text), new_x="LMARGIN", new_y="NEXT")

    def table(self, headers: list[str], widths: list[float], rows: list[list[str]], aligns: str,
              bold_cols=frozenset(), struck=frozenset(), font: float = FONT):
        self.set_font("Helvetica", "B", font)
        self.set_fill_color(225, 235, 225)
        for h, w, a in zip(headers, widths, aligns):
            self.cell(w, ROW_H + 0.5, _latin(h), border=1, align=a, fill=True)
        self.ln()
        self.set_fill_color(245, 245, 245)
        for ri, row in enumerate(rows):
            for ci, (v, w, a) in enumerate(zip(row, widths, aligns)):
                style = "B" if ci in bold_cols else ""
                if (ri, ci) in struck:
                    v, style = f"({v})", "I"
                self.set_font("Helvetica", style, font)
                self.cell(w, ROW_H, _latin(v), border=1, align=a, fill=ri % 2 == 1)
            self.ln()

    def note(self, text: str):
        self.ln(1)
        self.set_font("Helvetica", "", 7)
        self.multi_cell(0, 4, _latin(text), new_x="LMARGIN", new_y="NEXT")


def team_title(rnd: dict) -> str:
    return "Teamwertung " + TEAM_FORMATS[rnd.get("team_size", 3)]


def day_pdf(group: str, rnd: dict, course: dict, rows: list[DayRow], teams: list[dict] = ()) -> bytes:
    pdf = _Pdf(rnd.get("title") or "Tagesrangliste",
               f"{group} - {course['name']} - {fmt_date(rnd['date'])}")
    widths = [11, 46, 12, 16, 14, 14, 15, 11, 11, 10]
    aligns = "CLCCCCCCCC"
    headers = ["Rang", "Name", "HCP", "Spiel-HCP", "Netto", "Brutto", "Schläge", "Bird", "NTP", "LD"]

    def line(rank, r):
        return [str(rank), r.name, f"{r.hcp_index:.1f}", "-" if r.playing_hcp is None else str(r.playing_hcp),
                str(r.net), "-" if r.gross is None else str(r.gross), str(r.strokes or "-"),
                str(r.birdies or ""), str(r.ntp or ""), str(r.ld or "")]

    pdf.heading("Netto")
    pdf.table(headers, widths, [line(r.rank, r) for r in rows], aligns, bold_cols={4})
    if not rnd.get("totals_only"):
        pdf.ln(5)
        pdf.heading("Brutto")
        by_gross = sorted(rows, key=lambda r: (r.gross_rank, r.name.lower()))
        pdf.table(headers, widths, [line(r.gross_rank, r) for r in by_gross], aligns, bold_cols={5})
    if teams:
        pdf.ln(5)
        pdf.heading(team_title(rnd))
        pdf.table(["Rang", "Team", "Spieler", "Netto", "Brutto"], [11, 35, 85, 15, 15],
                  [[str(t["rank"]), t["name"], ", ".join(t["names"]), str(t["total"]), str(t["gross"])]
                   for t in teams], "CLLCC", bold_cols={3})
    pdf.note("Stableford-Punkte. Netto: bei Punktgleichheit entscheiden die letzten 9, 6, 3 und 1 Löcher. "
             "Brutto: bei Punktgleichheit entscheiden die Nettopunkte."
             + ((" Team: pro Loch zählt das bessere Resultat der beiden Spieler." if rnd.get("team_size") == 2
                 else " Team: pro Loch zählen die zwei besten Resultate des Teams.") if teams else ""))
    return bytes(pdf.output())


def season_pdf(group: str, year: int, rounds: list[dict], rows: list[SeasonRow], drop_worst: bool,
               gross: bool = False, series: str = "") -> bytes:
    title = f"{series or 'Jahreswertung'} {year} {'Brutto' if gross else 'Netto'}"
    if drop_worst:
        title += " (mit Streichresultat)"
    pdf = _Pdf(title, f"{group} - {len(rounds)} Runde(n)")
    n = len(rounds)
    tail = ["Bird", "NTP", "LD"] + (["Runden", "Total", "Streich", "Endtotal"] if drop_worst else ["Runden", "Total"])
    tail_w = [9, 9, 8] + ([13, 13, 13, 15] if drop_worst else [13, 14])
    name_w = 36
    rw = min(14, (180 - 11 - name_w - sum(tail_w)) / max(n, 1))
    font = FONT if rw >= 10 else 6.5
    headers = ["Rang", "Name"] + [fmt_date(r["date"])[:5] for r in rounds] + tail
    widths = [11, name_w] + [rw] * n + tail_w
    data, struck = [], set()
    for ri, r in enumerate(rows):
        if r.dropped_index is not None:
            struck.add((ri, 2 + r.dropped_index))
        end = [str(r.birdies or ""), str(r.ntp or ""), str(r.ld or ""), str(r.played)]
        if drop_worst:
            end += [str(r.raw_total), "-" if not r.dropped_value else f"-{r.dropped_value}"]
        data.append([str(r.rank), r.name, *("-" if x is None else str(x) for x in r.results), *end, str(r.total)])
    pdf.table(headers, widths, data, "CL" + "C" * (n + len(tail)), bold_cols={1 + n + len(tail)}, struck=struck,
              font=font)
    note = f"{'Brutto' if gross else 'Netto'}punkte Stableford. Bird, NTP, LD: Anzahl über alle Runden."
    if drop_worst:
        note += " Werte in Klammern sind gestrichen."
    pdf.note(note)
    return bytes(pdf.output())


def day_text(group: str, rnd: dict, course: dict, rows: list[DayRow], teams: list[dict] = ()) -> str:
    lines = [f"*{rnd.get('title') or 'Tagesrangliste'} {group}*",
             f"{course['name']}, {fmt_date(rnd['date'])}", "", "*Netto*"]
    lines += [f"{r.rank}. {r.name} – {r.net} P." for r in rows]
    if not rnd.get("totals_only"):
        lines += ["", "*Brutto*"]
        lines += [f"{r.gross_rank}. {r.name} – {r.gross} P."
                  for r in sorted(rows, key=lambda r: (r.gross_rank, r.name.lower()))]
    if teams:
        lines += ["", f"*{team_title(rnd)}*"]
        lines += [f"{t['rank']}. {t['name']} ({', '.join(t['names'])}) – {t['total']} P." for t in teams]
    return "\n".join(lines)


def season_text(group: str, year: int, rows: list[SeasonRow], drop_worst: bool, gross: bool = False,
                series: str = "") -> str:
    head = f"*{series or 'Jahreswertung'} {year} {'' if series else group + ' '}{'Brutto' if gross else 'Netto'}*"
    lines = [head + (" (mit Streichresultat)" if drop_worst else ""), ""]
    lines += [f"{r.rank}. {r.name} – {r.total} P. ({r.played} Runden)" for r in rows]
    return "\n".join(lines)
