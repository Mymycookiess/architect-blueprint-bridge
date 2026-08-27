from __future__ import annotations

import html
import re
from dataclasses import dataclass

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

BG = HexColor("#FAF9F6")
INK = HexColor("#141414")
MUTED = HexColor("#555555")
RULE = HexColor("#D0CCC4")
LEFT = 64
RIGHT = 64
BODY_WIDTH = letter[0] - LEFT - RIGHT
BODY_TOP = 636
BODY_BOTTOM = 58

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


@dataclass
class Element:
    kind: str
    text: str


def _wrap(text, font, size, width):
    words = text.split()
    lines = []
    line = ""
    for word in words:
        trial = (line + " " + word).strip()
        if stringWidth(trial, font, size) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _customer_text(text):
    """Remove production labels while retaining every chart statement that follows."""
    cleaned = html.unescape(text).replace("\u00a0", " ").strip()
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned)
    cleaned = re.sub(r"^\s*[-*]\s+", "• ", cleaned)
    for pattern in INTERNAL_PREFIXES:
        cleaned = re.sub(r"^" + pattern, "", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_heading(line):
    alpha = re.sub(r"[^A-Za-z]", "", line)
    return bool(alpha) and len(line) <= 88 and len(line.split()) <= 13 and line.upper() == line


def _is_list_item(line):
    return bool(re.match(r"^(?:•|\d+[.)]|[A-Z][.)])\s+", line))


def _elements(content):
    elements = []
    for block in (x.strip() for x in content.split("\n\n") if x.strip()):
        lines = []
        for raw_line in block.splitlines():
            clean = _customer_text(raw_line)
            if clean:
                lines.append(clean)
        body = []

        def flush():
            if body:
                elements.append(Element("body", " ".join(body)))
                body.clear()

        for line in lines:
            if _is_heading(line):
                flush()
                elements.append(Element("heading", line))
            elif _is_list_item(line):
                flush()
                elements.append(Element("list", line))
            else:
                body.append(line)
        flush()
    return elements


def _style(element):
    if element.kind == "heading":
        return "Times-Bold", 11.0, 15.2, 9, 5
    if element.kind == "list":
        return "Times-Roman", 10.4, 14.2, 2, 4
    return "Times-Roman", 10.7, 15.8, 0, 9.5


def render_pdf(payload: dict, out_path: str, return_diagnostics=False):
    width, height = letter
    pdf = canvas.Canvas(out_path, pagesize=letter)
    pdf.setTitle("The Architect Blueprint")
    page_no = 0
    page_stats = []
    visible_text = []
    orphaned_headings = []

    def start_page(section_title, continued=False):
        nonlocal page_no
        page_no += 1
        pdf.setFillColor(BG)
        pdf.rect(0, 0, width, height, fill=1, stroke=0)
        title = section_title.upper() + (" — CONTINUED" if continued else "")
        title_size = 17.5 if continued else 20
        title_lines = _wrap(title, "Times-Bold", title_size, width - 88)
        title_y = 706
        pdf.setFillColor(INK)
        pdf.setFont("Times-Bold", title_size)
        for line in title_lines[:2]:
            pdf.drawCentredString(width / 2, title_y, line)
            title_y -= title_size + 2
        rule_y = title_y - 5
        pdf.setStrokeColor(RULE)
        pdf.line(width / 2 - 58, rule_y, width / 2 + 58, rule_y)
        page_stats.append({"page": page_no, "body_lines": 0, "section": section_title})
        visible_text.append(title)
        return min(BODY_TOP, rule_y - 27)

    def finish_page(section_title=None, y=None):
        if section_title in ("Alignment & Action", "Personalized Action Plan", "Your First / Next Brick") and y and y > 180:
            note_y=y-9
            pdf.setFont("Times-Bold",8.5)
            pdf.setFillColor(MUTED)
            pdf.drawString(LEFT,note_y,"NOTES")
            pdf.setStrokeColor(RULE)
            for _ in range(min(7,max(2,int((note_y-BODY_BOTTOM-15)//27)))):
                note_y-=27
                pdf.line(LEFT,note_y,width-RIGHT,note_y)
        elif (section_title=="Birth Chart Snapshot" or
              (section_title=="Your Big Three" and page_stats[-1]["body_lines"]<20)) and y:
            pdf.setStrokeColor(RULE)
            box_bottom=max(BODY_BOTTOM+26,y-14)
            pdf.roundRect(LEFT-10,box_bottom,BODY_WIDTH+20,BODY_TOP-box_bottom+12,6,fill=0,stroke=1)
        elif y and page_stats[-1]["body_lines"]<16 and y>BODY_BOTTOM+55:
            pdf.setStrokeColor(RULE)
            pdf.line(LEFT,y-14,LEFT+72,y-14)
        pdf.setFont("Times-Roman", 7.2)
        pdf.setFillColor(MUTED)
        pdf.drawString(38, 26, "THE ARCHITECT BLUEPRINT")
        pdf.drawRightString(width - 38, 26, str(page_no))
        pdf.showPage()

    for section in payload["sections"]:
        if section["status"] == "OMITTED_BY_MODE":
            continue
        elements = _elements(section.get("content", ""))
        if not elements:
            continue
        y = start_page(section["title"])
        index = 0
        keep_next_pending = False
        pending_heading = None
        while index < len(elements):
            element = elements[index]
            font, size, leading, before, after = _style(element)
            body_width = BODY_WIDTH - (14 if element.kind == "list" else 0)
            lines = _wrap(element.text, font, size, body_width)
            if not lines:
                index += 1
                continue
            capacity = int((y - BODY_BOTTOM) // leading)
            future_lines = 0
            for future in elements[index:]:
                ff, fs, fl, fb, fa = _style(future)
                fw = BODY_WIDTH - (14 if future.kind == "list" else 0)
                future_lines += len(_wrap(future.text, ff, fs, fw)) + int((fb + fa) / fl)
            small_tail = future_lines - capacity
            if 0 < small_tail < 9 and page_stats[-1]["body_lines"] >= 8 and not keep_next_pending:
                finish_page(section["title"],y)
                y = start_page(section["title"], True)
                continue
            if element.kind == "heading" and index + 1 < len(elements):
                next_el = elements[index + 1]
                nf, ns, nl, nb, _ = _style(next_el)
                next_lines = _wrap(next_el.text, nf, ns, BODY_WIDTH)
                required = before + len(lines) * leading + after + nb + min(2, len(next_lines)) * nl
                if y - required < BODY_BOTTOM:
                    finish_page(section["title"],y)
                    y = start_page(section["title"], True)

            y -= before
            remaining = lines[:]
            while remaining:
                capacity = int((y - BODY_BOTTOM) // leading)
                if capacity < 2 and len(remaining) > 1:
                    finish_page(section["title"],y)
                    y = start_page(section["title"], True)
                    capacity = int((y - BODY_BOTTOM) // leading)
                take = min(capacity, len(remaining))
                remainder = len(remaining) - take
                if 0 < remainder < 8 and take > 8:
                    take -= 8 - remainder
                if len(remaining) - take == 1 and take > 2:
                    take -= 1
                if take <= 0:
                    finish_page(section["title"],y)
                    y = start_page(section["title"], True)
                    continue
                pdf.setFont(font, size)
                pdf.setFillColor(INK)
                x = LEFT + (14 if element.kind == "list" else 0)
                if element.kind != "heading" and pending_heading:
                    heading_text, heading_page = pending_heading
                    if heading_page != page_no:
                        orphaned_headings.append(heading_text)
                    pending_heading = None
                for line in remaining[:take]:
                    pdf.drawString(x, y, line)
                    y -= leading
                    page_stats[-1]["body_lines"] += 1
                visible_text.extend(remaining[:take])
                remaining = remaining[take:]
                if remaining:
                    finish_page(section["title"],y)
                    y = start_page(section["title"], True)
            y -= after
            keep_next_pending = element.kind == "heading"
            if element.kind == "heading":
                pending_heading = (element.text, page_no)
            index += 1
        finish_page(section["title"],y)

    pdf.save()
    text = "\n".join(visible_text)
    diagnostics = {
        "blank_pages": [p["page"] for p in page_stats if p["body_lines"] == 0],
        "orphaned_headings": orphaned_headings,
        "unresolved_placeholders": sorted({m.group(0) for p in PLACEHOLDER_PATTERNS for m in p.finditer(text)}),
        "internal_terms": sorted(t for t in INTERNAL_TERMS if re.search(rf"\b{re.escape(t)}\b", text, re.I)),
        "raw_orb_values": sorted(set(re.findall(r"\borb\s*[:=]?\s*\d+(?:\.\d+)?\s*°?",text,re.I))),
        "page_body_lines": [p["body_lines"] for p in page_stats],
    }
    return (page_no, diagnostics) if return_diagnostics else page_no
