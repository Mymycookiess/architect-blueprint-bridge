from __future__ import annotations
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth

BG=HexColor("#FAF9F6"); INK=HexColor("#141414"); MUTED=HexColor("#555555")

def _wrap(text,font,size,width):
    words=text.split(); lines=[]; line=""
    for w in words:
        t=(line+" "+w).strip()
        if stringWidth(t,font,size)<=width:
            line=t
        else:
            if line: lines.append(line)
            line=w
    if line: lines.append(line)
    return lines

def render_pdf(payload: dict, out_path: str):
    W,H=letter
    c=canvas.Canvas(out_path,pagesize=letter)
    c.setTitle("The Architect Blueprint")
    page_no=0

    def start_page(section_title, continued=False):
        nonlocal page_no
        page_no+=1
        c.setFillColor(BG); c.rect(0,0,W,H,fill=1,stroke=0)
        c.setFillColor(INK); c.setFont("Times-Bold",22)
        title=section_title.upper() + (" — CONTINUED" if continued else "")
        c.drawCentredString(W/2,700,title)
        c.setStrokeColor(HexColor("#D0CCC4")); c.line(245,672,367,672)
        return 635

    def finish_page():
        c.setFont("Times-Roman",7.2); c.setFillColor(MUTED)
        c.drawString(38,26,"THE ARCHITECT BLUEPRINT")
        c.drawRightString(W-38,26,str(page_no))
        c.showPage()

    for sec in payload["sections"]:
        if sec["status"]=="OMITTED_BY_MODE":
            continue
        chunks=[x.strip() for x in sec.get("content","").split("\n\n") if x.strip()]
        if not chunks:
            continue
        y=start_page(sec["title"],False)
        first=True
        for para in chunks:
            is_heading=len(para)<80 and para.upper()==para and len(para.split())<12
            font="Times-Bold" if is_heading else "Times-Roman"
            size=12.2 if is_heading else 11.35
            leading=17.0 if is_heading else 16.0
            lines=_wrap(para,font,size,500)
            needed=len(lines)*leading+10
            if y-needed<62:
                finish_page()
                y=start_page(sec["title"],True)
            c.setFont(font,size); c.setFillColor(INK)
            for ln in lines:
                c.drawCentredString(W/2,y,ln); y-=leading
            y-=10
        finish_page()
    c.save()
    return page_no
