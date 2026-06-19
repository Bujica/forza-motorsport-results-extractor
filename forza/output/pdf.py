from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, portrait
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from ..config import AppConfig, CLASS_COLORS
from ..domain import class_order_key, track_order_key, track_order_map
from ..domain.lap import strip_dirty_symbol
from ..schemas import ExportLap


log = logging.getLogger("forza")


# ── PDF archiving ─────────────────────────────────────────────────────────────

def _archive_pdf(pdf_path: Path) -> None:
    """
    If a PDF already exists at pdf_path, move it to an archive/ subfolder
    with a timestamp suffix before the new one is written.

    This preserves the previous report so it can be compared or restored
    after a rebuild that produces unexpected output.

    Example:
        output/reports/forza_bestlaps.pdf
        → output/reports/archive/forza_bestlaps_20260515_143022.pdf
    """
    if not pdf_path.exists():
        return
    archive_dir = pdf_path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = archive_dir / f"{pdf_path.stem}_{ts}{pdf_path.suffix}"
    try:
        shutil.move(str(pdf_path), dest)
        log.info(f"[pdf] Previous report archived: {dest.name}")
    except Exception as exc:
        log.warning(f"[pdf] Could not archive previous PDF: {exc}")


# ── Colour constants ──────────────────────────────────────────────────────────

# Row background colours
ROW_PLAYER   = "#FFF8DC"   # warm yellow  — player's own lap
ROW_EXTERNAL = "#D6EAF8"   # light blue   — external / world record
ROW_ALT      = "#F8F9FA"   # light grey   — alternating internal rows

MONTHS_PT: dict[int, str] = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março",    4: "Abril",
    5: "Maio",    6: "Junho",     7: "Julho",     8: "Agosto",
    9: "Setembro",10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


# ── Doc template with TOC support ─────────────────────────────────────────────

class _ForzaDocTemplate(SimpleDocTemplate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._track_count = 0

    def beforeDocument(self):
        self._track_count = 0

    def afterFlowable(self, flowable):
        if (
            isinstance(flowable, Paragraph)
            and flowable.style.name == "TOCTitle"
            and flowable.getPlainText() == "Track Index"
        ):
            self.canv.bookmarkPage("toc")

        if isinstance(flowable, Paragraph) and flowable.style.name == "TrackHeading":
            key = f"track_{self._track_count}"
            self._track_count += 1
            self.canv.bookmarkPage(key)
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page, key))


# ── Styles ────────────────────────────────────────────────────────────────────

