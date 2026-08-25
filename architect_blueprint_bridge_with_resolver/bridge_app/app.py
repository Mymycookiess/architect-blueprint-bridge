
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request as URLRequest, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel 
from fastapi.responses import FileResponse

APP_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = APP_ROOT.parent
ENGINE_ROOT = PACKAGE_ROOT / "blueprint_engine"

SHOPIFY_WEBHOOK_SECRET = os.getenv("SHOPIFY_WEBHOOK_SECRET", "")
BLUEPRINT_OUTPUT_ROOT = Path(os.getenv("BLUEPRINT_OUTPUT_ROOT", str(PACKAGE_ROOT / "production_runs")))
BLUEPRINT_PRODUCT_IDS = {
    x.strip() for x in os.getenv("BLUEPRINT_PRODUCT_IDS", "").split(",") if x.strip()
}
BLUEPRINT_PRODUCT_HANDLES = {
    x.strip().lower() for x in os.getenv("BLUEPRINT_PRODUCT_HANDLES", "").split(",") if x.strip()
}

# Optional resolver endpoint. It should accept JSON:
# {"birth_location":"Oakland, California, USA","birth_date":"1996-10-27","birth_time":"02:18"}
# and return {"latitude":37.8044,"longitude":-122.2712,"timezone_offset":-8}
LOCATION_RESOLVER_URL = os.getenv("LOCATION_RESOLVER_URL", "")
BLUEPRINT_WRITER = os.getenv("BLUEPRINT_WRITER", "deterministic")
ARCHITECT_AI_ENDPOINT = os.getenv("ARCHITECT_AI_ENDPOINT", "")
ARCHITECT_AI_TOKEN = os.getenv("ARCHITECT_AI_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")


class LocationResolveRequest(BaseModel):
    birth_location: str
    birth_date: str
    birth_time: str | None = None


US_STATE_NAMES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut", "DE": "delaware",
    "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
    "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska",
    "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey",
    "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon",
    "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina",
    "SD": "south dakota", "TN": "tennessee", "TX": "texas", "UT": "utah",
    "VT": "vermont", "VA": "virginia", "WA": "washington",
    "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia",
}


def _normalize_tokens(value: str) -> set[str]:
    clean = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    tokens = {t for t in clean.split() if t}
    for token in list(tokens):
        upper = token.upper()
        if upper in US_STATE_NAMES:
            tokens.update(US_STATE_NAMES[upper].split())
    return tokens


def _geocode_birth_location(location: str) -> dict:
    # Open-Meteo geocoding is keyless. Search the locality name, then score
    # returned candidates against the full customer-entered location.
    locality = location.split(",", 1)[0].strip() or location.strip()
    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={quote(locality)}&count=10&language=en&format=json"
    )
    req = URLRequest(url, headers={"User-Agent": "ArchitectBlueprintBridge/1.0"})
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    results = payload.get("results") or []
    if not results:
        raise HTTPException(422, f"Birth location could not be resolved: {location}")

    wanted = _normalize_tokens(location)

    def score(item: dict) -> tuple[int, int]:
        text = " ".join(str(item.get(k) or "") for k in (
            "name", "admin1", "admin2", "admin3", "country", "country_code"
        ))
        got = _normalize_tokens(text)
        overlap = len(wanted & got)
        exact_name = int(str(item.get("name") or "").strip().lower() == locality.lower())
        return (exact_name * 100 + overlap, int(item.get("population") or 0))

    best = max(results, key=score)
    if best.get("latitude") is None or best.get("longitude") is None or not best.get("timezone"):
        raise HTTPException(422, "Resolved location is missing coordinates or timezone.")
    return best


