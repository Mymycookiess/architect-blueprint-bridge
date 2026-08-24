
from __future__ import annotations
import json, os
from urllib.request import Request, urlopen

CONTRACT = """
You are the Architect Blueprint writing stage.
Use ONLY the supplied VALID personalization context.
Do not use raw provider data, outside astrology facts, prediction, diagnosis,
destiny language, guaranteed outcomes, or unselected library content.
Preserve FULL/PARTIAL mode gates.
Every generated section must return evidence_refs containing only source IDs
already present in that section's source_blocks.
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
    return result
