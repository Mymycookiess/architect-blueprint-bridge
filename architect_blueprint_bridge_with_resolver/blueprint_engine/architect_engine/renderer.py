from __future__ import annotations

import html
import os
import re

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ReportLab's built-in Type 1 fonts rendered with broken character spacing in
# production PDFs. Vera ships with ReportLab, so it is available in the same
# container everywhere and can be embedded in every customer document.
_REPORTLAB_FONT_DIR = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
pdfmetrics.registerFont(TTFont("BlueprintSans", os.path.join(_REPORTLAB_FONT_DIR, "Vera.ttf")))
pdfmetrics.registerFont(TTFont("BlueprintSans-Bold", os.path.join(_REPORTLAB_FONT_DIR, "VeraBd.ttf")))

BG = colors.HexColor("#FAF9F6")
INK = colors.HexColor("#171717")
MUTED = colors.HexColor("#616161")
GOLD = colors.HexColor("#9B7A3D")
RULE = colors.HexColor("#D8D2C7")
LEFT = 0.72 * inch
RIGHT = 0.72 * inch
TOP = 0.72 * inch
BOTTOM = 0.62 * inch
PAGE_W, PAGE_H = letter
BODY_WIDTH = PAGE_W - LEFT - RIGHT

INTERNAL_PREFIXES = (
    r"Bottom quote\s*[:—-]\s*",
    r"Interpretive boundary\s*[:—-]\s*",
    r"Verified chart note\s*[—:-]\s*",
    r"Verified aspect(?: for [^:]+)?\s*[:—-]\s*",
    r"Validated synthesis aspect\s*[:—-]\s*",
    r"(?:Big Three|Inner-wiring|Relationship|Career|Growth|Whole-chart) synthesis\s*[:—-]\s*",
    r"House synthesis for this life area\s*[:—-]\s*",
    r"(?:Relationship|Career|Growth|Alignment|Action-plan|Summary|Blueprint) (?:chart |axis )?anchor\s*[—:-]\s*",
    r"Recurring validated element pattern\s*[:—-]\s*",
    r"Lived experience\s*[:—-]\s*",
)
INTERNAL_TERMS = (
    "qa", "source id", "source ids", "selector", "context payload", "normalized data", "regression",
    "provider response", "ai writer", "internal validation", "bottom quote", "interpretive boundary",
    "validated factors", "relationship axis anchor", "summary anchor", "blueprint anchor",
    "verified chart note", "validated synthesis aspect",
)
PLACEHOLDER_PATTERNS = (
    re.compile(r"\bCUSTOMER\s+NAME\b", re.I),
    re.compile(r"@CUSTOMER(?:_NAME|\s+NAME)?@", re.I),
    re.compile(r"\{\{[^{}]+\}\}"),
    re.compile(r"\$\{[^{}]+\}"),
    re.compile(r"\[(?:INSERT|PLACEHOLDER|TODO|TBD)[^]]*\]", re.I),
    re.compile(r"<<?(?:INSERT|PLACEHOLDER|TODO|TBD)[^>]*>>?", re.I),
)

JOURNEY = (
    ("DISCOVER", "Welcome to Your Blueprint", "Birth Chart Snapshot"),
    ("UNDERSTAND", "Your Core Identity - Sun", "Your Emotional World - Moon", "How the World Meets You - Rising", "Your Big Three", "Your Houses / Life Areas", "Your Inner Wiring"),
    ("REFLECT", "Your Relationship Blueprint", "Your Career & Purpose Blueprint", "Your Growth Blueprint"),
    ("BUILD", "Alignment & Action", "Personalized Action Plan", "Your First / Next Brick"),
    ("CONTINUE", "Your Blueprint Summary", "Your Next Chapter / Continue"),
)