def _historical_utc_offset_hours(tz_name: str, birth_date: str, birth_time: str | None) -> float:
    try:
        date_obj = datetime.strptime(birth_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(422, "birth_date must use YYYY-MM-DD.") from exc

    if birth_time:
        try:
            time_obj = datetime.strptime(birth_time, "%H:%M").time()
        except ValueError as exc:
            raise HTTPException(422, "birth_time must use 24-hour HH:MM.") from exc
    else:
        # PARTIAL/unknown-time mode: noon avoids guessing a birth clock time while
        # giving a deterministic timezone offset for the date.
        time_obj = time(12, 0)

    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(422, f"Timezone database could not resolve {tz_name}.") from exc

    naive = datetime.combine(date_obj, time_obj)
    aware0 = naive.replace(tzinfo=tz, fold=0)
    aware1 = naive.replace(tzinfo=tz, fold=1)
    off0 = aware0.utcoffset()
    off1 = aware1.utcoffset()

    if off0 is None:
        raise HTTPException(422, "Could not determine UTC offset.")

    # For a known birth time, refuse to guess during the repeated fall-back hour.
    if birth_time and off1 is not None and off0 != off1:
        raise HTTPException(422, "Birth time is ambiguous because of a daylight-saving transition; manual review is required.")

    # Detect nonexistent spring-forward local times by UTC round-trip.
    if birth_time:
        roundtrip = aware0.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
        if roundtrip != naive:
            raise HTTPException(422, "Birth time does not exist locally because of a daylight-saving transition; manual review is required.")

    return off0.total_seconds() / 3600


app = FastAPI(title="Architect Blueprint Shopify Bridge", version="1.1.0")


@app.get("/")
def root():
    return {"ok": True, "service": "architect-blueprint-shopify-bridge"}


@app.post("/resolve-location")
def resolve_location_endpoint(payload: LocationResolveRequest):
    location = payload.birth_location.strip()
    if not location:
        raise HTTPException(422, "birth_location is required.")

    place = _geocode_birth_location(location)
    offset = _historical_utc_offset_hours(
        str(place["timezone"]), payload.birth_date, payload.birth_time
    )
    return {
        "latitude": float(place["latitude"]),
        "longitude": float(place["longitude"]),
        "timezone_offset": offset,
        "timezone": place["timezone"],
        "resolved_name": place.get("name"),
        "resolved_admin1": place.get("admin1"),
        "resolved_country": place.get("country"),
    }


def verify_shopify_hmac(raw_body: bytes, supplied: str | None) -> None:
    if not SHOPIFY_WEBHOOK_SECRET:
        raise HTTPException(500, "SHOPIFY_WEBHOOK_SECRET is not configured.")
    digest = hmac.new(
        SHOPIFY_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    if not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(401, "Invalid Shopify webhook signature.")


def safe_slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return value[:100] or "order"


def props_to_dict(properties: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in properties or []:
        if isinstance(p, dict):
            key = p.get("name") or p.get("key")
            value = p.get("value")
            if key:
                out[str(key)] = "" if value is None else str(value)
    return out


def is_blueprint_line_item(item: dict) -> bool:
    props = props_to_dict(item.get("properties"))
    if props.get("_Architect Product", "").lower() == "true":
        return True

    product_id = str(item.get("product_id") or "")
    if BLUEPRINT_PRODUCT_IDS and product_id in BLUEPRINT_PRODUCT_IDS:
        return True

    handle = str(item.get("handle") or item.get("product_handle") or "").lower()
    if BLUEPRINT_PRODUCT_HANDLES and handle in BLUEPRINT_PRODUCT_HANDLES:
        return True

    return False


def extract_intake(order: dict, item: dict) -> dict:
    props = props_to_dict(item.get("properties"))
    status = props.get("Birth Time Status", "").strip().upper()
    birth_time = props.get("Birth Time", "").strip() or None

    errors = []
    if not props.get("Blueprint Full Name"):
        errors.append("Missing Blueprint Full Name")
    if not props.get("Birth Date"):
        errors.append("Missing Birth Date")
    if status not in {"KNOWN", "UNKNOWN"}:
        errors.append("Birth Time Status must be KNOWN or UNKNOWN")
    if status == "KNOWN" and not birth_time:
        errors.append("Known birth time requires Birth Time")
    if not props.get("Birth Location"):
        errors.append("Missing Birth Location")
    if props.get("Birth Details Confirmed") != "YES":
        errors.append("Birth Details Confirmed is missing")

    if errors:
        raise ValueError("; ".join(errors))

    return {
        "customer_name": props["Blueprint Full Name"].strip(),
        "birth_date": props["Birth Date"].strip(),
        "birth_time": birth_time if status == "KNOWN" else None,
        "birth_time_status": status,
        "birth_location": props["Birth Location"].strip(),
        "latitude": None,
        "longitude": None,
        "timezone_offset": None,
        "_shopify": {
            "order_id": order.get("id"),
            "order_name": order.get("name"),
            "email": order.get("email"),
            "line_item_id": item.get("id"),
            "product_id": item.get("product_id"),
            "variant_id": item.get("variant_id"),
        }
    }


def resolve_location(intake: dict) -> dict:
    """Optional external resolver hook.

    The Blueprint Engine requires coordinates and UTC offset for live astrology
    calculations. This bridge intentionally does not guess them.

    If LOCATION_RESOLVER_URL is blank, the run is parked in WAITING_FOR_LOCATION_RESOLUTION.
    """
    if not LOCATION_RESOLVER_URL:
        return intake

    from urllib.request import Request, urlopen

    body = json.dumps({
        "birth_location": intake["birth_location"],
        "birth_date": intake["birth_date"],
        "birth_time": intake.get("birth_time"),
    }).encode("utf-8")

    req = Request(
        LOCATION_RESOLVER_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        resolved = json.loads(resp.read().decode("utf-8"))

    intake["latitude"] = resolved.get("latitude")
    intake["longitude"] = resolved.get("longitude")
    intake["timezone_offset"] = resolved.get("timezone_offset")
    return intake


def write_status(run_dir: Path, status: str, detail: str = "") -> None:
    payload = {
        "status": status,
        "detail": detail,
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    (run_dir / "frontdoor_status.json").write_text(json.dumps(payload, indent=2))
    print(f"BLUEPRINT_STATUS run={run_dir.name} status={status} detail={detail}", flush=True)


def _keep_render_awake(stop_event: threading.Event) -> None:
    """Keep a long Blueprint job alive on Render's free web-service tier."""
    service_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not service_url:
        return

    health_url = f"{service_url}/health"
    while not stop_event.wait(240):
        try:
            req = URLRequest(
                health_url,
                headers={"User-Agent": "ArchitectBlueprintJobKeepalive/1.0"},
            )
            with urlopen(req, timeout=20) as response:
                print(
                    f"BLUEPRINT_KEEPALIVE status={response.status}",
                    flush=True,
                )
        except Exception as exc:
            # A missed heartbeat should be visible, but it must not abort the job.
            print(f"BLUEPRINT_KEEPALIVE_ERROR detail={exc}", flush=True)

def run_blueprint(order: dict, item: dict, webhook_id: str) -> None:
    order_key = safe_slug(str(order.get("name") or order.get("id") or webhook_id))
    line_key = safe_slug(str(item.get("id") or item.get("variant_id") or "item"))
    run_dir = BLUEPRINT_OUTPUT_ROOT / f"{order_key}_{line_key}"
    run_dir.mkdir(parents=True, exist_ok=True)

    if (run_dir / "frontdoor_completed.flag").exists():
        return

    keepalive_stop = threading.Event()
    keepalive_thread = threading.Thread(
        target=_keep_render_awake,
        args=(keepalive_stop,),
        name=f"blueprint-keepalive-{run_dir.name}",
        daemon=True,
    )
    keepalive_thread.start()

    try:
        intake = extract_intake(order, item)
        intake = resolve_location(intake)
        (run_dir / "shopify_order_snapshot.json").write_text(
            json.dumps(order, indent=2)
        )
        (run_dir / "customer_intake.json").write_text(
            json.dumps(intake, indent=2)
        )

        if (
            intake.get("latitude") is None
            or intake.get("longitude") is None
            or intake.get("timezone_offset") is None
        ):
            write_status(
                run_dir,
                "WAITING_FOR_LOCATION_RESOLUTION",
                "Birth location was captured, but latitude/longitude/timezone are not resolved yet.",
            )
            return

        write_status(run_dir, "RUNNING_BLUEPRINT_ENGINE")

        cmd = [
            sys.executable,
            str(ENGINE_ROOT / "pipeline.py"),
            "--intake",
            str(run_dir / "customer_intake.json"),
            "--live-provider",
            "--out-dir",
            str(run_dir / "engine_output"),
        ]

        if BLUEPRINT_WRITER == "ai-http":
            if not ARCHITECT_AI_ENDPOINT:
                write_status(
                    run_dir,
                    "FRONTDOOR_ERROR",
                    "BLUEPRINT_WRITER is ai-http but ARCHITECT_AI_ENDPOINT is not configured.",
                )
                return

            cmd.extend(
                [
                    "--writer",
                    "ai-http",
                    "--ai-endpoint",
                    ARCHITECT_AI_ENDPOINT,
                ]
            )

        completed = subprocess.run(
            cmd,
            cwd=str(ENGINE_ROOT),
            capture_output=True,
            text=True,
            timeout=3600,
        )

        (run_dir / "engine_stdout.txt").write_text(completed.stdout or "")
        (run_dir / "engine_stderr.txt").write_text(completed.stderr or "")

        if completed.returncode != 0:
            write_status(
                run_dir,
                "ENGINE_ERROR",
                completed.stderr[-2000:],
            )
            return

        manifest_path = run_dir / "engine_output" / "00_manifest.json"
        manifest = json.loads(manifest_path.read_text())

        if manifest.get("status") == "PASS":
            write_status(run_dir, "BLUEPRINT_READY")
            (run_dir / "frontdoor_completed.flag").write_text("PASS\n")
        else:
            write_status(
                run_dir,
                "REVIEW_REQUIRED",
                "Engine completed but final manifest did not PASS.",
            )

    except Exception as exc:
        write_status(run_dir, "FRONTDOOR_ERROR", str(exc))
    finally:
        keepalive_stop.set()
        keepalive_thread.join(timeout=1)


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "architect-blueprint-shopify-bridge",
        "engine_present": (ENGINE_ROOT / "pipeline.py").exists(),
    }


@app.post("/webhooks/shopify/orders-paid")
async def orders_paid(
    request: Request,
    background_tasks: BackgroundTasks,
    x_shopify_hmac_sha256: str | None = Header(default=None),
    x_shopify_webhook_id: str | None = Header(default=None),
):
    raw = await request.body()
    verify_shopify_hmac(raw, x_shopify_hmac_sha256)

    try:
        order = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Invalid JSON payload.")

    webhook_id = x_shopify_webhook_id or str(order.get("id") or "unknown")
    items = [item for item in order.get("line_items", []) if is_blueprint_line_item(item)]

    if not items:
        return {"accepted": True, "blueprint_items": 0, "message": "Paid order contained no Blueprint product."}

    for item in items:
        background_tasks.add_task(run_blueprint, order, item, webhook_id)

    # Important: return quickly so Shopify receives 2xx while processing continues.
    return {"accepted": True, "blueprint_items": len(items)}

def verify_inspect_key(x_inspect_key: str | None) -> None:
    expected = os.getenv("INSPECT_KEY", "")
    if not expected or not hmac.compare_digest(x_inspect_key or "", expected):
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/runs/{run_id}/inspect")
def inspect_run(
    run_id: str,
    x_inspect_key: str | None = Header(default=None),
):
    verify_inspect_key(x_inspect_key)

    run_dir = BLUEPRINT_OUTPUT_ROOT / run_id
    engine_dir = run_dir / "engine_output"

    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    files = []
    if engine_dir.exists():
        files = sorted(
            str(p.relative_to(run_dir))
            for p in engine_dir.rglob("*")
            if p.is_file()
        )

    manifest = None
    qa = None

    manifest_path = engine_dir / "00_manifest.json"
    qa_path = engine_dir / "06_qa.json"

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    if qa_path.exists():
        qa = json.loads(qa_path.read_text())

    return {
        "run_id": run_id,
        "files": files,
        "manifest": manifest,
        "qa": qa,
    }


@app.get("/runs/{run_id}/pdf")
def get_run_pdf(
    run_id: str,
    x_inspect_key: str | None = Header(default=None),
):
    verify_inspect_key(x_inspect_key)

    pdf_path = (
        BLUEPRINT_OUTPUT_ROOT
        / run_id
        / "engine_output"
        / "05_architect_blueprint.pdf"
    )

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="architect_blueprint.pdf",
    )
class AIWriterRequest(BaseModel):
    contract: str
    report_id: str
    personalization_context: dict
    section_name: str | None = None
    section_word_target: int | None = None
    section_draft: dict | None = None


AIWriterRequest.model_rebuild()


def _call_openai(openai_payload: dict, output_kind: str) -> dict:
    body = json.dumps(openai_payload).encode("utf-8")
    req = URLRequest(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {exc}")
    output_text = result.get("output_text")
    if not output_text:
        for item in result.get("output", []):
            if item.get("type") != "message":
                continue
            for content_item in item.get("content", []):
                if content_item.get("type") == "output_text":
                    output_text = content_item.get("text")
                    break
            if output_text:
                break
    if not output_text:
        raise HTTPException(status_code=502, detail=f"OpenAI returned no {output_kind} text.")
    try:
        return json.loads(output_text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail=f"OpenAI returned invalid {output_kind} JSON.")



@app.post("/ai-writer")
def ai_writer(
    payload: AIWriterRequest,
    authorization: str | None = Header(default=None),
    x_architect_token: str | None = Header(default=None),
):
    expected = ARCHITECT_AI_TOKEN

    if not expected:
        raise HTTPException(
            status_code=500,
            detail="ARCHITECT_AI_TOKEN is not configured.",
        )

    supplied = x_architect_token or ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:]

    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured.",
        )

    context = payload.personalization_context

    sections = context.get("sections", {})

    if payload.section_name:
        section_name = payload.section_name
        section_data = sections.get(section_name)
        if not isinstance(section_data, dict):
            raise HTTPException(status_code=422, detail="Unknown Blueprint section.")
        allowed_section_refs = [
            str(block.get("source_content_id"))
            for block in section_data.get("source_blocks", [])
            if block.get("source_content_id")
        ]
        target = max(80, min(int(payload.section_word_target or 500), 1200))
        section_schema = {
            "type": "object",
            "properties": {
                "section_id": {"type": "string"},
                "title": {"type": "string"},
                "status": {"type": "string"},
                "content": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["section_id", "title", "status", "content", "evidence_refs"],
            "additionalProperties": False,
        }
        revision_instruction = ""
        if payload.section_draft:
            revision_instruction = f"""
Revise and expand the supplied existing_section into a complete replacement.
Preserve its grounded ideas, remove repetition, and reach the requested word
target. Return the entire revised section, not an addendum.
"""
        section_payload = {
            "model": OPENAI_MODEL,
            "max_output_tokens": 5000,
            "instructions": f"""
{payload.contract}
Write only the Blueprint section named: {section_name}
Target approximately {target} words and stay within 15 percent of that target.
{revision_instruction}
Use only this section's supplied data and the verified chart facts in the input.
Do not use outside astrology knowledge or invent facts. Develop polished,
substantive prose through grounded explanation, integration, reflection,
practical application, and examples faithful to the supplied context.
Avoid repetitive filler and generic horoscope language.
For Personalized Action Plan include exactly 3 strengths, 3 supporting habits,
3 patterns to watch, 1 challenge, 1 encouraging message, and 1 Next Brick.
Return one section object. Use only allowed_evidence_refs in evidence_refs.
""",
            "input": json.dumps({
                "report_id": payload.report_id,
                "section_name": section_name,
                "section_context": section_data,
                "chart_facts": context.get("chart_facts", {}),
                "customer": context.get("customer", ""),
                "mode": context.get("mode", ""),
                "allowed_evidence_refs": allowed_section_refs,
                "existing_section": payload.section_draft,
            }),
            "text": {"format": {
                "type": "json_schema", "name": "architect_blueprint_section",
                "strict": True, "schema": section_schema,
            }},
            "store": False,
        }
        section = _call_openai(section_payload, "section")
        section["title"] = section_name
        section["section_id"] = section_name.lower().replace(" ", "_").replace("/", "_")
        if not set(section.get("evidence_refs", [])).issubset(set(allowed_section_refs)):
            raise HTTPException(
                status_code=422,
                detail=f"Source-boundary violation in section: {section_name}",
            )
        return section

    mode = str(context.get("mode") or "FULL").upper()
    if mode == "PARTIAL":
        total_word_target = "7,200 to 8,200 words"
    else:
        total_word_target = "9,200 to 10,200 words"

    allowed_refs = {}
    for section_name, section_data in sections.items():
        allowed_refs[section_name] = [
            str(block.get("source_content_id"))
            for block in section_data.get("source_blocks", [])
            if block.get("source_content_id")
        ]

    instructions = f"""
{payload.contract}

You are producing THE ARCHITECT BLUEPRINT.

Use ONLY the supplied personalization_context.

Do not use outside astrology knowledge.
Do not invent placements, houses, aspects, traits, events, diagnoses,
predictions, destiny claims, or guaranteed outcomes.

Every statement must be grounded in the supplied context.

For each section:
- preserve the supplied section purpose
- personalize the writing using only selected source blocks and chart facts
- use only evidence_refs that belong to that section
- never cite a source_content_id from another section

LENGTH REQUIREMENTS:
- The complete report must contain {total_word_target} across section content.
- Treat the length requirement as mandatory, not aspirational.
- Develop each included section into substantive long-form prose; do not merely
  summarize its source blocks.
- Expand only through explanation, integration, reflection, practical
  application, and grounded examples that remain faithful to the supplied
  context. Do not add new astrology facts.
- Keep omitted sections omitted and redistribute their word allowance among the
  included sections.
- Before returning the report, silently estimate the total word count and expand
  underdeveloped included sections until the target range is met.

For a FULL report, use these approximate section word budgets:
- Personalized Cover: 80
- Welcome to Your Blueprint: 350
- Birth Chart Snapshot: 550
- Your Story Begins Here: 450
- Your Core Identity â Sun: 650
- Your Emotional World â Moon: 650
- How the World Meets You â Rising: 550
- Your Big Three: 650
- Your Houses / Life Areas: 900
- Your Inner Wiring: 650
- Your Relationship Blueprint: 650
- Your Career & Purpose Blueprint: 650
- Your Growth Blueprint: 550
- Alignment & Action: 500
- Personalized Action Plan: 750
- Your First / Next Brick: 350
- Your Blueprint Summary: 550
- Your Next Chapter / Continue: 350

The Personalized Action Plan must contain exactly:
- 3 strengths
- 3 supporting habits
- 3 patterns to watch
- 1 challenge
- 1 encouraging message
- 1 Next Brick

The writing should feel reflective, premium, calm, specific, and useful.
Avoid repetitive filler and generic horoscope language.

Return only the requested structured report object.
"""

    report_schema = {
        "type": "object",
        "properties": {
            "report_id": {
                "type": "string"
            },
            "schema_version": {
                "type": "string"
            },
            "context_version": {
                "type": "string"
            },
            "mode": {
                "type": "string"
            },
            "customer": {
                "type": "string"
            },
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section_id": {
                            "type": "string"
                        },
                        "title": {
                            "type": "string"
                        },
                        "status": {
                            "type": "string"
                        },
                        "content": {
                            "type": "string"
                        },
                        "evidence_refs": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            }
                        }
                    },
                    "required": [
                        "section_id",
                        "title",
                        "status",
                        "content",
                        "evidence_refs"
                    ],
                    "additionalProperties": False
                }
            },
            "qa": {
                "type": "object",
                "properties": {
                    "source_boundary": {
                        "type": "string"
                    },
                    "new_astrology_added": {
                        "type": "boolean"
                    }
                },
                "required": [
                    "source_boundary",
                    "new_astrology_added"
                ],
                "additionalProperties": False
            }
        },
        "required": [
            "report_id",
            "schema_version",
            "context_version",
            "mode",
            "customer",
            "sections",
            "qa"
        ],
        "additionalProperties": False
    }

    openai_payload = {
        "model": OPENAI_MODEL,
        "max_output_tokens": 30000,
        "instructions": instructions,
        "input": json.dumps(
            {
                "report_id": payload.report_id,
                "personalization_context": context,
                "allowed_evidence_refs": allowed_refs,
            }
        ),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "architect_blueprint_report",
                "strict": True,
                "schema": report_schema,
            }
        },
        "store": False,
    }

    body = json.dumps(openai_payload).encode("utf-8")

    req = URLRequest(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI request failed: {exc}",
        )

    output_text = result.get("output_text")

    if not output_text:
        for item in result.get("output", []):
            if item.get("type") != "message":
                continue

            for content_item in item.get("content", []):
                if content_item.get("type") == "output_text":
                    output_text = content_item.get("text")
                    break

            if output_text:
                break

    if not output_text:
        raise HTTPException(
            status_code=502,
            detail="OpenAI returned no report text.",
        )

    try:
        report = json.loads(output_text)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail="OpenAI returned invalid report JSON.",
        )

    for section in report.get("sections", []):
        title = section.get("title", "")
        refs = section.get("evidence_refs", [])

        permitted = set(allowed_refs.get(title, []))

        if not set(refs).issubset(permitted):
            raise HTTPException(
                status_code=422,
                detail=f"Source-boundary violation in section: {title}",
            )

    report["report_id"] = payload.report_id
    report["context_version"] = context.get("context_version", "")
    report["mode"] = context.get("mode", "")
    report["customer"] = context.get("customer", "")
    report["qa"] = {
        "source_boundary": "LOCKED_TO_CONTEXT",
        "new_astrology_added": False,
    }

    return report
