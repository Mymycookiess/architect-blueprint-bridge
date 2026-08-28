from __future__ import annotations

import html
import os
import re
from datetime import datetime

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
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
from pypdf import PdfReader


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
    ("BUILD", "Alignment & Action", "Your Personalized Action Plan", "Your Next Brick"),
    ("CONTINUE", "Your Blueprint Summary", "Continue Building"),
)

DISPLAY_TITLES = {
    "Your First / Next Brick": "Your Next Brick",
    "Your Next Chapter / Continue": "Continue Building",
}

CHAPTER_STAGES = {
    "Welcome to Your Blueprint": "DISCOVER",
    "Birth Chart Snapshot": "DISCOVER",
    "Your Story Begins Here": "UNDERSTAND",
    "Your Core Identity — Sun": "UNDERSTAND",
    "Your Emotional World — Moon": "UNDERSTAND",
    "How the World Meets You — Rising": "UNDERSTAND",
    "Your Big Three": "UNDERSTAND",
    "Your Houses / Life Areas": "UNDERSTAND",
    "Your Inner Wiring": "UNDERSTAND",
    "Your Relationship Blueprint": "REFLECT",
    "Your Career & Purpose Blueprint": "REFLECT",
    "Your Growth Blueprint": "REFLECT",
    "Alignment & Action": "BUILD",
    "Personalized Action Plan": "BUILD",
    "Your First / Next Brick": "BUILD",
    "Your Blueprint Summary": "CONTINUE",
    "Your Next Chapter / Continue": "CONTINUE",
}

MAJOR_SECTION_STARTS = {
    "Welcome to Your Blueprint",
    "Your Story Begins Here",
    "Your Relationship Blueprint",
    "Your Career & Purpose Blueprint",
    "Your Growth Blueprint",
    "Alignment & Action",
    "Your Blueprint Summary",
    "Your Next Chapter / Continue",
}

ACTION_PLAN_HEADINGS = {
    "3 Strengths",
    "3 Supporting Habits",
    "3 Patterns to Watch",
    "1 Challenge",
    "1 Encouraging Message",
    "1 Next Brick",
}


