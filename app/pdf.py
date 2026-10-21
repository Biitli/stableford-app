"""PDF- und Textausgabe der Ranglisten (zum Drucken und für WhatsApp)."""

from __future__ import annotations

from datetime import date

from fpdf import FPDF

from .rankings import DayRow, SeasonRow

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


def day_pdf(group: str, rnd: dict, course: dict, rows: list[DayRow]) -> bytes:
    pdf = _Pdf(rnd.get("title") or "Tagesrangliste",
               f"{group} - {course['name']} - {fmt_date(rnd['date'])}")
    widths = [11, 52, 13, 17, 15, 15, 15]
    aligns = "CLCCCCC"
    headers = ["Rang", "Name", "HCP", "Spiel-HCP", "Netto", "Brutto", "Schläge"]

    def line(rank, r):
        return [str(rank), r.name, f"{r.hcp_index:.1f}", str(r.playing_hcp), str(r.net), str(r.gross),
                str(r.strokes or "-")]

    pdf.heading("Netto")
    pdf.table(headers, widths, [line(r.rank, r) for r in rows], aligns, bold_cols={4})
    pdf.ln(5)
    pdf.heading("Brutto")
    by_gross = sorted(rows, key=lambda r: (r.gross_rank, r.name.lower()))
    pdf.table(headers, widths, [line(r.gross_rank, r) for r in by_gross], aligns, bold_cols={5})
    pdf.note("Stableford-Punkte. Netto: bei Punktgleichheit entscheiden die letzten 9, 6, 3 und 1 Löcher. "
             "Brutto: bei Punktgleichheit entscheiden die Nettopunkte.")
    return bytes(pdf.output())


def season_pdf(group: str, year: int, rounds: list[dict], rows: list[SeasonRow], drop_worst: bool,
               gross: bool = False) -> bytes:
    title = f"Jahreswertung {year} {'Brutto' if gross else 'Netto'}"
    if drop_worst:
        title += " (mit Streichresultat)"
    pdf = _Pdf(title, f"{group} - {len(rounds)} Runde(n)")
    n = len(rounds)
    name_w, fixed = 44, 11 + 44 + 14 + 13
    rw = min(14, (180 - fixed) / max(n, 1))
    font = FONT if rw >= 10 else 6.5
    headers = ["Rang", "Name"] + [fmt_date(r["date"])[:5] for r in rounds] + ["Total", "Runden"]
    widths = [11, name_w] + [rw] * n + [14, 13]
    data, struck = [], set()
    for ri, r in enumerate(rows):
        if r.dropped_index is not None:
            struck.add((ri, 2 + r.dropped_index))
        data.append([str(r.rank), r.name, *("-" if x is None else str(x) for x in r.results),
                     str(r.total), str(r.played)])
    pdf.table(headers, widths, data, "CL" + "C" * n + "CC", bold_cols={2 + n}, struck=struck, font=font)
    note = f"{'Brutto' if gross else 'Netto'}punkte Stableford."
    if drop_worst:
        note += " Werte in Klammern sind gestrichen."
    pdf.note(note)
    return bytes(pdf.output())


def day_text(group: str, rnd: dict, course: dict, rows: list[DayRow]) -> str:
    lines = [f"*{rnd.get('title') or 'Tagesrangliste'} {group}*",
             f"{course['name']}, {fmt_date(rnd['date'])}", "", "*Netto*"]
    lines += [f"{r.rank}. {r.name} – {r.net} P." for r in rows]
    lines += ["", "*Brutto*"]
    lines += [f"{r.gross_rank}. {r.name} – {r.gross} P."
              for r in sorted(rows, key=lambda r: (r.gross_rank, r.name.lower()))]
    return "\n".join(lines)


def season_text(group: str, year: int, rows: list[SeasonRow], drop_worst: bool, gross: bool = False) -> str:
    head = f"*Jahreswertung {year} {group} {'Brutto' if gross else 'Netto'}*"
    lines = [head + (" (mit Streichresultat)" if drop_worst else ""), ""]
    lines += [f"{r.rank}. {r.name} – {r.total} P. ({r.played} Runden)" for r in rows]
    return "\n".join(lines)