def _build_styles() -> dict[str, ParagraphStyle]:
    return {
        "TitleBig": ParagraphStyle(
            "TitleBig", fontName="Helvetica-Bold", fontSize=28,
            leading=34, alignment=1, textColor=colors.HexColor("#2C3E50"), spaceAfter=6,
        ),
        "TitleSub": ParagraphStyle(
            "TitleSub", fontName="Helvetica", fontSize=16,
            leading=20, alignment=1, textColor=colors.HexColor("#7F8C8D"), spaceAfter=4,
        ),
        "TitleName": ParagraphStyle(
            "TitleName", fontName="Helvetica-Bold", fontSize=18,
            leading=22, alignment=1, textColor=colors.HexColor("#2C3E50"), spaceAfter=4,
        ),
        "TitleDate": ParagraphStyle(
            "TitleDate", fontName="Helvetica", fontSize=12,
            leading=16, alignment=1, textColor=colors.HexColor("#95A5A6"), spaceAfter=4,
        ),
        "TitleStats": ParagraphStyle(
            "TitleStats", fontName="Helvetica", fontSize=11,
            leading=14, alignment=1, textColor=colors.HexColor("#7F8C8D"),
        ),
        "TitleLegend": ParagraphStyle(
            "TitleLegend", fontName="Helvetica", fontSize=10,
            leading=14, alignment=1, textColor=colors.HexColor("#7F8C8D"), spaceBefore=12,
        ),
        "TOCTitle": ParagraphStyle(
            "TOCTitle", fontName="Helvetica-Bold", fontSize=16,
            leading=20, textColor=colors.HexColor("#2C3E50"), spaceAfter=12,
        ),
        "TOCEntry": ParagraphStyle(
            "TOCEntry", fontName="Helvetica", fontSize=10,
            leading=14, leftIndent=10, spaceBefore=2, spaceAfter=1,
            textColor=colors.HexColor("#34495E"),
        ),
        "TrackHeading": ParagraphStyle(
            "TrackHeading", fontName="Helvetica-Bold", fontSize=13,
            leading=16, spaceBefore=0, spaceAfter=8,
            textColor=colors.white, backColor=colors.HexColor("#2C3E50"),
            borderPadding=(6, 10, 6, 10), keepWithNext=True,
        ),
        "CellN": ParagraphStyle("CellN", fontName="Helvetica",      fontSize=8, leading=10),
        "CellC": ParagraphStyle("CellC", fontName="Helvetica",      fontSize=8, leading=10, alignment=1),
        "CellH": ParagraphStyle("CellH", fontName="Helvetica-Bold", fontSize=9, leading=11,
                                textColor=colors.white, alignment=1),
        "CellLabel": ParagraphStyle("CellLabel", fontName="Helvetica-Bold", fontSize=9,
                                    leading=11, textColor=colors.white, alignment=1),
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_pdf(
    results: list[ExportLap],
    pdf_path: Path,
    cfg: AppConfig,
    track_order: list[str],
    *,
    external_records: list[dict] | None = None,
) -> set[str]:
    """
    Render the best-laps PDF.

    Parameters
    ----------
    results          : Cleaned flat export rows (internal data only).
    pdf_path         : Destination path for the PDF file.
    cfg              : Application configuration.
    track_order      : Canonical track list defining the sort order.
    external_records : Optional list of external best-lap dicts.  Each entry
                       must have: track, race_class, driver, car, best_lap,
                       best_lap_ms.  They are merged into the same tables as
                       internal results, sorted by time, and rendered with a
                       distinct light-blue background.  They do not contribute
                       to used_files (they have no image file).
    """
    if not results and not external_records:
        log.warning("[pdf] No results to render.")
        return set()

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    _archive_pdf(pdf_path)

    styles   = _build_styles()
    data_map = _build_data_map(results, cfg.gamertag, external_records or [])

    if not data_map:
        log.warning("[pdf] No valid data after building data map.")
        return set()

    order_index   = track_order_map(track_order)
    sorted_tracks = sorted(
        data_map,
        key=lambda t: track_order_key(t, order_index),
    )

    total_tracks  = len(data_map)
    total_classes = sum(len(c) for c in data_map.values())
    total_laps    = sum(len(rows) for t in data_map.values() for rows in t.values())
    ext_count     = len(external_records) if external_records else 0

    elems = []

    # ── Cover ──────────────────────────────────────────────────────────────
    elems.append(Spacer(1, 120))
    elems.append(Paragraph("Forza Motorsport", styles["TitleBig"]))
    elems.append(Paragraph("Best Laps", styles["TitleSub"]))
    elems.append(Spacer(1, 30))
    elems.append(HRFlowable(
        width="50%", thickness=2, color=colors.HexColor("#2C3E50"),
        spaceAfter=20, spaceBefore=0,
    ))
    elems.append(Paragraph(cfg.gamertag, styles["TitleName"]))
    now = datetime.now()
    elems.append(Paragraph(
        f"{now.day} de {MONTHS_PT[now.month]} de {now.year}",
        styles["TitleDate"],
    ))
    elems.append(Spacer(1, 30))
    elems.append(Paragraph(
        f"{total_tracks} tracks  ·  {total_classes} classes  ·  {total_laps} laps",
        styles["TitleStats"],
    ))

    # Colour legend — only shown when external records are present
    if ext_count:
        elems.append(Paragraph(
            f"Includes {ext_count} external record(s) — "
            f'<font color="{ROW_EXTERNAL}">■</font> '
            f"highlighted in blue",
            styles["TitleLegend"],
        ))

    elems.append(PageBreak())

    # ── TOC ────────────────────────────────────────────────────────────────
    toc = TableOfContents()
    toc.levelStyles = [styles["TOCEntry"]]
    elems.append(Paragraph("Track Index", styles["TOCTitle"]))
    elems.append(toc)
    elems.append(PageBreak())

    used_files: set[str] = set()

    for track in sorted_tracks:
        classes_in_track  = data_map[track]
        sorted_classes    = sorted(classes_in_track, key=class_order_key)
        track_heading_added = False

        for cls in sorted_classes:
            rows = classes_in_track[cls]
            if not rows:
                continue

            if not track_heading_added:
                elems.append(Paragraph(track, styles["TrackHeading"]))
                track_heading_added = True

            elems.append(_build_class_table(rows, cls, styles, cfg))
            elems.append(Spacer(1, 8))

            for row in rows:
                if row.get("file"):
                    used_files.add(row["file"])

        if track_heading_added:
            elems.append(PageBreak())

    # ── Footer with TOC back-link ──────────────────────────────────────────
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#95A5A6"))
        canvas.drawCentredString(
            doc.pagesize[0] / 2, 15,
            f"Forza Motorsport — Best Laps — Page {canvas.getPageNumber()}",
        )
        canvas.setFillColor(colors.HexColor("#7F8C8D"))
        canvas.drawRightString(doc.pagesize[0] - 30, 15, "TOC")
        canvas.linkRect(
            "", "toc",
            (doc.pagesize[0] - 48, 11, doc.pagesize[0] - 30, 21),
            relative=0, thickness=0,
        )
        canvas.restoreState()

    doc = _ForzaDocTemplate(
        str(pdf_path),
        pagesize=portrait(A4),
        leftMargin=30, rightMargin=30,
        topMargin=40, bottomMargin=40,
    )

    try:
        doc.multiBuild(elems, onFirstPage=_footer, onLaterPages=_footer)
    except Exception as exc:
        log.warning(f"[pdf] multiBuild failed ({exc}), falling back to simple build")
        fallback_elems = [e for e in elems if not isinstance(e, TableOfContents)]
        doc2 = SimpleDocTemplate(
            str(pdf_path), pagesize=portrait(A4),
            leftMargin=30, rightMargin=30, topMargin=40, bottomMargin=40,
        )
        doc2.build(fallback_elems, onFirstPage=_footer, onLaterPages=_footer)

    ext_msg = f" + {ext_count} external record(s)" if ext_count else ""
    log.info(f"[pdf] Written: {pdf_path}{ext_msg}")
    return used_files


# ── Data map builder ──────────────────────────────────────────────────────────

def _build_data_map(
    results:          list[ExportLap],
    gamertag:         str,
    external_records: list[dict],
) -> dict[str, dict[str, list[dict]]]:
    """
    Build the nested  { track → { class → [row, ...] } }  structure.

    Pass 1 — internal results from flat ExportLap rows.
    Pass 2 — external records injected with external=True, file=None.

    All rows within a (track, class) bucket are sorted by time ascending
    (fastest first).  External records appear in position 1 unless an
    internal driver beat the time.
    """
    data_map: dict[str, dict[str, list[dict]]] = {}
    gamertag_lower = gamertag.lower()

    for r in results:
        track = r.track or "Unknown"
        cls = r.race_class
        row = {
            "driver":   r.driver,
            "car":      r.car,
            "time_str": r.best_lap,
            "time_sec": r.best_lap_ms / 1000,
            "temp":     r.temp_c,
            "weather":  r.weather,
            "dirty":    r.dirty,
            "mine":     r.driver.lower() == gamertag_lower,
            "external": False,
            "file":     r.source_file,
        }
        data_map.setdefault(track, {}).setdefault(cls, []).append(row)

    # Pass 2: external records
    for rec in external_records:
        track = str(rec.get("track", "")).strip()
        cls   = str(rec.get("race_class", "")).strip()
        if not track or not cls:
            continue

        try:
            lap_sec = int(rec["best_lap_ms"]) / 1000
        except (KeyError, TypeError, ValueError):
            log.warning(f"[pdf] Skipping external record with invalid best_lap_ms: {rec}")
            continue

        row = {
            "driver":   str(rec.get("driver", "")).strip(),
            "car":      str(rec.get("car", "")).strip(),
            "time_str": str(rec.get("best_lap", "")).strip(),
            "time_sec": lap_sec,
            "temp":     None,    # external records have no session temperature
            "weather":  "dry",   # all external records are dry-condition bests
            "dirty":    False,
            "mine":     False,
            "external": True,
            "file":     None,    # no image file — not added to used_files
        }
        data_map.setdefault(track, {}).setdefault(cls, []).append(row)

    # Sort every bucket: fastest time first, player row before others on tie
    for track in data_map:
        for cls in data_map[track]:
            data_map[track][cls].sort(key=lambda x: (x["time_sec"], not x["mine"]))

    return data_map


# ── Table builder ─────────────────────────────────────────────────────────────

def _build_class_table(
    rows:   list[dict],
    cls:    str,
    styles: dict,
    cfg:    AppConfig,
) -> Table:
    """
    Build a single class table.  Row backgrounds:
      ROW_PLAYER   (#FFF8DC) — player's own lap
      ROW_EXTERNAL (#D6EAF8) — external / world record
      ROW_ALT      (#F8F9FA) — alternating rows for internal non-player laps
      (white)                — remaining internal rows
    """
    color_hex = CLASS_COLORS.get(cls, "#000000")
    cor       = colors.HexColor(color_hex)

    header = [
        Paragraph(f'<font color="white"><b>{cls}</b></font>', styles["CellLabel"]),
        Paragraph("Driver",   styles["CellH"]),
        Paragraph("Car",      styles["CellH"]),
        Paragraph("Best Lap", styles["CellH"]),
        Paragraph("Weather",  styles["CellH"]),
        Paragraph("°C",       styles["CellH"]),
    ]

    t_data = [header]
    for row in rows:
        time_clean = strip_dirty_symbol(str(row["time_str"]))

        if cfg.pdf.show_dirty_lap_symbol and row["dirty"]:
            time_cell = (
                f'<font color="#E74C3C">'
                f'{time_clean} {cfg.pdf.dirty_lap_symbol}'
                f'</font>'
            )
        else:
            time_cell = time_clean

        temp_str = str(row["temp"]) if row["temp"] is not None else "-"

        t_data.append([
            Paragraph("",                              styles["CellN"]),
            Paragraph(row["driver"],                   styles["CellN"]),
            Paragraph(row["car"],                      styles["CellN"]),
            Paragraph(time_cell,                       styles["CellC"]),
            Paragraph(str(row["weather"]).title(),     styles["CellC"]),
            Paragraph(temp_str,                        styles["CellC"]),
        ])

    col_widths = [35, 105, 195, 75, 55, 30]
    tbl        = Table(t_data, colWidths=col_widths)

    style_cmds = [
        ("BACKGROUND",    (0, 0), (-1,  0), cor),
        ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
        ("LINEBELOW",     (0, 0), (-1,  0), 1.5, colors.HexColor("#2C3E50")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]

    # Assign row background colours.  Priority: player > external > alternating.
    internal_non_player_idx = 0   # counter for alternating grey on internal rows
    for idx, row in enumerate(rows, start=1):
        if row["mine"]:
            style_cmds.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor(ROW_PLAYER)))
        elif row["external"]:
            style_cmds.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor(ROW_EXTERNAL)))
        else:
            internal_non_player_idx += 1
            if internal_non_player_idx % 2 == 0:
                style_cmds.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor(ROW_ALT)))

    tbl.setStyle(TableStyle(style_cmds))
    return KeepTogether([tbl])

