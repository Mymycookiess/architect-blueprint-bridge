from __future__ import annotations

import html
import math
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
    Flowable,
    HRFlowable,
    Image,
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
    ("UNDERSTAND", "Your Story Begins Here", "Your Core Identity - Sun", "Your Emotional World - Moon", "How the World Meets You - Rising", "Your Big Three", "Your Houses / Life Areas", "Your Inner Wiring"),
    ("REFLECT", "Your Relationship Blueprint", "Your Career & Purpose Blueprint", "Your Growth Blueprint"),
    ("BUILD", "Alignment & Action", "Personalized Action Plan", "Your Next Brick"),
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
    "strength": "Strengths",
    "strengths": "Strengths",
    "supporting habit": "Supporting Habits",
    "supporting habits": "Supporting Habits",
    "pattern to watch": "Patterns to Watch",
    "patterns to watch": "Patterns to Watch",
    "challenge": "Challenge",
    "encouraging message": "Encouraging Message",
    "next brick": "Next Brick",
}


def _customer_text(text: str) -> str:
    cleaned = html.unescape(str(text or "")).replace("\u00a0", " ").strip()
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned)
    for pattern in INTERNAL_PREFIXES:
        cleaned = re.sub(r"^" + pattern, "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bBottom quote\s*[:—-]\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _heading_key(text: str) -> str:
    cleaned = _customer_text(text)
    cleaned = re.sub(r"^(?:\*\*|__)(.*?)(?:\*\*|__)$", r"\1", cleaned).strip()
    cleaned = re.sub(r"^(?:[-*•]\s+|\d+[.)]?\s+)", "", cleaned).strip()
    return cleaned.rstrip(":").strip().casefold()


def _action_plan_heading(text: str) -> str:
    return ACTION_PLAN_HEADINGS.get(_heading_key(text), "")


def _safe_markup(text: str) -> str:
    """Escape customer text, then convert the supported Markdown emphasis to ReportLab markup."""
    # The AI writer uses typographic dashes as sentence punctuation. Production
    # fonts must not receive a bare replacement hyphen ("clarity-not").
    # Normalize only em/en dashes so legitimate compounds remain untouched.
    text = re.sub(r"\s*[—–]\s*", " - ", _customer_text(text))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(
        r"\bMy focus is\s*_?\s*;\s*the friction I will address is\s*_?\s*;\s*my first action is\s*_?\s*\.",
        "My focus is __________; the friction I will address is __________; my first action is __________.",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bToday, I will\s*_?\s*for\s*_?\s*minutes\.",
        "Today, I will __________ for ______ minutes.",
        text,
        flags=re.I,
    )
    text = html.escape(text, quote=False)
    # Writing prompts intentionally use underscore runs as customer fill-in
    # lines. Preserve those before interpreting Markdown emphasis; otherwise
    # the renderer consumes the lines and leaves broken phrases such as
    # "My focus is ;" or "I will for minutes."
    fill_lines = []

    def preserve_fill_line(match):
        width = max(6, min(18, len(match.group(0))))
        fill_lines.append("<u>" + "_" * width + "</u>")
        return f"@@FILLLINE{len(fill_lines) - 1}TOKEN@@"

    text = re.sub(r"_{2,}", preserve_fill_line, text)
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_([^_\n]+?)_(?!_)", r"<i>\1</i>", text)
    # Remove unmatched emphasis delimiters after valid pairs have become real
    # PDF bold formatting. A bare delimiter has no customer-facing meaning.
    text = text.replace("**", "").replace("__", "").replace("*", "")
    for index, markup in enumerate(fill_lines):
        text = text.replace(f"@@FILLLINE{index}TOKEN@@", markup)
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
        "body": ParagraphStyle("body", fontName="BlueprintSans", fontSize=11.15, leading=17.0, textColor=INK, alignment=TA_LEFT, spaceAfter=10.5, splitLongWords=False, allowWidows=0, allowOrphans=0),
        "closing_body": ParagraphStyle("closing_body", fontName="BlueprintSans", fontSize=10.6, leading=14.4, textColor=INK, alignment=TA_LEFT, spaceAfter=7, splitLongWords=False, allowWidows=0, allowOrphans=0),
        "list": ParagraphStyle("list", parent=None, fontName="BlueprintSans", fontSize=11.0, leading=16.7, leftIndent=17, firstLineIndent=-10, textColor=INK, spaceAfter=8, bulletIndent=5, allowWidows=0, allowOrphans=0),
        "action_heading": ParagraphStyle("action_heading", fontName="BlueprintSans-Bold", fontSize=11.3, leading=14.5, textColor=GOLD, backColor=colors.HexColor("#F1EEE7"), borderColor=RULE, borderWidth=0.45, borderPadding=(6, 8, 6, 8), spaceBefore=10, spaceAfter=7, keepWithNext=True),
        "action_item": ParagraphStyle("action_item", fontName="BlueprintSans", fontSize=10.95, leading=16.4, textColor=INK, alignment=TA_LEFT, spaceAfter=12, splitLongWords=False, allowWidows=0, allowOrphans=0),
        "journey_title": ParagraphStyle("journey_title", fontName="BlueprintSans-Bold", fontSize=22, leading=27, textColor=INK, alignment=TA_CENTER, spaceAfter=10),
        "journey_stage": ParagraphStyle("journey_stage", fontName="BlueprintSans-Bold", fontSize=10.2, leading=13, textColor=GOLD, alignment=TA_CENTER, spaceAfter=2),
        "journey_body": ParagraphStyle("journey_body", fontName="BlueprintSans", fontSize=9.4, leading=13.4, textColor=INK, alignment=TA_CENTER),
        "birth_label": ParagraphStyle("birth_label", fontName="BlueprintSans-Bold", fontSize=9.6, leading=12, textColor=MUTED),
        "birth_value": ParagraphStyle("birth_value", fontName="BlueprintSans", fontSize=10.2, leading=13, textColor=INK),
        "big_three_label": ParagraphStyle("big_three_label", fontName="BlueprintSans-Bold", fontSize=8.8, leading=11, textColor=GOLD, alignment=TA_CENTER, spaceAfter=3),
        "big_three_value": ParagraphStyle("big_three_value", fontName="BlueprintSans-Bold", fontSize=12.2, leading=15, textColor=INK, alignment=TA_CENTER),
        "chart_caption": ParagraphStyle("chart_caption", fontName="BlueprintSans-Bold", fontSize=9.2, leading=12, textColor=INK, alignment=TA_CENTER, spaceAfter=5),
        "placement_head": ParagraphStyle("placement_head", fontName="BlueprintSans-Bold", fontSize=8.2, leading=10, textColor=GOLD),
        "placement_cell": ParagraphStyle("placement_cell", fontName="BlueprintSans", fontSize=8.2, leading=10.2, textColor=INK),
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


_SIGN_SHORT = ("Ar", "Ta", "Ge", "Ca", "Le", "Vi", "Li", "Sc", "Sg", "Cp", "Aq", "Pi")
_PLANET_SHORT = {
    "sun": "Su", "moon": "Mo", "mercury": "Me", "venus": "Ve",
    "mars": "Ma", "jupiter": "Ju", "saturn": "Sa",
}


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _placement_longitude(placement: dict):
    absolute = _number(
        placement.get("absolute_longitude", placement.get("full_degree"))
    )
    if absolute is not None:
        return absolute % 360
    sign = str(placement.get("sign") or "")
    degree = _number(placement.get("degree"))
    signs = ("Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces")
    if sign in signs and degree is not None:
        return (signs.index(sign) * 30 + degree) % 360
    return None


class CompactChartWheel(Flowable):
    """A restrained, data-driven natal wheel for FULL customer Blueprints."""

    def __init__(self, chart_details: dict, width=2.75 * inch, height=2.75 * inch):
        super().__init__()
        self.chart_details = chart_details
        self.width = width
        self.height = height

    def draw(self):
        canv = self.canv
        cx, cy = self.width / 2, self.height / 2
        radius = min(self.width, self.height) / 2 - 10
        angles = self.chart_details.get("angles") or {}
        asc = _number((angles.get("ascendant") or {}).get("absolute_longitude"))
        asc = 0.0 if asc is None else asc % 360

        def point(longitude, distance):
            theta = math.radians(180 - ((longitude - asc) % 360))
            return cx + distance * math.cos(theta), cy + distance * math.sin(theta)

        canv.saveState()
        canv.setStrokeColor(RULE)
        canv.setLineWidth(0.55)
        canv.circle(cx, cy, radius, stroke=1, fill=0)
        canv.circle(cx, cy, radius * 0.78, stroke=1, fill=0)
        canv.circle(cx, cy, radius * 0.48, stroke=1, fill=0)

        # Zodiac ring, rotated so the Ascendant is the left-hand horizon.
        canv.setFont("BlueprintSans-Bold", 6.6)
        canv.setFillColor(MUTED)
        for index, label in enumerate(_SIGN_SHORT):
            boundary = index * 30
            x1, y1 = point(boundary, radius * 0.78)
            x2, y2 = point(boundary, radius)
            canv.line(x1, y1, x2, y2)
            tx, ty = point(boundary + 15, radius * 0.89)
            canv.drawCentredString(tx, ty - 2.2, label)

        # House cusps and numbers are drawn only from validated FULL data.
        houses = sorted(
            [h for h in (self.chart_details.get("houses") or []) if _number(h.get("cusp_absolute_longitude")) is not None],
            key=lambda item: int(item.get("house") or 0),
        )
        canv.setFont("BlueprintSans", 6.4)
        canv.setFillColor(MUTED)
        for house in houses:
            longitude = float(house["cusp_absolute_longitude"]) % 360
            x1, y1 = point(longitude, radius * 0.48)
            x2, y2 = point(longitude, radius * 0.78)
            canv.line(x1, y1, x2, y2)
        if len(houses) == 12:
            for index, house in enumerate(houses):
                start = float(house["cusp_absolute_longitude"]) % 360
                end = float(houses[(index + 1) % 12]["cusp_absolute_longitude"]) % 360
                midpoint = (start + ((end - start) % 360) / 2) % 360
                tx, ty = point(midpoint, radius * 0.58)
                canv.drawCentredString(tx, ty - 2, str(house["house"]))

        placements = self.chart_details.get("placements") or {}
        plotted = []
        for key in _PLANET_SHORT:
            placement = placements.get(key) or {}
            longitude = _placement_longitude(placement)
            if longitude is not None:
                plotted.append((longitude, key))
        plotted.sort()
        cluster_index = 0
        previous = None
        for longitude, key in plotted:
            if previous is None or min((longitude - previous) % 360, (previous - longitude) % 360) >= 10:
                cluster_index = 0
            else:
                cluster_index += 1
            marker_radius = radius * (0.70 - 0.10 * (cluster_index % 3))
            tx, ty = point(longitude, marker_radius)
            canv.setFillColor(BG)
            canv.setStrokeColor(GOLD)
            canv.circle(tx, ty, 7.1, stroke=1, fill=1)
            canv.setFillColor(INK)
            canv.setFont("BlueprintSans-Bold", 5.7)
            canv.drawCentredString(tx, ty - 2, _PLANET_SHORT[key])
            previous = longitude

        # The horizon makes the wheel immediately legible without adding a
        # dense astrology lesson to the customer experience.
        left_x, left_y = point(asc, radius)
        right_x, right_y = point((asc + 180) % 360, radius)
        canv.setStrokeColor(GOLD)
        canv.setLineWidth(1.15)
        canv.line(left_x, left_y, right_x, right_y)
        canv.setFillColor(GOLD)
        canv.setFont("BlueprintSans-Bold", 6.4)
        canv.drawString(max(0, left_x - 1), left_y + 4, "ASC")
        canv.restoreState()


def _placement_snapshot(payload: dict, styles: dict):
    details = payload.get("chart_details") or {}
    placements = details.get("placements") or {}
    rows = [[
        Paragraph("BODY", styles["placement_head"]),
        Paragraph("SIGN / DEGREE", styles["placement_head"]),
        Paragraph("HOUSE", styles["placement_head"]),
    ]]
    for key in _PLANET_SHORT:
        placement = placements.get(key) or {}
        sign = str(placement.get("sign") or "").strip()
        if not sign:
            continue
        degree = _number(placement.get("degree", placement.get("norm_degree")))
        degree_text = f"{degree:.0f}°" if degree is not None and abs(degree - round(degree)) < 0.05 else (f"{degree:.1f}°" if degree is not None else "")
        retrograde = " R" if placement.get("retrograde") else ""
        house = placement.get("house")
        rows.append([
            Paragraph(str(placement.get("name") or key.title()), styles["placement_cell"]),
            Paragraph(_safe_markup(f"{sign} {degree_text}{retrograde}".strip()), styles["placement_cell"]),
            Paragraph(str(house) if house else "-", styles["placement_cell"]),
        ])
    if len(rows) == 1:
        return None
    table = Table(rows, colWidths=[0.90 * inch, 1.38 * inch, 0.45 * inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.45, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, RULE),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1EEE7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))
    return table


