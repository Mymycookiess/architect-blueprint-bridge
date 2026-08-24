
from __future__ import annotations
import re

SECTION_ORDER = [
"Personalized Cover","Welcome to Your Blueprint","Birth Chart Snapshot","Your Story Begins Here",
"Your Core Identity — Sun","Your Emotional World — Moon","How the World Meets You — Rising","Your Big Three",
"Your Houses / Life Areas","Your Inner Wiring","Your Relationship Blueprint","Your Career & Purpose Blueprint",
"Your Growth Blueprint","Alignment & Action","Personalized Action Plan","Your First / Next Brick",
"Your Blueprint Summary","Your Next Chapter / Continue"
]

def _clean_source(text):
    text=(text or "").replace("CUSTOMER NAME","")
    # Strip common internal brackets/instructions defensively.
    text=re.sub(r"\[[^\]]+\]","",text)
    lines=[ln.strip() for ln in text.splitlines()]
    return "\n".join([ln for ln in lines if ln and "website will automatically" not in ln.lower()])

def _fact_notes(context, section):
    f=context["chart_facts"]; p=f.get("placements",{}); notes=[]
    if section=="Birth Chart Snapshot":
        for k in ("sun","moon","mercury","venus","mars","jupiter","saturn"):
            x=p.get(k,{})
            if x.get("sign"):
                h=f" • House {x.get('house')}" if x.get("house") else ""
                notes.append(f"{k.title()}: {x['sign']}{h}")
        asc=f.get("angles",{}).get("ascendant",{})
        if asc.get("sign"): notes.append(f"Rising: {asc['sign']}")
    elif section=="Your Core Identity — Sun":
        x=p.get("sun",{})
        if x: notes.append(f"Verified chart note: Sun in {x.get('sign')} — House {x.get('house')}.")
    elif section=="Your Emotional World — Moon":
        x=p.get("moon",{})
        if x: notes.append(f"Verified chart note: Moon in {x.get('sign')} — House {x.get('house')}.")
    elif section=="How the World Meets You — Rising":
        x=f.get("angles",{}).get("ascendant",{})
        if x.get("sign"): notes.append(f"Verified chart note: {x.get('sign')} Rising.")
    elif section=="Your Inner Wiring":
        for k in ("mercury","venus","mars","jupiter","saturn"):
            x=p.get(k,{})
            if x.get("sign"): notes.append(f"{k.title()}: {x.get('sign')} — House {x.get('house')}.")
    elif section=="Your Career & Purpose Blueprint":
        mc=f.get("angles",{}).get("midheaven",{})
        if mc.get("sign"): notes.append(f"Verified chart note: 10th-house / Midheaven sign {mc.get('sign')}.")
    return notes

def compose_report(context: dict, report_id: str) -> dict:
    sections=[]
    for sec in SECTION_ORDER:
        cfg=context["sections"].get(sec,{"status":"REVIEW_REQUIRED","source_blocks":[]})
        if cfg["status"]=="OMITTED_BY_MODE":
            sections.append({"section_id":sec.lower().replace(" ","_"),"title":sec,"status":"OMITTED_BY_MODE","content":"","evidence_refs":[]})
            continue
        blocks=cfg.get("source_blocks",[])
        body=[]
        for b in blocks:
            cleaned=_clean_source(b.get("source_text",""))
            if cleaned and cleaned not in body:
                body.append(cleaned)
        notes=_fact_notes(context,sec)
        content="\n\n".join(body + notes)
        sections.append({
            "section_id":sec.lower().replace(" ","_").replace("/","_"),
            "title":sec,
            "status":"INCLUDED" if content else "REVIEW_REQUIRED",
            "content":content,
            "evidence_refs":[b["source_content_id"] for b in blocks]
        })
    return {
        "report_id":report_id,
        "schema_version":"blueprint_report_v1",
        "context_version":context["context_version"],
        "mode":context["mode"],
        "customer":context["customer"],
        "sections":sections,
        "qa":{"source_boundary":"LOCKED_TO_CONTEXT","new_astrology_added":False}
    }