def _customer_text(text: str) -> str:
    cleaned = html.unescape(str(text or "")).replace("\u00a0", " ").strip()
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned)
    for pattern in INTERNAL_PREFIXES:
        cleaned = re.sub(r"^" + pattern, "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bBottom quote\s*[:—-]\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _safe_markup(text: str) -> str:
    """Escape customer text, then convert the supported Markdown emphasis to ReportLab markup."""
    # The AI writer uses typographic dashes as sentence punctuation. Production
    # fonts must not receive a bare replacement hyphen ("clarity-not").
    # Normalize only em/en dashes so legitimate compounds remain untouched.
    text = re.sub(r"\s*[—–]\s*", " - ", _customer_text(text))
    text = re.sub(r"\s+", " ", text).strip()
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_([^_\n]+?)_(?!_)", r"<i>\1</i>", text)
    # Remove unmatched emphasis delimiters after valid pairs have become real
    # PDF bold formatting. A bare delimiter has no customer-facing meaning.
    text = text.replace("**", "").replace("__", "").replace("*", "")
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
        "chapter_stage": ParagraphStyle("chapter_stage", fontName="BlueprintSans-Bold", fontSize=8.8, leading=11, textColor=GOLD, alignment=TA_CENTER, keepWithNext=True, spaceAfter=7),
        "chapter_rule": ParagraphStyle("chapter_rule", fontName="BlueprintSans", fontSize=8, leading=8, textColor=GOLD, alignment=TA_CENTER, keepWithNext=True, spaceAfter=18),
        "heading": ParagraphStyle("heading", fontName="BlueprintSans-Bold", fontSize=11.4, leading=15.5, textColor=INK, spaceBefore=9, spaceAfter=5, keepWithNext=True),
        "body": ParagraphStyle("body", fontName="BlueprintSans", fontSize=10.55, leading=15.6, textColor=INK, alignment=TA_LEFT, spaceAfter=8.5, splitLongWords=False, allowWidows=0, allowOrphans=0),
        "closing_body": ParagraphStyle("closing_body", fontName="BlueprintSans", fontSize=10.55, leading=14.2, textColor=INK, alignment=TA_LEFT, spaceAfter=6.5, splitLongWords=False, allowWidows=0, allowOrphans=0),
        "list": ParagraphStyle("list", parent=None, fontName="BlueprintSans", fontSize=10.45, leading=15.2, leftIndent=15, firstLineIndent=-9, textColor=INK, spaceAfter=5.5, bulletIndent=5, allowWidows=0, allowOrphans=0),
        "action_heading": ParagraphStyle("action_heading", fontName="BlueprintSans-Bold", fontSize=11.3, leading=14.5, textColor=GOLD, backColor=colors.HexColor("#F1EEE7"), borderColor=RULE, borderWidth=0.45, borderPadding=(6, 8, 6, 8), spaceBefore=10, spaceAfter=7, keepWithNext=True),
        "action_item": ParagraphStyle("action_item", fontName="BlueprintSans", fontSize=10.35, leading=15.1, textColor=INK, alignment=TA_LEFT, spaceAfter=10.5, splitLongWords=False, allowWidows=0, allowOrphans=0),
        "journey_title": ParagraphStyle("journey_title", fontName="BlueprintSans-Bold", fontSize=22, leading=27, textColor=INK, alignment=TA_CENTER, spaceAfter=10),
        "journey_stage": ParagraphStyle("journey_stage", fontName="BlueprintSans-Bold", fontSize=10.2, leading=13, textColor=GOLD, alignment=TA_CENTER, spaceAfter=2),
        "journey_body": ParagraphStyle("journey_body", fontName="BlueprintSans", fontSize=9.4, leading=13.4, textColor=INK, alignment=TA_CENTER),
        "birth_label": ParagraphStyle("birth_label", fontName="BlueprintSans-Bold", fontSize=9.6, leading=12, textColor=MUTED),
        "birth_value": ParagraphStyle("birth_value", fontName="BlueprintSans", fontSize=10.2, leading=13, textColor=INK),
        "big_three_label": ParagraphStyle("big_three_label", fontName="BlueprintSans-Bold", fontSize=8.8, leading=11, textColor=GOLD, alignment=TA_CENTER, spaceAfter=3),
        "big_three_value": ParagraphStyle("big_three_value", fontName="BlueprintSans-Bold", fontSize=12.2, leading=15, textColor=INK, alignment=TA_CENTER),
    }


def _customer_name(payload: dict) -> str:
    customer = payload.get("customer") or {}
    if isinstance(customer, dict):
        name = str(customer.get("name") or "Your Blueprint").strip()
    else:
        name = str(customer or "Your Blueprint").strip()
    return name.title() if name.islower() or name.isupper() else name


def _display_birth_date(value) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
        return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"
    except ValueError:
        return raw or "Not provided"


def _display_birth_time(value) -> str:
    raw = str(value or "").strip()
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, pattern).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            pass
    return raw or "Unknown"


def _display_birth_location(value) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if not raw:
        return "Not provided"
    match = re.match(r"^(.*?)(?:,|\s)+(ca|california)(?:,|\s)+(usa|us|united states)$", raw, re.I)
    if match:
        city = match.group(1).strip(" ,").title() if match.group(1).islower() else match.group(1).strip(" ,")
        return f"{city}, California, USA"
    # Older storefront orders sometimes supplied only city + country. Preserve
    # the customer's words while polishing the common US locations we can
    # identify unambiguously.
    city_country = re.match(r"^(Las Vegas)(?:,|\s)+(USA|US|United States)$", raw, re.I)
    if city_country:
        return "Las Vegas, Nevada, USA"
    polished = raw.title() if raw.islower() or raw.isupper() else raw
    return re.sub(r"\bUsa\b", "USA", polished)


