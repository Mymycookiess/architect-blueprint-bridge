from __future__ import annotations
import re

REPETITIVE_DISCLAIMERS = (
    "this may suggest",
    "this can suggest",
    "you might",
    "could indicate",
    "not a guarantee",
    "this does not mean",
    "astrology cannot predict",
)
PROHIBITED_CERTAINTY = (
    "you will definitely",
    "you are destined",
    "destined to",
    "guaranteed outcome",
    "guaranteed to",
    "your fate is",
)
DIRECT_REWRITES = (
    (r"\bthis may suggest\b", "this shows"),
    (r"\bthis can suggest\b", "this shows"),
    (r"\byou might\b", "you can"),
    (r"\bcould indicate\b", "indicates"),
    (r"\bcan offer insight into\b", "offers insight into"),
    (r"\bcan help you\b", "helps you"),
    (r"\bmay help you\b", "helps you"),
    (r"\bmay help explain\b", "helps explain"),
    (r"\bmay reveal\b", "reveals"),
    (r"\bmay influence\b", "influences"),
    (r"\bmay repeatedly\b", "repeatedly"),
    (r"\bmay naturally\b", "naturally"),
    (r"\bmay become especially noticeable\b", "is especially noticeable"),
    (r"\bmay become\b", "can become"),
    (r"\bmay express itself\b", "expresses itself"),
    (r"\bmay appear\b", "appears"),
    (r"\bmay show up\b", "shows up"),
    (r"\bmay connect\b", "connect"),
    (r"\bmay appreciate\b", "value"),
    (r"\bmay approach\b", "approach"),
    (r"\bmay need\b", "need"),
    (r"\bmay allow you to\b", "allows you to"),
    (r"\bothers may notice\b", "others notice"),
    (r"\bworld may experience you\b", "world experiences you"),
    (r"\bYour chart may offer\b", "Your chart offers"),
    (r"\bYour Blueprint may help you\b", "Your Blueprint helps you"),
    (r"\bmay be especially valuable\b", "is especially valuable"),
    (r"\bothers may not immediately see\b", "others do not immediately see"),
    (r"\bothers may initially experience\b", "others initially experience"),
    (r"\bmay sometimes feel\b", "can sometimes feel"),
    (r"\bmay immediately resonate\b", "often resonate immediately"),
    (r"\bmay feel\b", "can feel"),
    (r"\bmay recognize\b", "can recognize"),
    (r"\bmay also\b", "can also"),
    (r"\bmay include\b", "can include"),
    (r"\bmay involve\b", "can involve"),
    (r"\bmay mean\b", "can mean"),
    (r"\bmay represent\b", "can represent"),
    (r"\bmay speak\b", "can speak"),
    (r"\bmay be\b", "can be"),
    (r"\bmay look\b", "looks"),
    (r"\bmay remain\b", "can remain"),
    (r"\bmay hold\b", "hold"),
    (r"\bmay change\b", "can change"),
    (r"\bmay have\b", "can have"),
)


def _case_matched_replacement(match, replacement):
    if match.group(0)[:1].isupper():
        return replacement[:1].upper()+replacement[1:]
    return replacement


def strengthen_supported_language(text):
    strengthened=text or ""
    for pattern,replacement in DIRECT_REWRITES:
        strengthened=re.sub(
            pattern,
            lambda match,replacement=replacement:_case_matched_replacement(match,replacement),
            strengthened,
            flags=re.I,
        )
    strengthened=re.sub(
        r"Understanding Venus is not about predicting who you will love\.\s*It is about understanding",
        "Understanding Venus focuses on",
        strengthened,
        flags=re.I,
    )
    return strengthened


def hedge_count(text):
    return len(re.findall(r"\b(?:may|might|could)\b",text or "",re.I))


def section_confidence_rules(title, mode):
    boundary=(
        "Include exactly one front-matter note beginning 'Chart scope:' that explains unknown birth time means Rising and houses are omitted."
        if mode=="PARTIAL" else
        "Include at most one brief front-matter statement distinguishing chart interpretation from fixed prediction."
    )
    if title=="Welcome to Your Blueprint":
        return boundary
    return "State interpretations supported by validated chart facts directly and confidently. Do not repeat disclaimers or boundary language. Use a qualifier only for genuine ambiguity or tension. Continue to avoid prediction, guarantees, destiny, diagnosis, and certainty about future outcomes."


def section_confidence_rule_issues(title, content, mode):
    issues=[]
    for phrase in REPETITIVE_DISCLAIMERS:
        if re.search(re.escape(phrase),content or "",re.I):
            issues.append(f'Repetitive disclaimer phrase present: "{phrase}"')
    for phrase in PROHIBITED_CERTAINTY:
        if phrase.lower() in (content or "").lower():
            issues.append(f'Prohibited deterministic phrase present: "{phrase}"')
    if title!="Welcome to Your Blueprint" and re.search(r"(?im)^\s*(?:Interpretive boundary|Chart scope):",content or ""):
        issues.append("Disclaimer/data-scope note outside front matter")
    return issues


def report_confidence_rule_issues(report):
    issues=[]
    sections=report.get("sections",[])
    all_text="\n".join(str(section.get("content") or "") for section in sections)
    for section in sections:
        issues.extend(f'{section.get("title")}: {issue}' for issue in section_confidence_rule_issues(
            section.get("title"),section.get("content",""),report.get("mode")
        ))
    welcome=next((section.get("content","") for section in sections if section.get("title")=="Welcome to Your Blueprint"),"")
    if report.get("mode")=="PARTIAL":
        scopes=len(re.findall(r"(?im)^\s*Chart scope:",welcome))
        if scopes!=1 or not all(term in welcome.lower() for term in ("birth time","rising","houses")):
            issues.append("PARTIAL data limitations are not communicated exactly once in front matter")
    return issues
