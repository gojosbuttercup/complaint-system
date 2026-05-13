from html import escape
import logging
import traceback
from io import BytesIO

from services.analytics_service import build_dashboard_data

logger = logging.getLogger(__name__)


class PDFReportError(RuntimeError):
    pass


def _reportlab_import_error(exc: ImportError, step: str) -> PDFReportError:
    """Only claim reportlab is missing when the top-level package is missing."""
    missing = getattr(exc, "name", None)
    if missing == "reportlab" or (
        isinstance(exc, ModuleNotFoundError) and exc.name == "reportlab"
    ):
        return PDFReportError(
            "reportlab is not installed. Install with: pip install reportlab "
            "(or pip install -r requirements.txt)."
        )
    return PDFReportError(
        f"PDF export failed while importing {step}: {exc!s}\n"
        f"(This is often a missing dependency of reportlab, not reportlab itself.)\n"
        f"Traceback:\n{traceback.format_exc()}"
    )


def _load_reportlab():
    try:
        from reportlab.lib import colors
    except ImportError as exc:
        logger.exception("reportlab import failed: reportlab.lib.colors")
        raise _reportlab_import_error(exc, "reportlab.lib.colors") from exc

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.pagesizes import landscape
    except ImportError as exc:
        logger.exception("reportlab import failed: reportlab.lib.pagesizes")
        raise _reportlab_import_error(exc, "reportlab.lib.pagesizes") from exc

    try:
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError as exc:
        logger.exception("reportlab import failed: reportlab.lib.styles")
        raise _reportlab_import_error(exc, "reportlab.lib.styles") from exc

    try:
        from reportlab.platypus import SimpleDocTemplate
        from reportlab.platypus import Paragraph
        from reportlab.platypus import Spacer
        from reportlab.platypus import Table
        from reportlab.platypus import TableStyle
    except ImportError as exc:
        logger.exception("reportlab import failed: reportlab.platypus")
        raise _reportlab_import_error(exc, "reportlab.platypus") from exc

    return colors, landscape, letter, getSampleStyleSheet, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _cell(value, style, Paragraph):
    text = escape(str(value or ""))
    return Paragraph(text, style)


def build_complaints_pdf(complaints, departments, title="CIVITAS Complaint Report"):
    colors, landscape, letter, getSampleStyleSheet, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle = _load_reportlab()
    analytics = build_dashboard_data(complaints, departments)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=24,
        leftMargin=24,
        topMargin=24,
        bottomMargin=24,
        pageCompression=0,
    )
    styles = getSampleStyleSheet()
    cell_style = styles["BodyText"]
    cell_style.fontSize = 7
    cell_style.leading = 9
    elements = [Paragraph(title, styles["Title"]), Spacer(1, 12)]

    summary = [
        ["Total", str(len(complaints))],
        ["Pending", str(analytics["status_counts"].get("pending", 0))],
        ["In Progress", str(analytics["status_counts"].get("in_progress", 0))],
        ["Resolved", str(analytics["status_counts"].get("resolved", 0))],
        ["Rejected", str(analytics["status_counts"].get("rejected", 0))],
        ["Avg Resolution Hours", str(analytics["avg_resolution_hours"])],
    ]
    summary_table = Table(summary, colWidths=[160, 120])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.extend([summary_table, Spacer(1, 16)])

    table_data = [["ID", "Name", "Email", "Category", "Urgency", "Department", "Status", "Filed"]]
    for complaint in complaints:
        table_data.append([
            _cell(f"#{complaint.id}", cell_style, Paragraph),
            _cell(complaint.name, cell_style, Paragraph),
            _cell(complaint.email, cell_style, Paragraph),
            _cell(complaint.category, cell_style, Paragraph),
            _cell(complaint.urgency, cell_style, Paragraph),
            _cell(complaint.department, cell_style, Paragraph),
            _cell(complaint.status, cell_style, Paragraph),
            _cell(complaint.timestamp.strftime("%Y-%m-%d %H:%M") if complaint.timestamp else "", cell_style, Paragraph),
        ])

    if len(table_data) == 1:
        table_data.append(["No complaints found for the selected filters.", "", "", "", "", "", "", ""])

    table = Table(table_data, repeatRows=1, colWidths=[45, 95, 135, 80, 65, 130, 70, 95])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(table)

    try:
        doc.build(elements)
    except Exception as exc:
        logger.exception("reportlab SimpleDocTemplate.build failed")
        raise PDFReportError(
            f"Failed to generate PDF report: {exc!s}\n\nTraceback:\n{traceback.format_exc()}"
        ) from exc

    buffer.seek(0)
    head = buffer.read(5)
    buffer.seek(0)
    if head != b"%PDF-":
        raise PDFReportError(
            "Generated report is not a valid PDF document "
            f"(expected %PDF- header, got {head!r})."
        )
    buffer.seek(0)
    return buffer
