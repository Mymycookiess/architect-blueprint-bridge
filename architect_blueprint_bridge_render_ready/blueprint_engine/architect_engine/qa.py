
from __future__ import annotations
import re

PROHIBITED = [
"Los Angeles","UTC-7","3.66°","5.86°",
"you will definitely","you are destined","guaranteed outcome"
]

def count_words(payload):
    return sum(len(re.findall(r"\b[\w’'-]+\b", s.get("content",""))) for s in payload["sections"])

def run_qa(chart, selector, context, report, config, rendered_pages=None):
    words=count_words(report)
    mode=report["mode"]
    r=config["report"]
    lo=r["mode_full_word_min"] if mode=="FULL" else r["mode_partial_word_min"]
    hi=r["mode_full_word_max"] if mode=="FULL" else r["mode_partial_word_max"]
    plo=r["mode_full_page_min"] if mode=="FULL" else r["mode_partial_page_min"]
    phi=r["mode_full_page_max"] if mode=="FULL" else r["mode_partial_page_max"]
    all_text="\n".join(s.get("content","") for s in report["sections"])
    issues=[]
    for bad in PROHIBITED:
        if bad.lower() in all_text.lower():
            issues.append(f"Prohibited/superseded content found: {bad}")
    if selector["status"]!="VALID": issues.append("Selector not VALID")
    if context["context_status"]!="VALID": issues.append("Context not VALID")
    if mode=="PARTIAL":
        if chart.get("availability",{}).get("rising") or chart.get("availability",{}).get("houses"):
            issues.append("PARTIAL mode incorrectly exposes rising/houses")
        for sec in report["sections"]:
            if sec["title"] in ("How the World Meets You — Rising","Your Houses / Life Areas") and sec["status"]!="OMITTED_BY_MODE":
                issues.append(f"PARTIAL mode section not omitted: {sec['title']}")
    trace_ids={x["source_content_id"] for x in context["source_trace"]}
    used_ids={ref for s in report["sections"] for ref in s.get("evidence_refs",[])}
    if not used_ids.issubset(trace_ids):
        issues.append("Report references untraced source IDs")
    page_status=None if rendered_pages is None else ("PASS" if plo<=rendered_pages<=phi else "REVIEW_REQUIRED")
    return {
        "status":"PASS" if not issues else "FIX",
        "issues":issues,
        "word_count":words,
        "word_target":{"min":lo,"max":hi,"status":"PASS" if lo<=words<=hi else "REVIEW_REQUIRED"},
        "page_target":{"min":plo,"max":phi,"actual":rendered_pages,"status":page_status},
        "selector_status":selector["status"],
        "context_status":context["context_status"],
        "source_boundary":"PASS" if used_ids.issubset(trace_ids) else "FIX"
    }
