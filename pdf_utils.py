"""Compact, ATS-friendly PDF rendering for generated application materials."""

import html
import os
import re
import unicodedata

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepInFrame, Paragraph, SimpleDocTemplate


def _plain_markdown(line: str) -> str:
    line = re.sub(r"!\[[^]]*\]\([^)]*\)", "", line)
    line = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"[`*_]+", "", line)
    line = unicodedata.normalize("NFKD", line)
    line = line.replace("—", "-").replace("–", "-").replace("‑", "-")
    line = line.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    line = line.encode("ascii", "ignore").decode("ascii")
    return html.escape(line.strip())


def _flowables(markdown_text: str):
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ATSName", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=13,
        leading=14, alignment=TA_CENTER, spaceAfter=3,
    )
    heading = ParagraphStyle(
        "ATSHeading", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9.5,
        leading=10.5, spaceBefore=3, spaceAfter=1,
    )
    body = ParagraphStyle(
        "ATSBody", parent=styles["Normal"], fontName="Helvetica", fontSize=8.4,
        leading=9.6, alignment=TA_LEFT, spaceAfter=1,
    )
    bullet = ParagraphStyle("ATSBullet", parent=body, leftIndent=9, firstLineIndent=-6)

    flow = []
    first_content = True
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        if line.startswith("#"):
            text = _plain_markdown(line.lstrip("# "))
            flow.append(Paragraph(text, title if first_content else heading))
            first_content = False
        elif re.match(r"^(?:[-*]|\d+[.)])\s+", line):
            text = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line)
            flow.append(Paragraph("&#8226; " + _plain_markdown(text), bullet))
        else:
            flow.append(Paragraph(_plain_markdown(line), body))
            first_content = False
    return flow


def markdown_to_pdf(markdown_text: str, output_path: str) -> str:
    """Render Markdown into a compact single-page PDF, shrinking if necessary."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc = SimpleDocTemplate(
        output_path, pagesize=LETTER,
        rightMargin=0.55 * inch, leftMargin=0.55 * inch,
        topMargin=0.45 * inch, bottomMargin=0.45 * inch,
        title=os.path.basename(output_path), author="Job Hunter",
    )
    content = KeepInFrame(doc.width, doc.height, _flowables(markdown_text), mode="shrink")
    doc.build([content])
    return output_path