def _chart_snapshot(payload: dict, styles: dict):
    snapshot_image = str(payload.get("chart_snapshot_image") or "").strip()
    if snapshot_image and os.path.isfile(snapshot_image):
        width = BODY_WIDTH
        height = width * 900 / 2180
        return [Image(snapshot_image, width=width, height=height)]
    details = payload.get("chart_details") or {}
    table = _placement_snapshot(payload, styles)
    if table is None:
        return []
    availability = details.get("availability") or {}
    if payload.get("mode") == "FULL" and availability.get("houses") and availability.get("rising"):
        wheel = CompactChartWheel(details)
        panel = Table(
            [[wheel, table]],
            colWidths=[3.0 * inch, BODY_WIDTH - 3.0 * inch],
            hAlign="LEFT",
        )
        panel.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 10),
            ("LEFTPADDING", (1, 0), (1, 0), 0),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return [Paragraph("Your Compact Chart Wheel & Placements", styles["heading"]), panel]
    return [Paragraph("Your Planetary Placements", styles["heading"]), table]


def _content_flowables(content: str, styles: dict, section_title: str = ""):
    flow = []
    source_lines = (content or "").splitlines()
    while source_lines and not source_lines[0].strip():
        source_lines.pop(0)
    duplicate_titles = {section_title, DISPLAY_TITLES.get(section_title, "")}
    duplicate_title_keys = {_heading_key(title) for title in duplicate_titles if title}
    while source_lines and _heading_key(source_lines[0]) in duplicate_title_keys:
        source_lines.pop(0)
        while source_lines and not source_lines[0].strip():
            source_lines.pop(0)
    content = "\n".join(source_lines)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", content or "") if b.strip()]
    previous_plain = None
    for block in blocks:
        lines = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # The AI can occasionally repeat the same worksheet template line.
            # Keep one customer prompt, never two identical adjacent copies.
            plain_line = _customer_text(line)
            comparison_line = re.sub(r"_+", "", plain_line)
            if comparison_line == previous_plain and re.search(r"\bToday, I will\b", comparison_line, re.I):
                continue
            lines.append(line)
            previous_plain = comparison_line
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
            action_heading = _action_plan_heading(plain) if section_title == "Personalized Action Plan" else ""
            if action_heading:
                flush_body()
                flow.append(Paragraph(_safe_markup(action_heading), styles["action_heading"]))
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


