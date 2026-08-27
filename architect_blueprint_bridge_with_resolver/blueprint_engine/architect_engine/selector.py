
from __future__ import annotations
import re
from .xlsx_reader import read_sheet_dicts

CANONICAL_SECTIONS = [
"Personalized Cover","Welcome to Your Blueprint","Birth Chart Snapshot","Your Story Begins Here",
"Your Core Identity — Sun","Your Emotional World — Moon","How the World Meets You — Rising","Your Big Three",
"Your Houses / Life Areas","Your Inner Wiring","Your Relationship Blueprint","Your Career & Purpose Blueprint",
"Your Growth Blueprint","Alignment & Action","Personalized Action Plan","Your First / Next Brick",
"Your Blueprint Summary","Your Next Chapter / Continue"
]

SECTION_ALIASES = {
"Your Core Identity — Sun":["Your Core Identity — Sun","Your Core Identity - Sun","Your Core Identity","Your Sun Sign"],
"Your Emotional World — Moon":["Your Emotional World — Moon","Your Emotional World - Moon","Your Emotional World","Your Moon Sign"],
"How the World Meets You — Rising":["How the World Meets You — Rising","How the World Meets You - Rising","Your Rising Sign"],
"Your Big Three":["Your Big Three"],
"Your Houses / Life Areas":["Your Houses / Life Areas","Your Houses","Houses / Life Areas"],
"Your Inner Wiring":["Your Inner Wiring"],
"Your Relationship Blueprint":["Your Relationship Blueprint","Relationships"],
"Your Career & Purpose Blueprint":["Your Career & Purpose Blueprint","Career & Purpose"],
"Your Growth Blueprint":["Your Growth Blueprint","Growth"],
"Alignment & Action":["Alignment & Action"],
"Personalized Action Plan":["Personalized Action Plan"],
"Your First / Next Brick":["Your First / Next Brick","Your Next Three Bricks","Your First Brick"],
"Your Blueprint Summary":["Your Blueprint Summary","The Final Architect Blueprint"],
"Your Next Chapter / Continue":["Your Next Chapter / Continue","Your Next Chapter"],
"Personalized Cover":["Personalized Cover"],
"Welcome to Your Blueprint":["Welcome to Your Blueprint"],
"Birth Chart Snapshot":["Birth Chart Snapshot"],
"Your Story Begins Here":["Your Story Begins Here"]
}

def _safe_text(v): return str(v or "").strip()
def _norm(v): return re.sub(r"\s+"," ",_safe_text(v)).strip().lower()

def _matches_sign(row, chart, section=None):
    placement=_safe_text(row.get("Placement / Sign"))
    if not placement: return None
    p=_norm(placement)
    signs=[]
    for key in ("sun","moon","mercury","venus","mars","jupiter","saturn"):
        s=chart.get("placements",{}).get(key,{}).get("sign")
        if s: signs.append((key,s.lower()))
    asc=chart.get("angles",{}).get("ascendant",{}).get("sign")
    if asc: signs.append(("rising",asc.lower()))
    for key,sign in signs:
        body_names=("rising","ascendant") if key=="rising" else (key,)
        if any(re.search(rf"\b{re.escape(body)}\b",p) for body in body_names):
            return sign in p
    section_body={
        "Your Core Identity — Sun":"sun",
        "Your Emotional World — Moon":"moon",
        "How the World Meets You — Rising":"rising",
    }.get(section)
    if section_body:
        return any(key==section_body and sign in p for key,sign in signs)
    return any(sign in p for _,sign in signs)

def select_sources(chart: dict, library_path: str, sheet_name: str="DETAILED CONTENT LIBRARY") -> dict:
    rows=read_sheet_dicts(library_path,sheet_name)
    mode=chart["calculation"]["mode"]
    selected=[]; filtered=[]
    for sec in CANONICAL_SECTIONS:
        aliases=[_norm(x) for x in SECTION_ALIASES.get(sec,[sec])]
        candidates=[]
        for r in rows:
            arch=_norm(r.get("V1 Architecture Section"))
            title=_norm(r.get("Title"))
            if not any(a==arch or a==title for a in aliases):
                continue
            if _safe_text(r.get("Audit Status")).upper()!="KEEP":
                filtered.append((sec,r,"audit_status_not_keep")); continue
            action=_safe_text(r.get("Engine Action")).upper()
            cls=_safe_text(r.get("V2 Content Class")).upper()
            placement=_safe_text(r.get("Placement / Sign"))
            source_text=_safe_text(r.get("Corrected Source Text"))
            if mode=="PARTIAL" and sec=="Your Big Three" and re.search(r"\b(?:rising|ascendant)\b",source_text,re.I):
                filtered.append((sec,r,"partial_mode_rising_reference")); continue
            exact=_matches_sign(r,chart,sec)
            if placement and exact is False:
                filtered.append((sec,r,"placement_or_sign_mismatch")); continue
            if mode=="PARTIAL" and sec in ("How the World Meets You — Rising","Your Houses / Life Areas"):
                filtered.append((sec,r,"omitted_by_partial_mode")); continue
            if action=="KEEP_APPROVED":
                score=60
            elif action in ("SYNTHESIZE","KEEP_AND_SYNTHESIZE"):
                score=55
            elif action in ("SELECT_AND_SYNTHESIZE","SELECT_MATCH"):
                if exact:
                    score=170
                else:
                    filtered.append((sec,r,"dynamic_template_without_exact_match")); continue
            else:
                filtered.append((sec,r,"unsafe_or_unsupported_engine_action")); continue
            if exact: score=max(score,170)
            candidates.append((score,r))
        candidates.sort(key=lambda x:(-x[0], int(x[1].get("Master Page") or 9999)))
        # keep enough context but avoid dumping the whole library
        cap = 8 if sec=="Your Houses / Life Areas" else 7 if sec in ("Your Inner Wiring","Your Career & Purpose Blueprint") else 5
        for score,r in candidates[:cap]:
            selected.append({
                "section_name":sec,
                "source_content_id":r.get("Source Content ID"),
                "master_page":r.get("Master Page"),
                "selection_reason":"exact sign/placement" if score>=170 else r.get("Engine Action"),
                "source_priority_score":score,
                "source_text":r.get("Corrected Source Text") or "",
                "title":r.get("Title"),"subtitle":r.get("Subtitle"),
                "trace_status":"SELECTED"
            })
    state={}
    for sec in CANONICAL_SECTIONS:
        count=sum(1 for x in selected if x["section_name"]==sec)
        if mode=="PARTIAL" and sec in ("How the World Meets You — Rising","Your Houses / Life Areas"):
            state[sec]="OMITTED_BY_MODE"
        elif count or (mode=="PARTIAL" and sec=="Your Big Three" and chart.get("availability",{}).get("sun") and chart.get("availability",{}).get("moon")):
            state[sec]="VALID"
        else:
            state[sec]="REVIEW_REQUIRED"
    return {
        "selector_version":"phase3b_runtime_v1",
        "mode":mode,
        "selected_sources":selected,
        "filtered_count":len(filtered),
        "section_states":state,
        "status":"VALID" if all(v in ("VALID","OMITTED_BY_MODE") for v in state.values()) else "REVIEW_REQUIRED"
    }
