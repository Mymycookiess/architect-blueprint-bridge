from __future__ import annotations
import re
from difflib import SequenceMatcher

SYNTHESIS_HEAVY_SECTIONS = (
    "Your Big Three",
    "Your Inner Wiring",
    "Your Relationship Blueprint",
    "Your Career & Purpose Blueprint",
    "Your Growth Blueprint",
    "Personalized Action Plan",
    "Your Blueprint Summary",
)
SPECIFIC_CHAPTER_PRIORITY = {
    "Your Story Begins Here": 0,
    "Your Blueprint Summary": 10,
    "Personalized Cover": 10,
    "Welcome to Your Blueprint": 10,
    "Birth Chart Snapshot": 10,
    "Your Core Identity — Sun": 30,
    "Your Emotional World — Moon": 30,
    "How the World Meets You — Rising": 30,
    "Your Big Three": 30,
}


def source_block_owner(section_names):
    return max(section_names,key=lambda name:(SPECIFIC_CHAPTER_PRIORITY.get(name,20),-list(section_names).index(name)))


def _normalize_sentence(sentence):
    text=re.sub(r"[^a-z0-9' ]"," ",sentence.lower())
    return re.sub(r"\s+"," ",text).strip()


def meaningful_sentences(content):
    flattened=re.sub(r"\s*\n\s*"," ",content or "")
    return [
        (sentence.strip(),_normalize_sentence(sentence))
        for sentence in re.split(r"(?<=[.!?])\s+",flattened)
        if len(_normalize_sentence(sentence).split())>=8
    ]


def _core_paragraphs(content):
    prefixes=(
        "Big Three synthesis:","Core synthesis:","Inner-wiring synthesis:",
        "Relationship synthesis:","Career synthesis:","Growth synthesis:",
        "Whole-chart synthesis:","Lived experience:",
    )
    return [
        _normalize_sentence(paragraph)
        for paragraph in (content or "").split("\n\n")
        if paragraph.strip().startswith(prefixes)
    ]


def _substantial_paragraphs(content):
    results=[]
    for paragraph in (content or "").split("\n\n"):
        normalized=_normalize_sentence(paragraph)
        words=normalized.split()
        if len(words)>=32:
            results.append(normalized)
    return results


def section_progression_rules(title):
    if title in ("Your Core Identity — Sun","Your Emotional World — Moon","How the World Meets You — Rising"):
        return "Own and introduce this placement's core lived pattern. Keep cross-references brief so later chapters have room to apply and integrate it."
    if title=="Your Big Three":
        return "Integrate the three layers and explain their interaction; do not repeat the standalone Sun, Moon, or Rising explanation."
    if title in ("Your Inner Wiring","Your Relationship Blueprint","Your Career & Purpose Blueprint","Your Growth Blueprint"):
        return "Apply earlier chart discoveries to this chapter's specific life area. A callback must add a new context, consequence, tension, choice, or application and remain concise."
    if title=="Personalized Action Plan":
        return "Convert earlier insights into decisions and behaviors. Do not summarize or restate previous chapters; every callback must become a specific action, habit, pattern-to-watch, challenge, or Next Brick."
    if title=="Your Blueprint Summary":
        return "Name the concise whole-chart through-line without copying or rephrasing entire earlier explanations. End with integration, not recap."
    return "Advance this chapter's purpose without repeating an explanation already owned by another chapter."


def report_repetition_rule_issues(report):
    issues=[]
    seen={}
    for section in report.get("sections",[]):
        if section.get("status")!="INCLUDED":
            continue
        title=section.get("title")
        for original,normalized in meaningful_sentences(section.get("content","")):
            owner=seen.get(normalized)
            if owner and owner!=title:
                issues.append(f'Exact meaningful sentence repeated in {owner} and {title}: "{original[:100]}"')
            else:
                seen[normalized]=title

    paragraphs=[]
    for section in report.get("sections",[]):
        if section.get("title") in SYNTHESIS_HEAVY_SECTIONS:
            for paragraph in _core_paragraphs(section.get("content","")):
                for other_title,other in paragraphs:
                    ratio=SequenceMatcher(None,other,paragraph).ratio()
                    if ratio>=0.86:
                        issues.append(f"Near-duplicate core insight in {other_title} and {section.get('title')} ({ratio:.2f})")
                paragraphs.append((section.get("title"),paragraph))

    # Catch substantial passages that are rephrased too closely across chapters,
    # not just identical sentences. This is intentionally conservative so normal
    # short callbacks are still allowed.
    substantial=[]
    for section in report.get("sections",[]):
        if section.get("status")!="INCLUDED":
            continue
        title=section.get("title")
        for paragraph in _substantial_paragraphs(section.get("content","")):
            for other_title,other in substantial:
                if other_title==title:
                    continue
                ratio=SequenceMatcher(None,other,paragraph).ratio()
                if ratio>=0.91:
                    issues.append(f"Near-duplicate substantial passage in {other_title} and {title} ({ratio:.2f})")
            substantial.append((title,paragraph))

    summary=next((section for section in report.get("sections",[]) if section.get("title")=="Your Blueprint Summary"),{})
    summary_paragraphs={normalized for _,normalized in meaningful_sentences(summary.get("content",""))}
    for section in report.get("sections",[]):
        if section.get("title")=="Your Blueprint Summary":
            continue
        overlap=summary_paragraphs & {normalized for _,normalized in meaningful_sentences(section.get("content",""))}
        if overlap:
            issues.append(f"Blueprint Summary copies {len(overlap)} meaningful sentence(s) from {section.get('title')}")
    return issues