def _balanced_summary_flow(flow):
    """Split long summaries near their word midpoint instead of leaving a short spill page."""
    weighted = []
    total = 0
    for index, item in enumerate(flow):
        if isinstance(item, Paragraph):
            words = len(re.findall(r"\b\w+\b", item.getPlainText()))
            if words:
                weighted.append((index, words))
                total += words
    if total <= 475 or len(weighted) < 4:
        return flow
    # A summary page comfortably holds about 380 words at Blueprint body size.
    # Choose the smallest page count that can hold the content, then place each
    # break at the paragraph boundary nearest its ideal cumulative midpoint.
    page_count = max(2, math.ceil(total / 380))
    targets = [total * n / page_count for n in range(1, page_count)]
    breaks = []
    running = 0
    candidate_positions = []
    for index, words in weighted[:-1]:
        running += words
        candidate_positions.append((index, running))
    previous_index = -1
    for target in targets:
        choices = [(index, cumulative) for index, cumulative in candidate_positions if index > previous_index]
        if not choices:
            break
        split_after, _ = min(choices, key=lambda pair: abs(pair[1] - target))
        breaks.append(split_after)
        previous_index = split_after
    if not breaks:
        return flow
    output = []
    break_set = set(breaks)
    for index, item in enumerate(flow):
        output.append(item)
        if index in break_set:
            output.append(PageBreak())
    return output


