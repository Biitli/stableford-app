"""Mitgliederliste aus Excel (.xlsx) oder CSV einlesen."""

from __future__ import annotations

import csv
import io


def _hcp(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        try:
            x = float(str(v).strip().replace(",", ".").lstrip("+"))
        except ValueError:
            return None
        if str(v).strip().startswith("+"):
            x = -x  # Plus-Handicap
    return x if -10 <= x <= 54 else None


def parse_rows(rows) -> list[tuple[str, float]]:
    """Eine Zeile zählt als Mitglied, wenn sie einen Namen und eine Zahl (HCP) enthält.

    Titel- und Kopfzeilen ohne Zahl werden übersprungen. Steht Vor- und Nachname in zwei
    Spalten, werden sie zusammengesetzt.
    """
    out = []
    for row in rows:
        cells = [c for c in row if c is not None and str(c).strip() != ""]
        texts = [str(c).strip() for c in cells if _hcp(c) is None]
        nums = [_hcp(c) for c in cells if _hcp(c) is not None]
        if texts and nums:
            out.append((" ".join(texts[:2]), round(nums[0], 1)))
    return out


def read_file(filename: str, data: bytes) -> list[tuple[str, float]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        return parse_rows(wb.worksheets[0].iter_rows(values_only=True))
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
    return parse_rows(csv.reader(io.StringIO(text), dialect))
