
from __future__ import annotations
import re

SECTION_ORDER = [
"Personalized Cover","Welcome to Your Blueprint","Birth Chart Snapshot","Your Story Begins Here",
"Your Core Identity — Sun","Your Emotional World — Moon","How the World Meets You — Rising","Your Big Three",
"Your Houses / Life Areas","Your Inner Wiring","Your Relationship Blueprint","Your Career & Purpose Blueprint",
"Your Growth Blueprint","Alignment & Action","Personalized Action Plan","Your First / Next Brick",
"Your Blueprint Summary","Your Next Chapter / Continue"
]

def _clean_source(text, customer=""):
    text = (text or "").replace("@CUSTOMER NAME@", customer)
    # Strip common internal brackets/instructions defensively.
    text=re.sub(r"\[[^\]]+\]","",text)
    lines=[ln.strip() for ln in text.splitlines()]
    return "\n".join([ln for ln in lines if ln and "website will automatically" not in ln.lower()])

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

    def aspect_notes(body_names=None, limit=3):
        results = []

        for aspect in f.get("aspects", []) or []:
            body1 = (
                aspect.get("body1")
                or aspect.get("planet1")
                or aspect.get("first")
                or ""
            )
            body2 = (
                aspect.get("body2")
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
            orb = aspect.get("orb")

            if not body1 or not body2 or not aspect_type:
                continue

            if body_names:
                wanted = {x.lower() for x in body_names}
                if body1.lower() not in wanted and body2.lower() not in wanted:
                    continue

            orb_text = ""
            if isinstance(orb, (int, float)):
                orb_text = f" — orb {orb:.2f}°"

            results.append(
                f"Verified aspect: {body1} {aspect_type} {body2}{orb_text}."
            )

            if len(results) >= limit:
                break

        return results

    if section == "Birth Chart Snapshot":
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
        note = placement_note("Verified chart note — Sun", "sun")
        if note:
            notes.append(note)

        notes.extend(aspect_notes(["sun"], limit=2))

    elif section == "Your Emotional World — Moon":
        note = placement_note("Verified chart note — Moon", "moon")
        if note:
            notes.append(note)

        notes.extend(aspect_notes(["moon"], limit=2))

    elif section == "How the World Meets You — Rising":
        asc = f.get("angles", {}).get("ascendant", {})
        if asc.get("sign"):
            notes.append(
                f"Verified chart note: {asc.get('sign')} Rising."
            )

    elif section == "Your Inner Wiring":
        for key in ("mercury", "venus", "mars", "jupiter", "saturn"):
            note = placement_note(key.title(), key)
            if note:
                notes.append(note)

        notes.extend(
            aspect_notes(
                ["mercury", "venus", "mars"],
                limit=3,
            )
        )

    elif section == "Your Relationship Blueprint":
        for key in ("venus", "mars", "moon"):
            note = placement_note(
                f"Relationship chart anchor — {key.title()}",
                key,
            )
            if note:
                notes.append(note)

        note = rising_note()
        if note:
            notes.append(f"Relationship axis anchor — {note}")

        notes.extend(
            aspect_notes(
                ["venus", "mars", "moon"],
                limit=3,
            )
        )

    elif section == "Your Career & Purpose Blueprint":
        mc = f.get("angles", {}).get("midheaven", {})
        if mc.get("sign"):
            notes.append(
                "Verified chart note: "
                f"10th-house / Midheaven sign {mc.get('sign')}."
            )

        for key in ("sun", "jupiter", "saturn", "mars"):
            note = placement_note(
                f"Career chart anchor — {key.title()}",
                key,
            )
            if note:
                notes.append(note)

    elif section == "Your Growth Blueprint":
        for key in ("saturn", "jupiter"):
            note = placement_note(
                f"Growth chart anchor — {key.title()}",
                key,
            )
            if note:
                notes.append(note)

        notes.extend(
            aspect_notes(
                ["saturn", "jupiter"],
                limit=3,
            )
        )

    elif section == "Alignment & Action":
        for key in ("sun", "moon", "mars", "saturn"):
            note = placement_note(
                f"Alignment chart anchor — {key.title()}",
                key,
            )
            if note:
                notes.append(note)

        notes.extend(
            aspect_notes(
                ["sun", "moon", "mars", "saturn"],
                limit=3,
            )
        )

    elif section == "Personalized Action Plan":
        for key in ("sun", "moon", "mars", "saturn"):
            note = placement_note(
                f"Action-plan chart anchor — {key.title()}",
                key,
            )
            if note:
                notes.append(note)

        note = rising_note()
        if note:
            notes.append(f"Action-plan chart anchor — {note}")

        notes.extend(
            aspect_notes(
                ["sun", "moon", "mars", "saturn"],
                limit=3,
            )
        )

    elif section == "Your Blueprint Summary":
        for key in ("sun", "moon"):
            note = placement_note(
                f"Summary anchor — {key.title()}",
                key,
            )
            if note:
                notes.append(note)

        note = rising_note()
        if note:
            notes.append(f"Summary anchor — {note}")

        notes.extend(aspect_notes(limit=2))

    elif section == "Your Next Chapter / Continue":
        sun = placement_note("Sun", "sun")
        moon = placement_note("Moon", "moon")
        rising = rising_note()

        if sun:
            notes.append(f"Blueprint anchor — {sun}")
        if moon:
            notes.append(f"Blueprint anchor — {moon}")
        if rising:
            notes.append(f"Blueprint anchor — {rising}")

    return notes

def compose_report(context: dict, report_id: str) -> dict:
    customer = str(context.get("customer") or "").strip()
    sections=[]
    for sec in SECTION_ORDER:
        cfg=context["sections"].get(sec,{"status":"REVIEW_REQUIRED","source_blocks":[]})
        if cfg["status"]=="OMITTED_BY_MODE":
            sections.append({"section_id":sec.lower().replace(" ","_"),"title":sec,"status":"OMITTED_BY_MODE","content":"","evidence_refs":[]})
            continue
        blocks=cfg.get("source_blocks",[])
        body=[]
        for b in blocks:
           cleaned = _clean_source(b.get("source_text",""), customer)
            if cleaned and cleaned not in body:
                body.append(cleaned)
        notes=_fact_notes(context,sec)
        content="\n\n".join(body + notes)
        sections.append({
            "section_id":sec.lower().replace(" ","_").replace("/","_"),
            "title": "THE ARCHITECT BLUEPRINT" if sec == "Personalized Cover" else sec,
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
