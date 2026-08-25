
from __future__ import annotations
import json, os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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

def _extract_section(result: object, title: str) -> dict:
    """Accept both the new section response and the legacy full-report response."""
    if not isinstance(result, dict):
        raise RuntimeError(f"AI endpoint returned an invalid section: {title}")

    section = result if "content" in result else None
    if section is None:
        sections = result.get("sections")
        if isinstance(sections, list):
            expected_id = _section_id(title)
            section = next(
                (
                    item
                    for item in sections
                    if isinstance(item, dict)
                    and (
                        item.get("title") == title
                        or item.get("section_id") == expected_id
                    )
                ),
                None,
            )

    if not isinstance(section, dict) or not isinstance(section.get("content"), str):
        raise RuntimeError(f"AI endpoint returned an invalid section: {title}")

    section = dict(section)
    section["title"] = title
    section["section_id"] = _section_id(title)
    section.setdefault("status", "INCLUDED" if section["content"].strip() else "REVIEW_REQUIRED")
    section.setdefault("evidence_refs", [])
    return section

def _word_count(section: dict) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", section.get("content", "")))


def _request_section_once(context, report_id, endpoint, token, title, draft=None):
    body=json.dumps({
        "contract":CONTRACT,
        "report_id":report_id,
        "personalization_context":context,
        "section_name":title,
        "section_word_target":SECTION_WORD_TARGETS[title],
        "section_draft":draft,
    }).encode("utf-8")
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]=f"Bearer {token}"
    req=Request(endpoint,data=body,headers=headers,method="POST")
    with urlopen(req,timeout=300) as resp:
        result=json.loads(resp.read().decode("utf-8"))
    return _extract_section(result, title)


def _request_section(context, report_id, endpoint, token, title):
    section = _request_section_once(context, report_id, endpoint, token, title)
    target = SECTION_WORD_TARGETS[title]
    if _word_count(section) < int(target * 0.85):
        expanded = _request_section_once(
            context, report_id, endpoint, token, title, draft=section,
        )
        if _word_count(expanded) > _word_count(section):
            section = expanded
    return section

def compose_report_with_ai(context: dict, report_id: str, endpoint: str, token_env: str="ARCHITECT_AI_TOKEN") -> dict:
    token=os.environ.get(token_env,"")
    if not endpoint:
        raise RuntimeError("AI endpoint is required.")
    generated_by_title={}
    pending=[]
    for title in SECTION_ORDER:
        cfg=context.get("sections",{}).get(title,{"status":"REVIEW_REQUIRED","source_blocks":[]})
        if cfg.get("status")=="OMITTED_BY_MODE":
            generated_by_title[title]={
                "section_id":_section_id(title),"title":title,
                "status":"OMITTED_BY_MODE","content":"","evidence_refs":[],
            }
            continue
        pending.append(title)

    # Two concurrent requests keep the production run comfortably inside the
    # bridge timeout while avoiding a burst of API traffic.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={
            pool.submit(_request_section,context,report_id,endpoint,token,title):title
            for title in pending
        }
        for future in as_completed(futures):
            title=futures[future]
            generated_by_title[title]=future.result()

    generated=[generated_by_title[title] for title in SECTION_ORDER]
    return {
        "report_id":report_id,"schema_version":"blueprint_report_v1",
        "context_version":context["context_version"],"mode":context["mode"],
        "customer":context["customer"],"sections":generated,
        "qa":{"source_boundary":"LOCKED_TO_CONTEXT","new_astrology_added":False},
    }