def _customer_text(text: str) -> str:
    cleaned = html.unescape(str(text or "")).replace("\u00a0", " ").strip()
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned)
    for pattern in INTERNAL_PREFIXES:
        cleaned = re.sub(r"^" + pattern, "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _safe_markup(text: str) -> str:
    """Escape customer text, then convert the supported Markdown emphasis to ReportLab markup."""
    text = html.escape(_customer_text(text), quote=False)
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+?)__", r"<b>\1</b>", text)
    text = text.replace("—", "-").replace("–", "-")
    return text


def _is_heading(line: str) -> bool:
    raw = re.sub(r"\*\*", "", line).strip()
    alpha = re.sub(r"[^A-Za-z]", "", raw)
    return bool(alpha) and len(raw) <= 96 and len(raw.split()) <= 14 and raw.upper() == raw


def _is_list(line: str) -> bool:
    return bool(re.match(r"^\s*(?:[-*•]|\d+[.)]|[A-Z][.)])\s+", line))


def _clean_list_prefix(line: str) -> str:
    return re.sub(r"^\s*(?:[-*•]|\d+[.)]|[A-Z][.)])\s+", "", line).strip()


def _styles():
    return {
        "cover_brand": ParagraphStyle("cover_brand", fontName="BlueprintSans-Bold", fontSize=12, leading=15, textColor=GOLD, alignment=TA_CENTER, spaceAfter=18),
        "cover_title": ParagraphStyle("cover_title", fontName="BlueprintSans-Bold", fontSize=28, leading=34, textColor=INK, alignment=TA_CENTER, spaceAfter=14),
        "cover_sub": ParagraphStyle("cover_sub", fontName="BlueprintSans", fontSize=12.2, leading=17, textColor=MUTED, alignment=TA_CENTER, spaceAfter=26),
        "cover_name": ParagraphStyle("cover_name", fontName="BlueprintSans-Bold", fontSize=20, leading=24, textColor=INK, alignment=TA_CENTER, spaceAfter=14),
        "chapter": ParagraphStyle("chapter", fontName="BlueprintSans-Bold", fontSize=20, leading=24, textColor=INK, alignment=TA_CENTER, keepWithNext=True, spaceAfter=8),
        "chapter_rule": ParagraphStyle("chapter_rule", fontName="BlueprintSans", fontSize=8, leading=8, textColor=GOLD, alignment=TA_CENTER, keepWithNext=True, spaceAfter=18),
        "heading": ParagraphStyle("heading", fontName="BlueprintSans-Bold", fontSize=11.4, leading=15.5, textColor=INK, spaceBefore=9, spaceAfter=5, keepWithNext=True),
        "body": ParagraphStyle("body", fontName="BlueprintSans", fontSize=10.55, leading=15.6, textColor=INK, alignment=TA_LEFT, spaceAfter=8.5, splitLongWords=False, allowWidows=0, allowOrphans=0),
        "list": ParagraphStyle("list", parent=None, fontName="BlueprintSans", fontSize=10.45, leading=15.2, leftIndent=15, firstLineIndent=-9, textColor=INK, spaceAfter=5.5, bulletIndent=5, allowWidows=0, allowOrphans=0),
        "journey_title": ParagraphStyle("journey_title", fontName="BlueprintSans-Bold", fontSize=22, leading=27, textColor=INK, alignment=TA_CENTER, spaceAfter=10),
        "journey_stage": ParagraphStyle("journey_stage", fontName="BlueprintSans-Bold", fontSize=10.2, leading=13, textColor=GOLD, alignment=TA_CENTER, spaceAfter=2),
        "journey_body": ParagraphStyle("journey_body", fontName="BlueprintSans", fontSize=9.4, leading=13.4, textColor=INK, alignment=TA_CENTER),
        "birth_label": ParagraphStyle("birth_label", fontName="BlueprintSans-Bold", fontSize=9.6, leading=12, textColor=MUTED),
        "birth_value": ParagraphStyle("birth_value", fontName="BlueprintSans", fontSize=10.2, leading=13, textColor=INK),
    }


