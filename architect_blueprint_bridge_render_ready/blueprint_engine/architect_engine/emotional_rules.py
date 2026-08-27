from __future__ import annotations
import re

EMOTIONAL_SECTIONS = (
    "Your Emotional World — Moon",
    "Your Big Three",
    "Your Inner Wiring",
    "Your Relationship Blueprint",
    "Your Career & Purpose Blueprint",
    "Your Growth Blueprint",
    "Your Blueprint Summary",
)
EXPERIENTIAL_MARKERS = (
    "feel", "need", "safe", "seen", "understood", "misunderstood",
    "pressure", "stress", "protect", "hide", "trust", "boundary",
    "respond", "react", "decide", "choice", "conflict", "comfort",
    "secure", "fulfilled", "settle",
)
GENERIC_ASTROLOGY_PHRASES = (
    "this placement means",
    "this placement suggests",
    "you value",
    "you prefer",
    "you may prefer",
)
OVERREACH_PHRASES = (
    "your trauma", "traumatic experience", "you were abused",
    "attachment disorder", "personality disorder", "you are depressed",
    "you have anxiety", "you are bipolar", "you have ptsd",
    "when you were a child", "in your childhood", "you grew up",
    "your past relationship", "this happened to you",
)


def section_emotional_rules(title):
    if title not in EMOTIONAL_SECTIONS:
        return "Keep any emotional language relevant to the chapter and grounded in its selected source blocks."
    return """Translate the validated factors and selected source ideas into concrete lived experience: what the person notices internally, needs from others, protects, does under pressure, or considers when making choices. Show reinforcement or tension only when supported by the supplied synthesis anchors. Use compassionate, direct language without sounding therapeutic. Do not invent biography, trauma, childhood events, diagnoses, relationship history, or unsupported reactions. Prefer recognizable dynamics over a list of abstract traits."""


def render_emotional_note(section, chart_facts):
    anchors=chart_facts.get("synthesis_anchors",{})
    factors={factor["key"]:factor for factor in anchors.get(section,{}).get("factors",[])}

    def named(key):
        factor=factors.get(key)
        return None if not factor else f'{factor["sign"]} {factor["label"]}'

    if section=="Your Emotional World — Moon":
        moon=chart_facts.get("placements",{}).get("moon",{})
        if moon.get("sign"):
            return [f'Lived experience: Your {moon["sign"]} Moon is easiest to recognize through what helps you feel secure, what unsettles that security, and what you need before an emotional response feels honest.']
    if section=="Your Big Three":
        sun=named("sun"); moon=named("moon"); rising=named("rising")
        if sun and moon and rising:
            return [f'Lived experience: Your {sun}, {moon}, and {rising} do not always move at the same pace. Notice the moments when what you feel inside, what you choose, and what you are ready to show other people need to be reconciled.']
        if sun and moon:
            return [f'Lived experience: Your {sun} and {moon} become clearest in the space between what you decide and what you need emotionally before that decision feels settled.']
    if section=="Your Inner Wiring" and len(factors)>=2:
        return ["Lived experience: Under pressure, this wiring becomes visible in the gap between what you think, what you value, and how quickly you act. Recognizing that sequence gives you a clearer choice about how to respond."]
    if section=="Your Relationship Blueprint" and len(factors)>=2:
        return ["Lived experience: In close relationships, notice whether the way you pursue connection matches what helps you feel safe and understood. When those needs pull differently, boundaries and timing become part of the conversation."]
    if section=="Your Career & Purpose Blueprint" and len(factors)>=2:
        return ["Lived experience: Work feels more fulfilling when your public direction, daily decisions, effort, and long-term standards support the same goal. Pressure builds when success asks you to protect one of those needs by ignoring another."]
    if section=="Your Growth Blueprint" and len(factors)>=2:
        return ["Lived experience: Growth becomes personal at the moment an old source of comfort conflicts with the choice that moves you forward. The useful signal is not discomfort alone, but what you protect or avoid when it appears."]
    if section=="Your Blueprint Summary" and len(factors)>=2:
        return ["Lived experience: The whole chart becomes recognizable in recurring moments—what helps you settle, what makes you protect your energy, how you decide whom to trust, and what allows your choices to feel aligned from the inside out."]
    return []


def section_emotional_rule_issues(title, content, status="INCLUDED"):
    issues=[]
    for phrase in OVERREACH_PHRASES:
        if phrase in (content or "").lower():
            issues.append(f'Unsupported emotional overreach: "{phrase}"')
    if title in EMOTIONAL_SECTIONS and status!="OMITTED_BY_MODE":
        markers={marker for marker in EXPERIENTIAL_MARKERS if re.search(rf"\b{re.escape(marker)}\w*\b",content,re.I)}
        direct=re.search(r"\byou\s+(?:feel|need|notice|protect|hide|trust|respond|react|decide|choose|settle|struggle|hold)\b",content,re.I)
        if len(markers)<3 or direct is None:
            issues.append(f"{title}: insufficient concrete emotional/behavioral language")
        generic=sum(len(re.findall(re.escape(phrase),content,re.I)) for phrase in GENERIC_ASTROLOGY_PHRASES)
        if generic>6:
            issues.append(f"{title}: generic astrology-only phrasing is repeated ({generic})")
    return issues


def report_emotional_rule_issues(report):
    issues=[]
    for section in report.get("sections",[]):
        issues.extend(section_emotional_rule_issues(
            section.get("title"),str(section.get("content") or ""),section.get("status")
        ))
    return issues
