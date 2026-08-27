
from __future__ import annotations
from collections import defaultdict
from .synthesis import build_synthesis_anchors

def build_context(chart: dict, selector: dict, context_id: str) -> dict:
    grouped=defaultdict(list)
    for s in selector["selected_sources"]:
        grouped[s["section_name"]].append({
            "source_content_id":s["source_content_id"],
            "master_page":s["master_page"],
            "priority_score":s["source_priority_score"],
            "source_text":s["source_text"]
        })
    sections={}
    for sec,state in selector["section_states"].items():
        sections[sec]={
            "status":state,
            "allowed_to_generate":state=="VALID",
            "source_blocks":grouped.get(sec,[])
        }
    return {
        "context_id":context_id,
        "context_version":"personalization_context_v1",
        "context_status":"VALID" if selector["status"]=="VALID" else "REVIEW_REQUIRED",
        "mode":chart["calculation"]["mode"],
        "customer":chart["customer"],
        "chart_facts":{
            "placements":chart.get("placements",{}),
            "angles":chart.get("angles",{}),
            "houses":chart.get("houses",[]),
            "aspects":chart.get("aspects",[]),
            "availability":chart.get("availability",{}),
            "lookup_keys":chart.get("lookup_keys",[]),
            "synthesis_anchors":build_synthesis_anchors(chart)
        },
        "sections":sections,
        "source_trace":[
            {k:s[k] for k in ("section_name","source_content_id","master_page","selection_reason","source_priority_score","trace_status")}
            for s in selector["selected_sources"]
        ],
        "exclusions":[
            "raw_provider_payloads",
            "unselected_library_content",
            "unsupported_predictions",
            "diagnostic_or_deterministic_language",
            "unverified_rising_or_houses_in_partial_mode"
        ]
    }
