
from __future__ import annotations
import re
from .synthesis import render_synthesis_notes
from .confidence_rules import strengthen_supported_language
from .emotional_rules import render_emotional_note
from .repetition_rules import source_block_owner

SECTION_ORDER = [
"Personalized Cover","Welcome to Your Blueprint","Birth Chart Snapshot","Your Story Begins Here",
"Your Core Identity — Sun","Your Emotional World — Moon","How the World Meets You — Rising","Your Big Three",
"Your Houses / Life Areas","Your Inner Wiring","Your Relationship Blueprint","Your Career & Purpose Blueprint",
"Your Growth Blueprint","Alignment & Action","Personalized Action Plan","Your First / Next Brick",
"Your Blueprint Summary","Your Next Chapter / Continue"
]

def _customer_name(context):
    customer=context.get("customer") or ""
    if isinstance(customer,dict):
        customer=customer.get("name") or ""
    return str(customer).strip()


def _clean_source(text, customer=""):
    text = (text or "").replace("@CUSTOMER NAME@", customer)
    text = re.sub(r"\bCUSTOMER NAME\b", customer, text, flags=re.I)
    # Strip common internal brackets/instructions defensively.
    text=re.sub(r"\[[^\]]+\]","",text)
    lines=[ln.strip() for ln in text.splitlines()]
    return strengthen_supported_language("\n".join([ln for ln in lines if ln and "website will automatically" not in ln.lower()]))


def _proofread_customer_text(text, section_title=""):
    """Apply narrow V1 copy fixes without changing report meaning or structure."""
    replacements = {
        "themes appears": "themes appear",
        "Others offers": "Others offer",
        "these five areas helps": "these five areas help",
        "goals that allows": "goals that allow",
        "reveals what need development": "reveals what needs development",
    }
    for source, replacement in replacements.items():
        pattern = re.escape(source).replace(r"\ ", r"\s+")
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)

    # The renderer already supplies the chapter title. Remove only an identical
    # source-library heading at the start, never a distinct subtitle.
    lines = text.splitlines()
    while lines and section_title and lines[0].strip().casefold() == section_title.strip().casefold():
        lines = lines[1:]

    # Remove only immediately repeated all-caps headings; preserve repeated prose.
    cleaned = []
    for line in lines:
        if (
            cleaned
            and line.strip()
            and line.strip() == line.strip().upper()
            and line.strip().casefold() == cleaned[-1].strip().casefold()
        ):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()

def _fact_notes(context, section):
    f = context["chart_facts"]
    p = f.get("placements", {})
    notes = []

    def placement_note(label, key):
        x = p.get(key, {})
        if not x or not x.get("sign"):
            return None

        house = f" — House {x.get('house')}" if x.get("house") else ""
        return f"{label}: {x.get('sign')}{house}."

    def rising_note():
        asc = f.get("angles", {}).get("ascendant", {})
        if asc.get("sign"):
            return f"Rising: {asc.get('sign')}."
        return None

    def aspect_notes(body_names=None, limit=3, application="this chapter"):
        results = []

        for aspect in f.get("aspects", []) or []:
            body1 = (
                aspect.get("body_a")
                or aspect.get("body1")
                or aspect.get("planet1")
                or aspect.get("first")
                or ""
            )
            body2 = (
                aspect.get("body_b")
                or aspect.get("body2")
                or aspect.get("planet2")
                or aspect.get("second")
                or ""
            )
            aspect_type = (
                aspect.get("type")
                or aspect.get("aspect")
                or aspect.get("name")
                or ""
            )
            if not body1 or not body2 or not aspect_type:
                continue

            if body_names:
                wanted = {x.lower() for x in body_names}
                if body1.lower() not in wanted and body2.lower() not in wanted:
                    continue

            results.append(
                f"The {aspect_type.lower()} between {body1} and {body2} adds another layer to {application}."
            )

            if len(results) >= limit:
                break

        return results

    if section == "Welcome to Your Blueprint":
        if context.get("mode")=="PARTIAL":
            notes.append("Chart scope: Because birth time is unknown, this Blueprint uses only stable validated planets and aspects; Rising and houses are intentionally omitted.")
        else:
            notes.append("This Blueprint describes the patterns in your chart rather than fixed predictions.")

    elif section == "Birth Chart Snapshot":
        for key in (
            "sun",
            "moon",
            "mercury",
            "venus",
            "mars",
            "jupiter",
            "saturn",
        ):
            note = placement_note(key.title(), key)
            if note:
                notes.append(note)

        note = rising_note()
        if note:
            notes.append(note)

    elif section == "Your Core Identity — Sun":
        note = placement_note("Your Sun", "sun")
        if note:
            notes.append(note)

        notes.extend(aspect_notes(["sun"], limit=2, application="core identity"))

    elif section == "Your Emotional World — Moon":
        note = placement_note("Your Moon", "moon")
        if note:
            notes.append(note)

        notes.extend(aspect_notes(["moon"], limit=2, application="emotional processing"))

    elif section == "How the World Meets You — Rising":
        asc = f.get("angles", {}).get("ascendant", {})
        if asc.get("sign"):
            notes.append(
                f"Your {asc.get('sign')} Rising shapes how you first meet the world."
            )

    elif section == "Your Big Three":
        sun = p.get("sun", {}).get("sign")
        moon = p.get("moon", {}).get("sign")
        rising = f.get("angles", {}).get("ascendant", {}).get("sign")
        if sun and moon and rising:
            notes.append(f"Your Big Three are {sun} Sun, {moon} Moon, and {rising} Rising.")

    elif section == "Your Inner Wiring":
        for key in ("mercury", "venus", "mars", "jupiter", "saturn"):
            note = placement_note(key.title(), key)
            if note:
                notes.append(note)

    elif section == "Your Relationship Blueprint":
        pass
    elif section == "Your Career & Purpose Blueprint":
        mc = f.get("angles", {}).get("midheaven", {})
        if mc.get("sign"):
            notes.append(
                f"Your Midheaven is in {mc.get('sign')}, describing the public direction of your work."
            )

    elif section == "Your Growth Blueprint":
        pass
    elif section == "Alignment & Action":
        for key in ("sun", "moon", "mars", "saturn"):
            note = placement_note(f"Your {key.title()}",key)
            if note:
                notes.append(note)

        notes.extend(
            aspect_notes(
                ["sun", "moon", "mars", "saturn"],
                limit=3,
                application="alignment decisions",
            )
        )

    elif section == "Personalized Action Plan":
        for key in ("sun", "moon", "mars", "saturn"):
            note = placement_note(f"Your {key.title()}",key)
            if note:
                notes.append(note)

        note = rising_note()
        if note:
            notes.append(note)

        notes.extend(
            aspect_notes(
                ["sun", "moon", "mars", "saturn"],
                limit=3,
                application="the action plan",
            )
        )

    elif section == "Your Blueprint Summary":
        pass
    elif section == "Your Next Chapter / Continue":
        sun = placement_note("Sun", "sun")
        moon = placement_note("Moon", "moon")
        rising = rising_note()

        if sun:
            notes.append(sun)
        if moon:
            notes.append(moon)
        if rising:
            notes.append(rising)

    notes.extend(render_synthesis_notes(section, f.get("synthesis_anchors", {})))
    notes.extend(render_emotional_note(section,f))
    return notes

