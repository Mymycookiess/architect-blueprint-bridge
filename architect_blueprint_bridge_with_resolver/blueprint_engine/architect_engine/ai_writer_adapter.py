
from __future__ import annotations
import json, os
from urllib.request import Request, urlopen

from architect_engine.writer import SECTION_ORDER

CONTRACT = """
You are the Architect Blueprint writing stage.
Use ONLY the supplied VALID personalization context.
Do not use raw provider data, outside astrology facts, prediction, diagnosis,
destiny language, guaranteed outcomes, or unselected library content.
Preserve FULL/PARTIAL mode gates.
Every generated section must return evidence_refs containing only source IDs
already present in that section's source_blocks.
"""

SECTION_WORD_TARGETS = {
    "Personalized Cover": 80,
    "Welcome to Your Blueprint": 380,
    "Birth Chart Snapshot": 550,
    "Your Story Begins Here": 470,
    "Your Core Identity — Sun": 640,
    "Your Emotional World — Moon": 640,
    "How the World Meets You — Rising": 550,
    "Your Big Three": 640,
    "Your Houses / Life Areas": 850,
    "Your Inner Wiring": 640,
    "Your Relationship Blueprint": 640,
    "Your Career & Purpose Blueprint": 640,
    "Your Growth Blueprint": 550,
    "Alignment & Action": 510,
    "Personalized Action Plan": 720,
    "Your First / Next Brick": 380,
    "Your Blueprint Summary": 550,
    "Your Next Chapter / Continue": 380,
}

def _section_id(title: str) -> str:
    return title.lower().replace(" ", "_").replace("/", "_")

def _request_section(context, report_id, endpoint, token, title):
    body=json.dumps({
        "contract":CONTRACT,
        "report_id":report_id,
        "personalization_context":context,
        "section_name":title,
        "section_word_target":SECTION_WORD_TARGETS[title],
    }).encode("utf-8")
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]=f"Bearer {token}"
    req=Request(endpoint,data=body,headers=headers,method="POST")
    with urlopen(req,timeout=300) as resp:
        result=json.loads(resp.read().decode("utf-8"))
    if not isinstance(result,dict) or "content" not in result:
        raise RuntimeError(f"AI endpoint returned an invalid section: {title}")
    return result

def compose_report_with_ai(context: dict, report_id: str, endpoint: str, token_env: str="ARCHITECT_AI_TOKEN") -> dict:
    token=os.environ.get(token_env,"")
    if not endpoint:
        raise RuntimeError("AI endpoint is required.")
    generated=[]
    for title in SECTION_ORDER:
        cfg=context.get("sections",{}).get(title,{"status":"REVIEW_REQUIRED","source_blocks":[]})
        if cfg.get("status")=="OMITTED_BY_MODE":
            generated.append({
                "section_id":_section_id(title),"title":title,
                "status":"OMITTED_BY_MODE","content":"","evidence_refs":[],
            })
            continue
        generated.append(_request_section(context,report_id,endpoint,token,title))
    return {
        "report_id":report_id,"schema_version":"blueprint_report_v1",
        "context_version":context["context_version"],"mode":context["mode"],
        "customer":context["customer"],"sections":generated,
        "qa":{"source_boundary":"LOCKED_TO_CONTEXT","new_astrology_added":False},
    }
