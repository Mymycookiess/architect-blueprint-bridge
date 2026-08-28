
from __future__ import annotations
import re
from .content_rules import report_content_rule_issues
from .synthesis import report_synthesis_rule_issues
from .confidence_rules import report_confidence_rule_issues
from .emotional_rules import report_emotional_rule_issues
from .repetition_rules import report_repetition_rule_issues

PROHIBITED = [
"Los Angeles","UTC-7","3.66°","5.86°",
"you will definitely","you are destined","guaranteed outcome"
]

def count_words(payload):
    return sum(len(re.findall(r"\b[\w’'-]+\b", s.get("content",""))) for s in payload["sections"])

def customer_lock_issues(report, context):
    issues=[]
    sections={s.get("title"):s.get("content","") for s in report.get("sections",[])}
    welcome=sections.get("Welcome to Your Blueprint","")
    quote="The greatest project you will ever build is yourself."
    if welcome.count(quote)>1:
        issues.append("Welcome page repeats the signature quote")
    all_text="\n".join(sections.values())
    if re.search(r"(?i)\bin\s+(?:this|the|your|[a-z &-]+),?\s+[A-Z][a-z]+\s+(?:conjunction|sextile|square|trine|opposition)\s+[A-Z][a-z]+\s+reinforces\s+(?:this pattern|the connection)",all_text):
        issues.append("Formulaic aspect reinforcement phrasing found")
    aspects=context.get("chart_facts",{}).get("aspects",[]) or []
    for title in ("Your Inner Wiring","Your Blueprint Summary"):
        content=sections.get(title,"")
        for aspect in aspects:
            a=aspect.get("body_a"); b=aspect.get("body_b"); kind=aspect.get("type")
            if not a or not b or not kind:
                continue
            paragraphs=[p for p in content.split("\n\n") if a.lower() in p.lower() and b.lower() in p.lower() and kind.lower() in p.lower()]
            if len(paragraphs)>1:
                issues.append(f"{title} repeats {a} {kind} {b}")
    return issues


def proofreading_issues(report):
    issues=[]
    known_errors=(
        "themes appears", "others offers", "these five areas helps",
        "goals that allows", "reveals what need development",
    )
    for section in report.get("sections", []):
        title=section.get("title", "")
        content=section.get("content", "")
        for error in known_errors:
            pattern=re.escape(error).replace(r"\ ", r"\s+")
            if re.search(pattern, content, re.I):
                issues.append(f"Copyediting error in {title}: {error}")
        if re.search(r"\s+[,.;:!?]", content):
            issues.append(f"Space before punctuation in {title}")
        lines=content.splitlines()
        if lines and lines[0].strip().casefold() == title.strip().casefold():
            issues.append(f"Duplicate opening chapter heading in {title}")
        for previous, current in zip(lines, lines[1:]):
            if current.strip() and current.strip() == current.strip().upper() and current.strip().casefold() == previous.strip().casefold():
                issues.append(f"Adjacent duplicate heading in {title}: {current.strip()}")
    return issues

def run_qa(chart, selector, context, report, config, rendered_pages=None, render_diagnostics=None):
    words=count_words(report)
    mode=report["mode"]
    r=config["report"]
    lo=r["mode_full_word_min"] if mode=="FULL" else r["mode_partial_word_min"]
    hi=r["mode_full_word_max"] if mode=="FULL" else r["mode_partial_word_max"]
    hi += 100
    plo=r["mode_full_page_min"] if mode=="FULL" else r["mode_partial_page_min"]
    phi=r["mode_full_page_max"] if mode=="FULL" else r["mode_partial_page_max"]
    all_text="\n".join(s.get("content","") for s in report["sections"])
    issues=[]
    for bad in PROHIBITED:
        if bad.lower() in all_text.lower():
            issues.append(f"Prohibited/superseded content found: {bad}")
    issues.extend(report_content_rule_issues(report))
    issues.extend(report_synthesis_rule_issues(context,report))
    issues.extend(report_confidence_rule_issues(report))
    issues.extend(report_emotional_rule_issues(report))
    issues.extend(report_repetition_rule_issues(report))
    issues.extend(customer_lock_issues(report,context))
    issues.extend(proofreading_issues(report))
    if render_diagnostics:
        for key, label in (
            ("blank_pages", "Accidental blank pages"),
            ("sparse_pages", "Accidental sparse pages"),
            ("orphaned_headings", "Orphaned headings"),
            ("unresolved_placeholders", "Unresolved placeholders"),
            ("internal_terms", "Customer-facing internal terms"),
            ("raw_orb_values", "Raw aspect orb values in customer prose"),
            ("markdown_bold_markers", "Unconverted Markdown bold markers"),
            ("markdown_emphasis_markers", "Unconverted Markdown emphasis markers"),
        ):
            if render_diagnostics.get(key):
                issues.append(f"{label}: {render_diagnostics[key]}")
    if selector["status"]!="VALID": issues.append("Selector not VALID")
    if context["context_status"]!="VALID": issues.append("Context not VALID")
    if mode=="FULL":
        if not chart.get("availability",{}).get("rising"):
            issues.append("FULL mode missing Ascendant")
        if not chart.get("availability",{}).get("houses"):
            issues.append("FULL mode missing or invalid houses")
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
        "source_boundary":"PASS" if used_ids.issubset(trace_ids) else "FIX",
        "visual_qa":render_diagnostics or {}
    }
