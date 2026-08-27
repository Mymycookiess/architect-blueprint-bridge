
from __future__ import annotations
import json, os
from urllib.request import Request, urlopen
from architect_engine.content_rules import report_content_rule_issues
from architect_engine.confidence_rules import report_confidence_rule_issues
from architect_engine.emotional_rules import report_emotional_rule_issues
from architect_engine.repetition_rules import report_repetition_rule_issues

CONTRACT = """
You are the Architect Blueprint writing stage.
Use ONLY the supplied VALID personalization context.
Do not use raw provider data, outside astrology facts, prediction, diagnosis,
destiny language, guaranteed outcomes, or unselected library content.
Preserve FULL/PARTIAL mode gates.
Every generated section must return evidence_refs containing only source IDs
already present in that section's source_blocks.
The full Strengths / Supporting Habits / Patterns to Watch / Challenge /
Encouraging Message / Next Brick structure belongs only in Personalized Action
Plan. Earlier chapters must not repeat those headings. If useful, they may close
with an Architect Reflection of 1–2 prompts or observations and at most 90 words.
Use chart_facts.synthesis_anchors to integrate multiple validated factors in Big
Three, Inner Wiring, Relationships, Career, Growth, and Summary. PARTIAL mode
must never mention Rising or houses. Do not reuse synthesis prose across chapters
or introduce placements/aspects absent from the anchors.
State validated chart interpretations directly. Do not repeat “this may suggest,”
“you might,” “could indicate,” prediction disclaimers, or possibility reminders
throughout chapters. Put any brief interpretive boundary once in Welcome. PARTIAL
mode must explain unavailable Rising/houses once in Welcome. Continue to prohibit
guarantees, destiny, diagnosis, and absolute future prediction.
In Moon, Big Three, Inner Wiring, Relationships, Career, Growth, and Summary,
translate approved chart patterns into concrete internal experience, needs,
boundaries, pressure responses, choices, and self-perception. Do not invent
biography, trauma, diagnoses, childhood events, or relationship history.
Use a progression: introduce patterns early, apply them to distinct life areas in
the middle, integrate them later, and keep Summary concise. Do not copy exact or
near-identical insights across chapters. A callback must add a new context,
consequence, tension, choice, or application.
Return JSON in blueprint_report_v1 shape.
"""

def compose_report_with_ai(context: dict, report_id: str, endpoint: str, token_env: str="ARCHITECT_AI_TOKEN") -> dict:
    token=os.environ.get(token_env,"")
    if not endpoint:
        raise RuntimeError("AI endpoint is required.")
    body=json.dumps({
        "contract":CONTRACT,
        "report_id":report_id,
        "personalization_context":context
    }).encode("utf-8")
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]=f"Bearer {token}"
    req=Request(endpoint,data=body,headers=headers,method="POST")
    with urlopen(req,timeout=120) as resp:
        result=json.loads(resp.read().decode("utf-8"))
    if "report" in result:
        result=result["report"]
    if not isinstance(result,dict) or "sections" not in result:
        raise RuntimeError("AI endpoint did not return a valid report object.")
    issues=report_content_rule_issues(result)
    issues.extend(report_confidence_rule_issues(result))
    issues.extend(report_emotional_rule_issues(result))
    issues.extend(report_repetition_rule_issues(result))
    if issues:
        raise RuntimeError("AI report violates content rules: "+"; ".join(issues))
    return result
