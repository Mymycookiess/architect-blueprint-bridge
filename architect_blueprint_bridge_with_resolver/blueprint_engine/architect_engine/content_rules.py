from __future__ import annotations
import re
from typing import Optional

ACTION_PLAN_SECTION = "Personalized Action Plan"
FIRST_BRICK_SECTION = "Your First / Next Brick"
ACTION_PLAN_HEADINGS = (
    "Strengths",
    "Supporting Habits",
    "Patterns to Watch",
    "Challenge",
    "Encouraging Message",
    "Next Brick",
)


def section_writing_rules(title: str) -> str:
    if title == ACTION_PLAN_SECTION:
        return """This is the one dedicated full Action Plan. Include exactly these six parts:
- 3 strengths
- 3 supporting habits
- 3 patterns to watch
- 1 challenge
- 1 encouraging message
- 1 Next Brick

Ground the plan in THIS customer's supplied personalization_context, not generic self-help.
Across the six parts, explicitly connect at least four materially relevant validated chart factors
using their exact sign + planet/angle names when available, and use validated aspects when the
context supplies them. Translate each factor or aspect into a concrete behavior, choice, habit,
relationship pattern, or decision the customer can recognize in real life. Do not merely list
placements. Do not invent Rising, houses, Midheaven, aspects, or any missing chart fact. In
PARTIAL mode, never reference Rising or houses. Each habit/challenge must be realistic and
specific enough to try within normal life; avoid generic advice such as simply 'journal more',
'be yourself', or 'trust the process' unless it is tied to a named validated chart pattern and a
clear action."""
    if title == FIRST_BRICK_SECTION:
        return """Preserve this focused First / Next Brick chapter. Do not turn it into the
six-part Personalized Action Plan or repeat that template. Choose one concrete, realistic action
that follows from the customer's strongest validated themes and can be started immediately."""
    return """Do not use Action Plan headings or reproduce the Strengths / Supporting Habits /
Patterns to Watch / Challenge / Encouraging Message / Next Brick template in this chapter.
Deepen recognition and understanding first. If a closing device is useful, label it
Architect Reflection and use only 1–2 short personalized prompts or observations,
60–90 words maximum. Do not add a checklist or generic motivational filler. Advance this
chapter's specific purpose rather than restating explanations already owned by earlier chapters."""


def _heading_pattern(heading: str) -> re.Pattern:
    return re.compile(
        rf"(?im)^\s*(?:#+\s*)?(?:your\s+)?{re.escape(heading)}\s*:?[ \t]*$"
    )


def action_plan_headings(content: str) -> list[str]:
    return [heading for heading in ACTION_PLAN_HEADINGS if _heading_pattern(heading).search(content or "")]


def _reflection_text(content: str) -> Optional[str]:
    match = re.search(r"(?im)^\s*(?:#+\s*)?Architect Reflection\s*:?[ \t]*$", content or "")
    return None if match is None else content[match.end():].strip()


def section_content_rule_issues(title: str, content: str) -> list[str]:
    issues=[]
    headings=action_plan_headings(content)
    if title != ACTION_PLAN_SECTION and headings:
        issues.append(f"Action Plan headings outside {ACTION_PLAN_SECTION}: {', '.join(headings)}")
    reflection=_reflection_text(content)
    if title != ACTION_PLAN_SECTION and reflection is not None:
        words=len(re.findall(r"\b[\w’'-]+\b", reflection))
        prompts=reflection.count("?")
        checklist_lines=sum(
            1 for line in reflection.splitlines()
            if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", line)
        )
        if words > 90:
            issues.append(f"Architect Reflection exceeds 90 words ({words})")
        if prompts > 2:
            issues.append(f"Architect Reflection exceeds 2 prompts ({prompts})")
        if checklist_lines > 2:
            issues.append(f"Architect Reflection contains a large checklist ({checklist_lines} items)")
    return issues


def report_content_rule_issues(report: dict) -> list[str]:
    issues=[]
    by_title={section.get("title"):section for section in report.get("sections",[])}
    for title,section in by_title.items():
        issues.extend(f"{title}: {issue}" for issue in section_content_rule_issues(title,section.get("content","")))
    for required in (ACTION_PLAN_SECTION,FIRST_BRICK_SECTION):
        section=by_title.get(required,{})
        if section.get("status")!="INCLUDED" or not str(section.get("content") or "").strip():
            issues.append(f"Required final section did not render: {required}")
    return issues
