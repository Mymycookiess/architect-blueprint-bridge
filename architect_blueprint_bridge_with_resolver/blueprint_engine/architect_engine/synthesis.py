from __future__ import annotations
import re

APPROVED_PLANETS = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
ELEMENTS = {
    "Aries": "Fire", "Leo": "Fire", "Sagittarius": "Fire",
    "Taurus": "Earth", "Virgo": "Earth", "Capricorn": "Earth",
    "Gemini": "Air", "Libra": "Air", "Aquarius": "Air",
    "Cancer": "Water", "Scorpio": "Water", "Pisces": "Water",
}
MODALITIES = {
    "Aries": "Cardinal", "Cancer": "Cardinal", "Libra": "Cardinal", "Capricorn": "Cardinal",
    "Taurus": "Fixed", "Leo": "Fixed", "Scorpio": "Fixed", "Aquarius": "Fixed",
    "Gemini": "Mutable", "Virgo": "Mutable", "Sagittarius": "Mutable", "Pisces": "Mutable",
}
SECTION_FACTORS = {
    "Your Big Three": ("sun", "moon", "rising"),
    "Your Inner Wiring": ("sun", "mercury", "venus", "mars", "jupiter", "saturn"),
    "Your Relationship Blueprint": ("venus", "mars", "moon", "rising", "saturn"),
    "Your Career & Purpose Blueprint": ("sun", "mercury", "mars", "jupiter", "saturn", "midheaven"),
    "Your Growth Blueprint": ("sun", "moon", "jupiter", "saturn"),
    "Your Blueprint Summary": ("sun", "moon", "rising", "mercury", "venus", "mars", "jupiter", "saturn", "midheaven"),
}

SYNTHESIS_HEAVY_SECTIONS = set(SECTION_FACTORS)


def section_synthesis_rules(title):
    if title=="Your Big Three":
        return "Integrate the validated Sun, Moon, and Rising as three interacting layers. In PARTIAL mode, integrate Sun and Moon only and never mention Rising or houses."
    if title in SYNTHESIS_HEAVY_SECTIONS:
        return "Use this section's synthesis_anchors to connect multiple materially relevant validated factors, including listed aspects or recurring patterns when present. Translate the connection into clear human meaning; do not list placements or reuse synthesis prose from another chapter."
    return "Keep the chapter centered on its main subject. Use at most one light cross-reference to another validated factor and save deeper whole-chart integration for later synthesis chapters."


def _factor(chart, key):
    if key in APPROVED_PLANETS:
        placement=chart.get("placements",{}).get(key,{})
        if not placement.get("sign"):
            return None
        return {
            "key":key,
            "label":key.title(),
            "sign":placement["sign"],
            "house":placement.get("house"),
        }
    angle_key="ascendant" if key=="rising" else key
    if key=="rising" and not chart.get("availability",{}).get("rising"):
        return None
    angle=chart.get("angles",{}).get(angle_key,{})
    if not angle.get("sign"):
        return None
    return {"key":key,"label":"Rising" if key=="rising" else "Midheaven","sign":angle["sign"],"house":None}


def _validated_aspects(chart):
    available={key for key in APPROVED_PLANETS if chart.get("placements",{}).get(key,{}).get("sign")}
    aspects=[]
    for aspect in chart.get("aspects",[]) or []:
        if aspect.get("allowed_for_v1") is False:
            continue
        body_a=aspect.get("body_a") or aspect.get("body1") or aspect.get("aspecting_planet")
        body_b=aspect.get("body_b") or aspect.get("body2") or aspect.get("aspected_planet")
        aspect_type=aspect.get("type") or aspect.get("aspect")
        if not body_a or not body_b or not aspect_type:
            continue
        if body_a.lower() not in available or body_b.lower() not in available:
            continue
        aspects.append({
            "body_a":body_a,
            "body_b":body_b,
            "type":aspect_type,
            "orb":aspect.get("orb"),
        })
    return aspects


def _recurring_patterns(factors):
    results=[]
    for name,mapping in (("element",ELEMENTS),("modality",MODALITIES)):
        members={}
        for factor in factors:
            value=mapping.get(factor["sign"])
            if value:
                members.setdefault(value,[]).append(factor["label"])
        for value,labels in members.items():
            if len(labels)>=2:
                results.append({"kind":name,"value":value,"factors":labels})
    return results


def build_synthesis_anchors(chart):
    mode=chart.get("calculation",{}).get("mode")
    aspects=_validated_aspects(chart)
    anchors={}
    for section,keys in SECTION_FACTORS.items():
        factors=[factor for key in keys if (factor:=_factor(chart,key))]
        if mode=="PARTIAL":
            factors=[factor for factor in factors if factor["key"] not in ("rising","midheaven") and factor["house"] is None]
        factor_keys={factor["key"] for factor in factors}
        relevant_aspects=[
            aspect for aspect in aspects
            if aspect["body_a"].lower() in factor_keys and aspect["body_b"].lower() in factor_keys
        ]
        anchors[section]={
            "factors":factors,
            "aspects":relevant_aspects,
            "recurring_patterns":_recurring_patterns(factors) if section=="Your Blueprint Summary" else [],
        }
    return anchors