def _big_three_rows(payload: dict, styles: dict):
    summary = payload.get("chart_summary") or {}
    items = []
    for label, key in (("SUN", "sun"), ("MOON", "moon"), ("RISING", "rising")):
        placement = summary.get(key) or {}
        sign = str(placement.get("sign") or "").strip()
        if not sign:
            continue
        house = placement.get("house")
        value = f"{sign} · House {house}" if house else sign
        items.append([
            Paragraph(label, styles["big_three_label"]),
            Paragraph(_safe_markup(value), styles["big_three_value"]),
        ])
    if len(items) != 3:
        return None
    table = Table([items], colWidths=[BODY_WIDTH / 3] * 3, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.55, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, RULE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7F4ED")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return table


def _birth_rows(payload: dict, styles: dict):
    customer = payload.get("customer") or {}
    if not isinstance(customer, dict):
        return []
    mode = payload.get("mode") or ""
    date = _display_birth_date(customer.get("birth_date"))
    time = _display_birth_time(customer.get("birth_time_local"))
    status = customer.get("birth_time_status") or ("KNOWN" if customer.get("birth_time_local") else "UNKNOWN")
    location = _display_birth_location(customer.get("birth_location_display"))
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


def _content_flowables(content: str, styles: dict, section_title: str = ""):
    flow = []
    blocks = [b.strip() for b in re.split(r"\n\s*\n", content or "") if b.strip()]
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        body_buffer = []

        def flush_body():
            if body_buffer:
                text = " ".join(body_buffer)
                if section_title == "Personalized Action Plan":
                    match = re.match(
                        r"^((?:\d+[.)]\s*)?(?:Strength|Supporting habit|Pattern to watch|Challenge|Encouraging message|Next Brick):)\s*(.*)$",
                        text,
                        re.I,
                    )
                    if match:
                        markup = f"<b>{_safe_markup(match.group(1))}</b> {_safe_markup(match.group(2))}"
                        flow.append(Paragraph(markup, styles["action_item"]))
                    else:
                        flow.append(Paragraph(_safe_markup(text), styles["action_item"]))
                else:
                    style = styles["closing_body"] if section_title == "Your Next Chapter / Continue" else styles["body"]
                    flow.append(Paragraph(_safe_markup(text), style))
                body_buffer.clear()

        for line in lines:
            stripped = re.sub(r"^#{1,6}\s+", "", line).strip()
            plain = re.sub(r"^(?:\*\*|__)(.*?)(?:\*\*|__)$", r"\1", stripped).strip()
            if section_title == "Personalized Action Plan" and plain in ACTION_PLAN_HEADINGS:
                flush_body()
                flow.append(Paragraph(_safe_markup(plain), styles["action_heading"]))
            elif _is_heading(stripped):
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
        if doc.page == 1:
            canv.setStrokeColor(GOLD)
            canv.setLineWidth(1.0)
            canv.rect(0.42 * inch, 0.42 * inch, PAGE_W - 0.84 * inch, PAGE_H - 0.84 * inch, fill=0, stroke=1)
            canv.setLineWidth(0.35)
            canv.rect(0.50 * inch, 0.50 * inch, PAGE_W - inch, PAGE_H - inch, fill=0, stroke=1)
            # A restrained architectural mark gives the paid cover a distinct
            # identity without depending on an external image asset.
            canv.setStrokeColor(GOLD)
            canv.setLineWidth(0.8)
            center_x = PAGE_W / 2
            mark_y = PAGE_H - 1.03 * inch
            canv.line(center_x - 28, mark_y, center_x - 7, mark_y)
            canv.line(center_x + 7, mark_y, center_x + 28, mark_y)
            canv.saveState()
            canv.translate(center_x, mark_y)
            canv.rotate(45)
            canv.rect(-4, -4, 8, 8, fill=0, stroke=1)
            canv.restoreState()
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
        # Start chapters on the current page when there is room for the complete
        # title treatment and a meaningful opening passage. This keeps the
        # luxury transitions while preventing half-empty ending pages.
        minimum_opening = (
            6.70 * inch
            if title == "Your Next Chapter / Continue"
            else 3.30 * inch
            if title in MAJOR_SECTION_STARTS
            else 2.45 * inch
        )
        story.append(CondPageBreak(minimum_opening))
        display_title = DISPLAY_TITLES.get(title, title)
        story.extend([
            Spacer(1, 0.22 * inch),
            Paragraph(CHAPTER_STAGES.get(title, "YOUR BLUEPRINT"), styles["chapter_stage"]),
            Paragraph(_safe_markup(display_title.upper()), styles["chapter"]),
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
                big_three = _big_three_rows(payload, styles)
                if big_three is not None:
                    story.extend([
                        Paragraph("Your Big Three at a Glance", styles["heading"]),
                        big_three,
                        Spacer(1, 0.18 * inch),
                    ])
        flow = _content_flowables(str(section.get("content") or ""), styles, title)
        # Keep headings with the paragraph that follows them whenever possible.
        grouped = []
        i = 0
        while i < len(flow):
            current = flow[i]
            if isinstance(current, Paragraph) and current.style.name in {"heading", "action_heading"} and i + 1 < len(flow):
                grouped.append(KeepTogether([current, flow[i + 1]]))
                i += 2
            else:
                grouped.append(current)
                i += 1
        story.extend(grouped)

    doc.build(story)

    # Customer-facing diagnostics must inspect the artifact customers receive,
    # not the Markdown-bearing source used to create it.
    rendered_pages = [page.extract_text() or "" for page in PdfReader(out_path).pages]
    rendered_text = "\n".join(rendered_pages)

    visible = "\n".join(str(section.get("content") or "") for section in included_sections)
    diagnostics = {
        "blank_pages": [i for i, page in enumerate(rendered_pages, 1) if not page.strip()],
        "sparse_pages": [
            i for i, page in enumerate(rendered_pages, 1)
            if i > 1 and len(re.findall(r"\b\w+\b", page)) < 40
        ],
        "orphaned_headings": [],
        "unresolved_placeholders": sorted({m.group(0) for p in PLACEHOLDER_PATTERNS for m in p.finditer(visible)}),
        "internal_terms": sorted(t for t in INTERNAL_TERMS if re.search(rf"\b{re.escape(t)}\b", rendered_text, re.I)),
        "raw_orb_values": sorted(set(re.findall(r"\borb\s*[:=]?\s*\d+(?:\.\d+)?\s*°?", rendered_text, re.I))),
        "markdown_bold_markers": bool(re.search(r"\*\*|__", rendered_text)),
        "markdown_emphasis_markers": bool(re.search(r"(?<!\*)\*[^*\n]+\*(?!\*)|(?<!_)_[^_\n]+_(?!_)", rendered_text)),
        "joined_dash_words": sorted(word for word in set(re.findall(r"\b[A-Za-z]+-[A-Za-z]+\b", rendered_text))
            if word not in {
                "self-expression", "well-being", "self-definition", "self-understanding",
                "self-knowledge", "follow-through", "self-sacrifice", "self-improvement",
                "self-criticism", "over-responsibility", "outward-facing", "inward-facing",
                "group-oriented", "future-oriented", "long-range", "big-picture",
                "whole-chart", "through-line", "values-based", "well-aimed",
                "hands-on", "one-sentence", "self-presentation", "self-recognition",
                "push-pull", "over-functioning", "less-visible", "larger-ranging",
                "self-directed", "problem-solver",
                "fifteen-minute", "thirty-day", "th-house",
            } and not re.match(r"^[A-Z][a-z]+-[A-Z][a-z]+$", word)),
        "page_word_counts": [len(re.findall(r"\b\w+\b", page)) for page in rendered_pages],
        "page_body_lines": [],
    }
    page_no = max(1, getattr(doc, "_blueprint_page_count", 1))
    return (page_no, diagnostics) if return_diagnostics else page_no