def _customer_name(payload: dict) -> str:
    customer = payload.get("customer") or {}
    if isinstance(customer, dict):
        return str(customer.get("name") or "Your Blueprint").strip()
    return str(customer or "Your Blueprint").strip()


def _birth_rows(payload: dict, styles: dict):
    customer = payload.get("customer") or {}
    if not isinstance(customer, dict):
        return []
    mode = payload.get("mode") or ""
    date = customer.get("birth_date") or "Not provided"
    time = customer.get("birth_time_local") or "Unknown"
    status = customer.get("birth_time_status") or ("KNOWN" if customer.get("birth_time_local") else "UNKNOWN")
    location = customer.get("birth_location_display") or "Not provided"
    scope = "Full chart calculation" if mode == "FULL" else "Time-independent chart calculation; Rising and houses omitted"
    if str(status).upper() != "KNOWN":
        time = "Unknown / not supplied"
    pairs = (
        ("Birth date", date),
        ("Birth time", time),
        ("Birth location", location),
        ("Blueprint scope", scope),
    )
    return [[Paragraph(k, styles["birth_label"]), Paragraph(_safe_markup(v), styles["birth_value"])] for k, v in pairs]


def _content_flowables(content: str, styles: dict):
    flow = []
    blocks = [b.strip() for b in re.split(r"\n\s*\n", content or "") if b.strip()]
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        body_buffer = []

        def flush_body():
            if body_buffer:
                text = " ".join(body_buffer)
                flow.append(Paragraph(_safe_markup(text), styles["body"]))
                body_buffer.clear()

        for line in lines:
            stripped = re.sub(r"^#{1,6}\s+", "", line).strip()
            if _is_heading(stripped):
                flush_body()
                flow.append(Paragraph(_safe_markup(stripped), styles["heading"]))
            elif _is_list(stripped):
                flush_body()
                item = _clean_list_prefix(stripped)
                flow.append(Paragraph("• " + _safe_markup(item), styles["list"]))
            else:
                body_buffer.append(stripped)
        flush_body()
    return flow


class BlueprintDocTemplate(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        super().__init__(filename, pagesize=letter, leftMargin=LEFT, rightMargin=RIGHT, topMargin=TOP, bottomMargin=BOTTOM, **kwargs)
        frame = Frame(LEFT, BOTTOM, BODY_WIDTH, PAGE_H - TOP - BOTTOM, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="body")
        self.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=self._decorate_page))
        self._blueprint_page_count = 0

    def _decorate_page(self, canv, doc):
        self._blueprint_page_count = max(self._blueprint_page_count, doc.page)
        canv.saveState()
        canv.setFillColor(BG)
        canv.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        if doc.page > 1:
            canv.setStrokeColor(RULE)
            canv.setLineWidth(0.45)
            canv.line(LEFT, 34, PAGE_W - RIGHT, 34)
            canv.setFillColor(MUTED)
            canv.setFont("BlueprintSans", 7.2)
            canv.drawString(LEFT, 20, "THE ARCHITECT BLUEPRINT")
            canv.drawRightString(PAGE_W - RIGHT, 20, str(doc.page - 1))
        canv.restoreState()


def _cover_story(payload: dict, styles: dict):
    name = html.escape(_customer_name(payload))
    return [
        Spacer(1, 1.35 * inch),
        Paragraph("THE ARCHITECT BLUEPRINT", styles["cover_brand"]),
        Paragraph("A Personalized Blueprint for Building Your Life", styles["cover_title"]),
        Spacer(1, 0.18 * inch),
        Paragraph("Prepared Exclusively For", styles["cover_sub"]),
        Paragraph(name, styles["cover_name"]),
        Spacer(1, 0.55 * inch),
        Paragraph("BUILD YOUR LIFE. BRICK BY BRICK.", styles["cover_brand"]),
        PageBreak(),
    ]


