"""PDF- und Textausgabe der Ranglisten (zum Drucken und für WhatsApp)."""

from __future__ import annotations

from datetime import date

from fpdf import FPDF

from .rankings import DayRow, SeasonRow


def fmt_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso


class _Pdf(FPDF):
    def __init__(self, title: str, subtitle: str, landscape: bool = False):
        super().__init__(orientation="L" if landscape else "P", format="A4")
        self.title_text, self.subtitle = title, subtitle
        self.set_auto_page_break(True, 15)
        self.add_page()

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 9, self.title_text, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 10)
        self.cell(0, 6, self.subtitle, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def table(self, headers: list[str], widths: list[float], rows: list[list[str]],
              aligns: str, bold_cols: set[int] = frozenset(), struck: set[tuple[int, int]] = frozenset()):
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(225, 235, 225)
        for h, w, a in zip(headers, widths, aligns):
            self.cell(w, 7, h, border=1, align=a, fill=True)
        self.ln()
        for ri, row in enumerate(rows):
            fill = ri % 2 == 1
            self.set_fill_color(245, 245, 245)
            for ci, (v, w, a) in enumerate(zip(row, widths, aligns)):
                style = "B" if ci in bold_cols else ""
                if (ri, ci) in struck:
                    v = f"({v})"
                    style = "I"
                self.set_font("Helvetica", style, 9)
                self.cell(w, 6.5, v, border=1, align=a, fill=fill)
            self.ln()


def _latin(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")


def day_pdf(group: str, rnd: dict, course: dict, rows: list[DayRow]) -> bytes:
    sub = f"{group} - {course['name']} ({rnd['tee']}) - {fmt_date(rnd['date'])}"
    pdf = _Pdf(_latin(rnd.get("title") or "Tagesrangliste"), _latin(sub))
    headers = ["Rang", "Name", "HCP", "Spiel-HCP", "Netto", "Brutto", "Schläge", "Rang Brutto"]
    widths = [14, 58, 16, 20, 18, 18, 18, 24]
    data = [[str(r.rank), _latin(r.name), f"{r.hcp_index:.1f}", str(r.playing_hcp), str(r.net),
             str(r.gross), str(r.strokes or "-"), str(r.gross_rank)] for r in rows]
    pdf.table([_latin(h) for h in headers], widths, data, "CLCCCCCC", bold_cols={4})
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, _latin("Bei Punktgleichheit entscheiden die letzten 9, 6, 3 und 1 Löcher (netto)."))
    return bytes(pdf.output())


def season_pdf(group: str, year: int, rounds: list[dict], rows: list[SeasonRow], drop_worst: bool) -> bytes:
    title = f"Jahreswertung {year}" + (" (mit Streichresultat)" if drop_worst else "")
    pdf = _Pdf(_latin(title), _latin(f"{group} - {len(rounds)} Runde(n)"), landscape=len(rounds) > 6)
    n = len(rounds)
    name_w = 50
    avail = (277 if n > 6 else 190) - 14 - name_w - 20 - 16
    rw = max(10, min(18, avail / max(n, 1)))
    headers = ["Rang", "Name"] + [fmt_date(r["date"])[:5] for r in rounds] + ["Total", "Runden"]
    widths = [14, name_w] + [rw] * n + [20, 16]
    data, struck = [], set()
    for ri, r in enumerate(rows):
        cells = ["-" if x is None else str(x) for x in r.results]
        if r.dropped_index is not None:
            struck.add((ri, 2 + r.dropped_index))
        data.append([str(r.rank), _latin(r.name), *cells, str(r.total), str(r.played)])
    pdf.table(headers, widths, data, "CL" + "C" * n + "CC", bold_cols={2 + n}, struck=struck)
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 8)
    note = "Nettopunkte Stableford."
    if drop_worst:
        note += " Werte in Klammern sind gestrichen."
    pdf.cell(0, 5, _latin(note))
    return bytes(pdf.output())


def day_text(group: str, rnd: dict, course: dict, rows: list[DayRow]) -> str:
    lines = [f"*{rnd.get('title') or 'Tagesrangliste'} {group}*",
             f"{course['name']}, {fmt_date(rnd['date'])}", ""]
    for r in rows:
        lines.append(f"{r.rank}. {r.name} – {r.net} P. netto ({r.gross} brutto)")
    return "\n".join(lines)


def season_text(group: str, year: int, rows: list[SeasonRow], drop_worst: bool) -> str:
    lines = [f"*Jahreswertung {year} {group}*" + (" (mit Streichresultat)" if drop_worst else ""), ""]
    for r in rows:
        lines.append(f"{r.rank}. {r.name} – {r.total} P. ({r.played} Runden)")
    return "\n".join(lines)