def render_synthesis_notes(section, anchors):
    anchor=anchors.get(section,{})
    factors={factor["key"]:factor for factor in anchor.get("factors",[])}
    if len(factors)<2:
        return []

    def named(key):
        factor=factors.get(key)
        return None if not factor else f'{factor["sign"]} {factor["label"]}'

    notes=[]
    if section=="Your Big Three":
        sun=named("sun"); moon=named("moon"); rising=named("rising")
        if sun and moon and rising:
            notes.append(f"Big Three synthesis: Your {sun} describes your core direction, while your {moon} names the emotional needs beneath it. Your {rising} shapes how those inner layers first meet the world, so all three belong in the same picture.")
        elif sun and moon:
            notes.append(f"Core synthesis: Your {sun} describes your core direction, while your {moon} names the emotional needs that must be considered alongside it.")
    elif section=="Your Inner Wiring":
        names=[named(key) for key in ("mercury","venus","mars","saturn") if named(key)]
        notes.append("Inner-wiring synthesis: "+", ".join(names[:-1])+f", and {names[-1]} work as connected parts of how you think, relate, act, and create structure—not as isolated labels.")
    elif section=="Your Relationship Blueprint":
        names=[named(key) for key in ("venus","mars","moon","rising","saturn") if named(key)]
        notes.append("Relationship synthesis: "+", ".join(names[:-1])+f", and {names[-1]} bring connection style, desire, emotional safety, presence, and commitment into one relational pattern.")
    elif section=="Your Career & Purpose Blueprint":
        mc=named("midheaven")
        names=[named(key) for key in ("sun","mercury","mars","jupiter","saturn") if named(key)]
        prefix=f"Your {mc} gives the career picture its public direction; " if mc else "Your career picture brings several chart patterns together: "
        notes.append("Career synthesis: "+prefix+", ".join(names)+" show how identity, thought, effort, growth, and long-term discipline support that direction.")
    elif section=="Your Growth Blueprint":
        names=[named(key) for key in ("sun","moon","jupiter","saturn") if named(key)]
        notes.append("Growth synthesis: "+", ".join(names[:-1])+f", and {names[-1]} connect who you are becoming, what steadies you emotionally, where you expand, and what asks for patient development.")
    elif section=="Your Blueprint Summary":
        sun=named("sun"); moon=named("moon"); rising=named("rising")
        if sun and moon and rising:
            notes.append(f"Whole-chart synthesis: Your {sun}, {moon}, and {rising} connect core direction, emotional grounding, and outward presence. The rest of your chart adds detail to how that foundation thinks, relates, acts, grows, and builds.")
        elif sun and moon:
            notes.append(f"Whole-chart synthesis: Your {sun} and {moon} connect core direction with emotional grounding. The other stable chart patterns add detail to how that foundation thinks, relates, acts, grows, and builds.")

    housed=[factor for factor in factors.values() if factor.get("house")]
    if section in ("Your Inner Wiring","Your Relationship Blueprint","Your Career & Purpose Blueprint") and len(housed)>=2:
        placements=", ".join(f'{factor["label"]} in House {factor["house"]}' for factor in housed[:4])
        notes.append(f"{placements} show where these connected patterns become most visible in daily life.")

    aspect_context={
        "Your Inner Wiring":"In your inner-wiring pattern",
        "Your Relationship Blueprint":"In your relationship pattern",
        "Your Career & Purpose Blueprint":"In your career pattern",
        "Your Growth Blueprint":"In your growth pattern",
        "Your Blueprint Summary":"In the whole-chart picture",
    }.get(section,"In this chapter")
    for aspect in anchor.get("aspects",[])[:2]:
        connection=f'the {aspect["type"].lower()} between {aspect["body_a"]} and {aspect["body_b"]}'
        connection=connection[0].upper()+connection[1:]
        if section=="Your Inner Wiring":
            notes.append(f'{connection} brings identity, thought, and action into the same inner conversation, showing how these parts of you cooperate rather than operate alone. Read this aspect as a point where the roles of {aspect["body_a"]} and {aspect["body_b"]} exchange momentum and shape a more coherent inner response.')
        elif section=="Your Blueprint Summary":
            notes.append(f'{connection} belongs to the larger through-line of your chart, linking self-direction with the way you think, communicate, and move into action. Your choices feel more coherent when the needs represented by {aspect["body_a"]} and {aspect["body_b"]} are given room in the same decision instead of being handled as unrelated parts of you.')
        elif section=="Your Career & Purpose Blueprint":
            notes.append(f'{connection} connects your sense of direction with the thinking and effort that carry purpose into visible work.')
        elif section=="Your Relationship Blueprint":
            notes.append(f'{connection} links the way you relate with the choices and responses that shape connection in practice.')
        elif section=="Your Growth Blueprint":
            notes.append(f'{connection} shows where growth asks different parts of you to develop in cooperation rather than in isolation.')
        else:
            notes.append(f'{connection} adds another connected layer to {aspect_context.lower().removeprefix("in ")}.')
    for pattern in anchor.get("recurring_patterns",[])[:2]:
        labels=", ".join(pattern["factors"])
        notes.append(f'A recurring {pattern["kind"]} pattern emerges: {pattern["value"]} appears across {labels}.')
    return notes


