"""Executive-grade, ATS-optimized PDF renderer for software engineering resumes.

Produces clean, high-signal, single-page resumes with:
- Centered header and contact block with clickable links
- Clean uppercase section headers with divider rules
- Bold metrics, technologies, and inline code formatting
- Zero unicode missing glyphs (black boxes)
- Professional bullet point alignment and typography
- Automatic single-page budget enforcement
"""

import html
import os
import re
import unicodedata
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, KeepInFrame, Paragraph, SimpleDocTemplate


def _clean_glyphs(text: str) -> str:
    """Normalize unicode and replace non-ASCII / missing glyph characters."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    # Replace all unicode hyphens and dashes with standard ASCII hyphen
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00ad]", "-", text)
    # Replace all unicode spaces with standard space
    text = re.sub(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]", " ", text)
    # Replace unicode quotes
    text = re.sub(r"[\u2018\u2019\u201a\u201b]", "'", text)
    text = re.sub(r"[\u201c\u201d\u201e\u201f]", '"', text)
    # Replace mathematical and arrow symbols
    text = text.replace("→", "->").replace("←", "<-").replace("⇒", "=>")
    text = text.replace("×", "x").replace("≈", "~").replace("≥", ">=").replace("≤", "<=")
    return text


def _plain_markdown(text: str) -> str:
    """Helper for plain text normalization and escaping."""
    text = _clean_glyphs(text)
    text = re.sub(r"!\[[^]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_]+", "", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return html.escape(text.strip(), quote=True)


def _format_inline(text: str) -> str:
    """Safely format markdown inline styles (bold, italic, links, code) into ReportLab XML."""
    if not text:
        return ""

    text = _clean_glyphs(text)

    # 1. Protect markdown links: [label](url)
    md_links = []
    def md_link_sub(m):
        idx = len(md_links)
        md_links.append((m.group(1), m.group(2)))
        return f"XXMDLINK{idx}XX"
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", md_link_sub, text)

    # 2. Protect raw angle-bracket links: <http://...>
    raw_links = []
    def raw_link_sub(m):
        idx = len(raw_links)
        raw_links.append(m.group(1))
        return f"XXRAWURL{idx}XX"
    text = re.sub(r"<(https?://[^>]+)>", raw_link_sub, text)

    # 3. XML escape special entities
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 4. Markdown Bold: **text** -> <b>text</b>
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)

    # 5. Markdown Italic: *text* -> <i>text</i>
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)

    # 6. Markdown Inline code: `text` -> <b>text</b>
    text = re.sub(r"`([^`]+)`", r"<b>\1</b>", text)

    # 7. Restore markdown links
    for idx, (label, url) in enumerate(md_links):
        safe_label = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_label = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", safe_label)
        text = text.replace(f"XXMDLINK{idx}XX", f'<a href="{url}" color="#0284c7"><u>{safe_label}</u></a>')

    # 8. Restore raw URLs
    for idx, url in enumerate(raw_links):
        clean_url_text = url.replace("https://", "").replace("http://", "").rstrip("/")
        text = text.replace(f"XXRAWURL{idx}XX", f'<a href="{url}" color="#0284c7"><u>{clean_url_text}</u></a>')

    return text.strip()


def _build_flowables(markdown_text: str):
    """Parse markdown resume into structured ReportLab flowables."""
    styles = getSampleStyleSheet()

    color_primary = HexColor("#0f172a")    # Slate 900
    color_secondary = HexColor("#1e293b")  # Slate 800
    color_muted = HexColor("#475569")      # Slate 600
    color_line = HexColor("#64748b")       # Slate 500

    title_style = ParagraphStyle(
        "ResumeName",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15.0,
        leading=16.5,
        alignment=TA_CENTER,
        textColor=color_primary,
        spaceAfter=2,
    )

    contact_style = ParagraphStyle(
        "ResumeContact",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.0,
        leading=9.8,
        alignment=TA_CENTER,
        textColor=color_muted,
        spaceAfter=3,
    )

    section_heading_style = ParagraphStyle(
        "ResumeSectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=11.0,
        alignment=TA_LEFT,
        textColor=color_primary,
        spaceBefore=3.5,
        spaceAfter=0.5,
    )

    item_heading_style = ParagraphStyle(
        "ResumeItemHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.8,
        leading=10.5,
        alignment=TA_LEFT,
        textColor=color_primary,
        spaceBefore=2.5,
        spaceAfter=0.5,
    )

    item_subheading_style = ParagraphStyle(
        "ResumeItemSubHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=7.8,
        leading=9.2,
        alignment=TA_LEFT,
        textColor=color_muted,
        spaceBefore=0,
        spaceAfter=0.8,
    )

    body_style = ParagraphStyle(
        "ResumeBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.0,
        leading=9.5,
        alignment=TA_LEFT,
        textColor=color_secondary,
        spaceBefore=0.8,
        spaceAfter=0.8,
    )

    bullet_style = ParagraphStyle(
        "ResumeBullet",
        parent=body_style,
        leftIndent=9,
        firstLineIndent=-6,
        spaceBefore=0.4,
        spaceAfter=0.4,
    )

    flow = []
    raw_lines = markdown_text.splitlines()
    lines = [l.strip() for l in raw_lines]
    i = 0
    total = len(lines)

    # 1. Parse Candidate Name and Contact Info Block
    while i < total and not lines[i]:
        i += 1

    if i < total and (lines[i].startswith("#") or "madhav" in lines[i].lower() or (i + 1 < total and any(k in lines[i+1].lower() for k in ["email", "phone", "@", "linkedin"]))):
        name_line = re.sub(r"^#+\s*", "", lines[i]).strip()
        name_line = re.sub(r"^\*\*([^*]+)\*\*$", r"\1", name_line)
        flow.append(Paragraph(_format_inline(name_line), title_style))
        i += 1

        # Collect contact lines
        contact_parts = []
        while i < total:
            c_line = lines[i]
            if not c_line or c_line == "---" or c_line.startswith("#"):
                break
            clean_c = _clean_glyphs(c_line)
            tokens = [t.strip() for t in clean_c.split("|") if t.strip()]
            contact_parts.extend(tokens)
            i += 1

        if contact_parts:
            formatted_contact = " &nbsp;|&nbsp; ".join([_format_inline(p) for p in contact_parts])
            flow.append(Paragraph(formatted_contact, contact_style))

    # 2. Parse Remaining Sections
    while i < total:
        line = lines[i]
        i += 1

        if not line or line == "---" or line.startswith("*Prepared for"):
            continue

        # Header 2: Section Heading (e.g. ## Professional Experience or ## **Professional Experience**)
        if line.startswith("## "):
            clean_heading = re.sub(r"[*#_]+", "", line[3:]).strip().upper()
            flow.append(Paragraph(clean_heading, section_heading_style))
            flow.append(HRFlowable(width="100%", thickness=0.8, color=color_line, spaceBefore=1, spaceAfter=2))
            continue

        # Header 3: Job Title / Project Name
        if line.startswith("### "):
            clean_item = line[4:].strip()
            flow.append(Paragraph(_format_inline(clean_item), item_heading_style))
            continue

        # Bullet point
        if re.match(r"^(?:[-*]|\d+[.)])\s+", line):
            clean_bullet = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line)
            formatted_text = _format_inline(clean_bullet)
            flow.append(Paragraph(f"&bull;&nbsp; {formatted_text}", bullet_style))
            continue

        # Sub-heading or italicized metadata line (e.g. *Jun 2025 – Jul 2025* or *GitHub: ...*)
        if (line.startswith("*") and line.endswith("*")) or line.startswith("—") or line.startswith("-"):
            formatted_text = _format_inline(line)
            flow.append(Paragraph(formatted_text, item_subheading_style))
            continue

        # General body text (Objective, Education detail, Skills categories)
        formatted_text = _format_inline(line)
        flow.append(Paragraph(formatted_text, body_style))

    return flow


def markdown_to_pdf(markdown_text: str, output_path: str, single_page: bool = False) -> str:
    """Render Markdown into a clean, executive ATS PDF allowing natural multi-page flow."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.40 * inch,
        leftMargin=0.40 * inch,
        topMargin=0.35 * inch,
        bottomMargin=0.35 * inch,
        title=os.path.basename(output_path),
        author="Madhav Jayam",
    )

    flowables = _build_flowables(markdown_text)
    if single_page:
        content = KeepInFrame(doc.width, doc.height, flowables, mode="shrink")
        doc.build([content])
    else:
        doc.build(flowables)
    return output_path