def compose_report(context: dict, report_id: str) -> dict:
    customer = _customer_name(context)
    block_sections={}
    for sec in SECTION_ORDER:
        cfg=context["sections"].get(sec,{"source_blocks":[]})
        for block in cfg.get("source_blocks",[]):
            cleaned=_clean_source(block.get("source_text",""),customer)
            if cleaned:
                block_sections.setdefault(cleaned,[]).append(sec)
    block_owners={text:source_block_owner(sections) for text,sections in block_sections.items()}
    sections=[]
    for sec in SECTION_ORDER:
        cfg=context["sections"].get(sec,{"status":"REVIEW_REQUIRED","source_blocks":[]})
        if cfg["status"]=="OMITTED_BY_MODE":
            sections.append({"section_id":sec.lower().replace(" ","_"),"title":sec,"status":"OMITTED_BY_MODE","content":"","evidence_refs":[]})
            continue
        blocks=cfg.get("source_blocks",[])
        body=[]; used_blocks=[]
        for b in blocks:
           cleaned = _clean_source(b.get("source_text",""), customer)
           if cleaned and block_owners.get(cleaned)==sec and cleaned not in body:
                body.append(cleaned)
                used_blocks.append(b)
        if sec in ("Your Core Identity — Sun","Your Emotional World — Moon","How the World Meets You — Rising"):
            key={"Your Core Identity — Sun":"sun","Your Emotional World — Moon":"moon","How the World Meets You — Rising":"rising"}[sec]
            if key=="rising":
                sign=context["chart_facts"].get("angles",{}).get("ascendant",{}).get("sign")
            else:
                sign=context["chart_facts"].get("placements",{}).get(key,{}).get("sign")
            specific=[]
            for item in body:
                if sign and re.match(rf"^{re.escape(sign)}(?:\s+(?:SUN|MOON|RISING))?\b",item,re.I):
                    specific.append(re.sub(rf"^{re.escape(sign)}(?:\s+(?:SUN|MOON|RISING))?\s*", "", item, count=1, flags=re.I))
            if specific:
                body=[f"YOUR {sign.upper()} {key.upper()}\n"+"\n\n".join(specific)]
        notes=_fact_notes(context,sec)
        synthesis_heavy={"Your Big Three","Your Inner Wiring","Your Relationship Blueprint","Your Career & Purpose Blueprint","Your Growth Blueprint","Personalized Action Plan","Your Blueprint Summary"}
        content_parts=(body[:1]+notes+body[1:]) if sec in synthesis_heavy and body else (body+notes)
        content="\n\n".join(content_parts)
        if sec=="Welcome to Your Blueprint":
            quote='"The greatest project you will ever build is yourself."'
            first=content.find(quote)
            if first>=0:
                content=content[:first+len(quote)]+content[first+len(quote):].replace(quote,"",1)
        display_title="THE ARCHITECT BLUEPRINT" if sec == "Personalized Cover" else sec
        content=_proofread_customer_text(content, display_title)
        sections.append({
            "section_id":sec.lower().replace(" ","_").replace("/","_"),
            "title": display_title,
            "status":"INCLUDED" if content else "REVIEW_REQUIRED",
            "content":content,
            "evidence_refs":[b["source_content_id"] for b in used_blocks]
        })
    return {
        "report_id":report_id,
        "schema_version":"blueprint_report_v1",
        "context_version":context["context_version"],
        "mode":context["mode"],
        "customer":context["customer"],
        "chart_summary": {
            "sun": context.get("chart_facts", {}).get("placements", {}).get("sun", {}),
            "moon": context.get("chart_facts", {}).get("placements", {}).get("moon", {}),
            "rising": context.get("chart_facts", {}).get("angles", {}).get("ascendant", {}),
        },
        "sections":sections,
        "qa":{"source_boundary":"LOCKED_TO_CONTEXT","new_astrology_added":False}
    }
