
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

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

app = FastAPI(title="Architect Blueprint Shopify Bridge", version="1.0.0")


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
    (run_dir / "frontdoor_status.json").write_text(json.dumps({
        "status": status,
        "detail": detail,
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }, indent=2))


def run_blueprint(order: dict, item: dict, webhook_id: str) -> None:
    order_key = safe_slug(str(order.get("name") or order.get("id") or webhook_id))
    line_key = safe_slug(str(item.get("id") or item.get("variant_id") or "item"))
    run_dir = BLUEPRINT_OUTPUT_ROOT / f"{order_key}_{line_key}"
    run_dir.mkdir(parents=True, exist_ok=True)

    if (run_dir / "frontdoor_completed.flag").exists():
        return

    try:
        intake = extract_intake(order, item)
        intake = resolve_location(intake)
        (run_dir / "shopify_order_snapshot.json").write_text(json.dumps(order, indent=2))
        (run_dir / "customer_intake.json").write_text(json.dumps(intake, indent=2))

        if (
            intake.get("latitude") is None
            or intake.get("longitude") is None
            or intake.get("timezone_offset") is None
        ):
            write_status(
                run_dir,
                "WAITING_FOR_LOCATION_RESOLUTION",
                "Birth location was captured, but latitude/longitude/timezone are not resolved yet."
            )
            return

        write_status(run_dir, "RUNNING_BLUEPRINT_ENGINE")

        cmd = [
            sys.executable,
            str(ENGINE_ROOT / "pipeline.py"),
            "--intake", str(run_dir / "customer_intake.json"),
            "--live-provider",
            "--out-dir", str(run_dir / "engine_output"),
        ]
        completed = subprocess.run(cmd, cwd=str(ENGINE_ROOT), capture_output=True, text=True, timeout=600)

        (run_dir / "engine_stdout.txt").write_text(completed.stdout or "")
        (run_dir / "engine_stderr.txt").write_text(completed.stderr or "")

        if completed.returncode != 0:
            write_status(run_dir, "ENGINE_ERROR", completed.stderr[-2000:])
            return

        manifest_path = run_dir / "engine_output" / "00_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("status") == "PASS":
            write_status(run_dir, "BLUEPRINT_READY")
            (run_dir / "frontdoor_completed.flag").write_text("PASS\n")
        else:
            write_status(run_dir, "REVIEW_REQUIRED", "Engine completed but final manifest did not PASS.")

    except Exception as exc:
        write_status(run_dir, "FRONTDOOR_ERROR", str(exc))


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