def _journey_story(styles: dict):
    story = [Spacer(1, 0.25 * inch), Paragraph("YOUR BLUEPRINT JOURNEY", styles["journey_title"]), Paragraph("DISCOVER  -  UNDERSTAND  -  REFLECT  -  BUILD  -  CONTINUE", styles["cover_sub"]), Spacer(1, 0.12 * inch)]
    rows = []
    for stage in JOURNEY:
        stage_name, *chapters = stage
        rows.append([
            Paragraph(stage_name, styles["journey_stage"]),
            Paragraph("<br/>".join(html.escape(ch) for ch in chapters), styles["journey_body"]),
        ])
    table = Table(rows, colWidths=[1.55 * inch, BODY_WIDTH - 1.55 * inch], hAlign="CENTER")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.45, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.extend([table, PageBreak()])
    return story


def render_pdf(payload: dict, out_path: str, return_diagnostics=False):
    styles = _styles()
    doc = BlueprintDocTemplate(out_path, title="The Architect Blueprint", author="The Architect Blueprint")
    story = []
    story.extend(_cover_story(payload, styles))
    story.extend(_journey_story(styles))

    included_sections = [s for s in payload.get("sections", []) if s.get("status") != "OMITTED_BY_MODE" and str(s.get("content") or "").strip()]
    for idx, section in enumerate(included_sections):
        title = str(section.get("title") or "").strip()
        if title.upper() in ("THE ARCHITECT BLUEPRINT", "PERSONALIZED COVER"):
            continue
        if story and not isinstance(story[-1], PageBreak):
            story.append(PageBreak())
        story.extend([
            Spacer(1, 0.22 * inch),
            Paragraph(_safe_markup(title.upper()), styles["chapter"]),
            HRFlowable(width=0.55 * inch, thickness=0.7, color=GOLD, spaceBefore=0, spaceAfter=18, hAlign="CENTER"),
        ])
        if title == "Birth Chart Snapshot":
            rows = _birth_rows(payload, styles)
            if rows:
                birth_table = Table(rows, colWidths=[1.35 * inch, BODY_WIDTH - 1.35 * inch], hAlign="LEFT")
                birth_table.setStyle(TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.55, RULE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, RULE),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1EEE7")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]))
                story.extend([
                    Paragraph("Birth Information Used for Your Blueprint", styles["heading"]),
                    birth_table,
                    Spacer(1, 0.18 * inch),
                ])
        flow = _content_flowables(str(section.get("content") or ""), styles)
        # Keep headings with the paragraph that follows them whenever possible.
        grouped = []
        i = 0
        while i < len(flow):
            current = flow[i]
            if isinstance(current, Paragraph) and current.style.name == "heading" and i + 1 < len(flow):
                grouped.append(KeepTogether([current, flow[i + 1]]))
                i += 2
            else:
                grouped.append(current)
                i += 1
        story.extend(grouped)
        if idx < len(included_sections) - 1:
            story.append(PageBreak())

    doc.build(story)

    visible = "\n".join(str(section.get("content") or "") for section in included_sections)
    diagnostics = {
        "blank_pages": [],
        "orphaned_headings": [],
        "unresolved_placeholders": sorted({m.group(0) for p in PLACEHOLDER_PATTERNS for m in p.finditer(visible)}),
        "internal_terms": sorted(t for t in INTERNAL_TERMS if re.search(rf"\b{re.escape(t)}\b", visible, re.I)),
        "raw_orb_values": sorted(set(re.findall(r"\borb\s*[:=]?\s*\d+(?:\.\d+)?\s*°?", visible, re.I))),
        "markdown_bold_markers": bool(re.search(r"\*\*[^*]+\*\*|__[^_]+__", _safe_markup(visible))),
        "page_body_lines": [],
    }
    page_no = max(1, getattr(doc, "_blueprint_page_count", 1))
    return (page_no, diagnostics) if return_diagnostics else page_no