SYNTHESIS_PREFIXES = (
    "Big Three synthesis:",
    "Core synthesis:",
    "Inner-wiring synthesis:",
    "Relationship synthesis:",
    "Career synthesis:",
    "Growth synthesis:",
    "Whole-chart synthesis:",
    "Validated synthesis aspect:",
    "Recurring validated ",
    "House synthesis for this life area:",
)


def report_synthesis_rule_issues(context, report):
    chart_facts=context.get("chart_facts",{})
    anchors=chart_facts.get("synthesis_anchors",{})
    mode=context.get("mode")
    by_title={section.get("title"):section for section in report.get("sections",[])}
    issues=[]
    seen={}
    for section,anchor in anchors.items():
        content=str(by_title.get(section,{}).get("content") or "")
        factors=anchor.get("factors",[])
        if len(factors)>=2:
            referenced=[
                factor for factor in factors
                if f'{factor["sign"]} {factor["label"]}'.lower() in content.lower()
            ]
            if len(referenced)<2:
                issues.append(f"{section}: fewer than two validated factors are integrated")
        for paragraph in content.split("\n\n"):
            clean=paragraph.strip()
            if clean.startswith(SYNTHESIS_PREFIXES):
                if clean in seen:
                    issues.append(f"Duplicate synthesis text in {seen[clean]} and {section}")
                seen[clean]=section

    big_three=str(by_title.get("Your Big Three",{}).get("content") or "")
    if mode=="FULL":
        required=anchors.get("Your Big Three",{}).get("factors",[])
        for factor in required:
            phrase=f'{factor["sign"]} {factor["label"]}'
            if phrase.lower() not in big_three.lower():
                issues.append(f"FULL Big Three missing validated factor: {phrase}")
    elif mode=="PARTIAL":
        if re.search(r"\b(?:rising|ascendant|house\s+\d+)\b",big_three,re.I):
            issues.append("PARTIAL Big Three references Rising, Ascendant, or houses")

    known_factors={
        factor["key"]:(factor["sign"],factor.get("house"))
        for anchor in anchors.values() for factor in anchor.get("factors",[])
    }
    body_keys={key.title():key for key in APPROVED_PLANETS}
    body_keys.update({"Rising":"rising","Midheaven":"midheaven"})
    signs="|".join(ELEMENTS)
    bodies="|".join(body_keys)
    all_content="\n".join(str(section.get("content") or "") for section in report.get("sections",[]))
    placement_patterns=(
        re.compile(rf"\b({signs})[ \t]+({bodies})\b",re.I),
        re.compile(rf"\b({bodies})[ \t]+(?:in[ \t]+)?({signs})\b",re.I),
    )
    for index,pattern in enumerate(placement_patterns):
        for match in pattern.finditer(all_content):
            sign,body=(match.group(1),match.group(2)) if index==0 else (match.group(2),match.group(1))
            canonical_body=next((name for name in body_keys if name.lower()==body.lower()),body)
            key=body_keys.get(canonical_body)
            expected=known_factors.get(key)
            if expected is None or expected[0].lower()!=sign.lower():
                issues.append(f"Unvalidated placement introduced: {sign} {canonical_body}")
    for match in re.finditer(rf"\b({bodies})[ \t]+in[ \t]+House[ \t]+(\d+)\b",all_content,re.I):
        body,house=match.group(1),int(match.group(2))
        canonical_body=next((name for name in body_keys if name.lower()==body.lower()),body)
        expected=known_factors.get(body_keys.get(canonical_body))
        if expected is None or expected[1]!=house:
            issues.append(f"Unvalidated house placement introduced: {canonical_body} in House {house}")
    valid_aspects={
        (aspect["body_a"].lower(),aspect["type"].lower(),aspect["body_b"].lower())
        for anchor in anchors.values() for aspect in anchor.get("aspects",[])
    }
    aspect_types=("Conjunction","Sextile","Square","Trine","Opposition")
    for match in re.finditer(rf"\b({bodies})[ \t]+({'|'.join(aspect_types)})[ \t]+({bodies})\b",all_content,re.I):
        found=(match.group(1).lower(),match.group(2).lower(),match.group(3).lower())
        reverse=(found[2],found[1],found[0])
        if found not in valid_aspects and reverse not in valid_aspects:
            issues.append(f"Unvalidated aspect introduced: {' '.join(match.groups())}")

    return issues