def _balanced_chapter_flow(flow, *, threshold=470, capacity=460):
    """Balance multi-page chapters at paragraph boundaries for premium pacing."""
    weighted = []
    total = 0
    for index, item in enumerate(flow):
        if isinstance(item, Paragraph):
            words = len(re.findall(r"\b\w+\b", item.getPlainText()))
            if words:
                weighted.append((index, words))
                total += words
    if total <= threshold or len(weighted) < 4:
        return flow
    page_count = max(2, math.ceil(total / capacity))
    targets = [total * n / page_count for n in range(1, page_count)]
    candidate_positions = []
    running = 0
    for index, words in weighted[:-1]:
        running += words
        item = flow[index]
        if item.style.name not in {"heading", "action_heading"}:
            candidate_positions.append((index, running))
    breaks = []
    previous_index = -1
    for target in targets:
        choices = [(index, cumulative) for index, cumulative in candidate_positions if index > previous_index]
        if not choices:
            break
        split_after, _ = min(choices, key=lambda pair: abs(pair[1] - target))
        breaks.append(split_after)
        previous_index = split_after
    output = []
    break_set = set(breaks)
    for index, item in enumerate(flow):
        output.append(item)
        if index in break_set:
            output.append(PageBreak())
    return output


def _normalized_page_marker(value):
    """Normalize extracted PDF text so chapter headings can be matched safely."""
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _sparse_page_diagnostics(rendered_pages, chapter_titles):
    """Separate intentional chapter thresholds from accidental short spill pages.

    Chapters deliberately start on fresh pages. A short chapter-opening page is
    therefore valid when its title is visible and it contains meaningful copy.
    Blank pages and sparse continuation pages remain blocking QA failures.
    """
    chapter_markers = {
        _normalized_page_marker(title)
        for title in chapter_titles
        if _normalized_page_marker(title)
    }
    intentional = []
    accidental = []
    for page_number, page in enumerate(rendered_pages, 1):
        word_count = len(re.findall(r"\b\w+\b", page))
        if page_number == 1 or word_count >= 40:
            continue
        opening_text = _normalized_page_marker("\n".join(page.splitlines()[:14]))
        is_chapter_opening = (
            word_count >= 12
            and any(marker in opening_text for marker in chapter_markers)
        )
        if is_chapter_opening:
            intentional.append(page_number)
        else:
            accidental.append(page_number)
    return accidental, intentional


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
    rendered_chapters = 0
    for section in included_sections:
        title = str(section.get("title") or "").strip()
        if title.upper() in ("THE ARCHITECT BLUEPRINT", "PERSONALIZED COVER"):
            continue
        # Every customer chapter receives a clean architectural threshold.
        # Starting chapters mid-page made the document read like a continuous
        # export rather than a premium, intentionally designed book.
        if rendered_chapters > 0:
            story.append(PageBreak())
        rendered_chapters += 1
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
                chart_snapshot = _chart_snapshot(payload, styles)
                if chart_snapshot:
                    story.extend(chart_snapshot)
        flow = _content_flowables(str(section.get("content") or ""), styles, title)
        if title == "Your Blueprint Summary":
            flow = _balanced_summary_flow(flow)
        elif title == "Your First / Next Brick":
            flow = _balanced_chapter_flow(flow, threshold=330, capacity=330)
        elif title not in {"Birth Chart Snapshot", "Personalized Action Plan", "Your Next Chapter / Continue"}:
            flow = _balanced_chapter_flow(flow)
        # Keep headings with the paragraph that follows them whenever possible.
        grouped = []
        i = 0
        while i < len(flow):
            current = flow[i]
            if isinstance(current, Paragraph) and current.style.name in {"heading", "action_heading"} and i + 1 < len(flow):
                grouped.append(KeepTogether([current, flow[i + 1]]))
                i += 2
            elif title == "Birth Chart Snapshot" and isinstance(current, Paragraph):
                grouped.append(KeepTogether([current]))
                i += 1
            else:
                grouped.append(current)
                i += 1
        story.extend(grouped)

    doc.build(story)

    # Customer-facing diagnostics must inspect the artifact customers receive,
    # not the Markdown-bearing source used to create it.
    rendered_pages = [page.extract_text() or "" for page in PdfReader(out_path).pages]
    rendered_text = "\n".join(rendered_pages)
    chapter_titles = [
        DISPLAY_TITLES.get(str(section.get("title") or "").strip(), str(section.get("title") or "").strip())
        for section in included_sections
        if str(section.get("title") or "").strip().upper() not in ("THE ARCHITECT BLUEPRINT", "PERSONALIZED COVER")
    ]
    sparse_pages, intentional_sparse_pages = _sparse_page_diagnostics(
        rendered_pages, chapter_titles
    )
    summary_page_counts = []
    summary_started = False
    for page in rendered_pages:
        if "YOUR BLUEPRINT SUMMARY" in page:
            summary_started = True
        if summary_started and "CONTINUE BUILDING" not in page:
            summary_page_counts.append(len(re.findall(r"\b\w+\b", page)))
        if summary_started and "CONTINUE BUILDING" in page:
            break
    unbalanced_summary_pages = []
    if len(summary_page_counts) > 1 and min(summary_page_counts) < max(summary_page_counts) * 0.55:
        unbalanced_summary_pages = summary_page_counts

    visible = "\n".join(str(section.get("content") or "") for section in included_sections)
    diagnostics = {
        "blank_pages": [i for i, page in enumerate(rendered_pages, 1) if not page.strip()],
        "sparse_pages": sparse_pages,
        "intentional_sparse_pages": intentional_sparse_pages,
        "orphaned_headings": [],
        "unresolved_placeholders": sorted({m.group(0) for p in PLACEHOLDER_PATTERNS for m in p.finditer(visible)}),
        "internal_terms": sorted(t for t in INTERNAL_TERMS if re.search(rf"\b{re.escape(t)}\b", rendered_text, re.I)),
        "raw_orb_values": sorted(set(re.findall(r"\borb\s*[:=]?\s*\d+(?:\.\d+)?\s*°?", rendered_text, re.I))),
        # Runs of underscores are intentional worksheet lines, not Markdown
        # markers. Only flag a double underscore with non-underscore neighbors.
        "markdown_bold_markers": bool(re.search(r"\*\*|(?<!_)__(?!_)", rendered_text)),
        "markdown_emphasis_markers": bool(re.search(r"(?<!\*)\*[^*\n]+\*(?!\*)|(?<!_)_[^_\n]+_(?!_)", rendered_text)),
        "broken_fill_in_prompts": sorted(set(
            match.group(0) for pattern in (
                r"My focus is\s*;\s*the friction I will address is\s*;\s*my first action is\s*_?\s*\.",
                r"Today, I will\s+for\s+minutes\.",
            ) for match in re.finditer(pattern, rendered_text, re.I)
        )),
        "duplicate_action_prompts": len(re.findall(r"Today, I will\s+_+\s+for\s+_+\s+minutes\.", rendered_text, re.I)) > 1,
        "unbalanced_summary_pages": unbalanced_summary_pages,
        "chart_snapshot_missing": bool(
            payload.get("mode") == "FULL"
            and (payload.get("chart_details") or {}).get("availability", {}).get("houses")
            and not str(payload.get("chart_snapshot_image") or "").strip()
            and "Your Compact Chart Wheel & Placements" not in rendered_text
        ),
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
