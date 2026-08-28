from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


DELIVERY_FILENAME = "delivery.json"
PDF_RELATIVE_PATH = Path("engine_output") / "05_architect_blueprint.pdf"
MANIFEST_RELATIVE_PATH = Path("engine_output") / "00_manifest.json"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_lock(run_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(run_id, threading.Lock())


def _object_key(run_id: str) -> str:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:32]
    return f"blueprints/{digest}.pdf"


def _delivery_id(run_id: str) -> str:
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]


def _load_state(run_dir: Path) -> dict:
    path = run_dir / DELIVERY_FILENAME
    if path.exists():
        return json.loads(path.read_text())
    now = _now()
    return {
        "run_id": run_dir.name,
        "status": "DELIVERY_PENDING",
        "object_key": _object_key(run_dir.name),
        "provider_message_id": None,
        "attempt_count": 0,
        "created_at": now,
        "updated_at": now,
        "uploaded_at": None,
        "delivered_at": None,
        "error_at": None,
        "sanitized_error_detail": None,
    }


def _save_state(run_dir: Path, state: dict) -> None:
    state["updated_at"] = _now()
    path = run_dir / DELIVERY_FILENAME
    temporary = run_dir / f".{DELIVERY_FILENAME}.tmp"
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(path)


def _configured_download_ttl() -> int:
    raw = os.getenv("BLUEPRINT_DOWNLOAD_TTL_SECONDS", "604800")
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise RuntimeError("BLUEPRINT_DOWNLOAD_TTL_SECONDS must be an integer") from exc
    if ttl < 60 or ttl > 604800:
        raise RuntimeError("BLUEPRINT_DOWNLOAD_TTL_SECONDS must be between 60 and 604800")
    return ttl


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _r2_client():
    import boto3

    account_id = _required_env("R2_ACCOUNT_ID")
    endpoint = os.getenv("R2_ENDPOINT_URL", "").strip()
    if not endpoint:
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=_required_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_required_env("R2_SECRET_ACCESS_KEY"),
    )


def _send_resend(email: str, download_url: str, idempotency_key: str) -> str | None:
    safe_download_url = html.escape(download_url, quote=True)
    payload = {
        "from": _required_env("BLUEPRINT_FROM_EMAIL"),
        "to": [email],
        "subject": "Your Architect Blueprint Is Ready",
        "html": (
            '<div style="font-family:Arial,sans-serif;color:#26231f;max-width:600px;margin:auto;">'
            '<h1 style="font-size:26px;font-weight:500;">Your Blueprint Is Ready</h1>'
            '<p style="font-size:16px;line-height:1.6;">Your personalized Architect Blueprint is complete.</p>'
            f'<p style="margin:30px 0;"><a href="{safe_download_url}" '
            'style="background:#26231f;color:#ffffff;text-decoration:none;padding:14px 22px;'
            'border-radius:3px;display:inline-block;">Download Your Blueprint</a></p>'
            '<p style="font-size:13px;line-height:1.5;color:#6b665f;">'
            'This private download link is available for a limited time.</p></div>'
        ),
    }
    request = Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f'Bearer {_required_env("RESEND_API_KEY")}',
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result.get("id")


def _sanitize_error(exc: Exception, email: str = "") -> str:
    detail = str(exc)
    secrets = (
        os.getenv("R2_ACCESS_KEY_ID", ""),
        os.getenv("R2_SECRET_ACCESS_KEY", ""),
        os.getenv("RESEND_API_KEY", ""),
        os.getenv("R2_ACCOUNT_ID", ""),
        email,
    )
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, "<redacted>")
    detail = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "<redacted-email>",
        detail,
        flags=re.I,
    )
    return detail[:500] or exc.__class__.__name__


def _log_delivery(run_id: str, state: dict) -> None:
    record = {
        "delivery_id": _delivery_id(run_id),
        "status": state["status"],
        "attempt": state["attempt_count"],
    }
    if state["status"] == "DELIVERY_ERROR":
        record["detail"] = state.get("sanitized_error_detail")
    print(
        "BLUEPRINT_DELIVERY_STATUS "
        + json.dumps(record, ensure_ascii=True, separators=(",", ":")),
        flush=True,
    )


def deliver_blueprint(run_dir: Path, intake: dict) -> dict:
    run_dir = Path(run_dir)
    with _run_lock(run_dir.name):
        state = _load_state(run_dir)
        if state.get("status") == "DELIVERED":
            return state

        email = str((intake.get("_shopify") or {}).get("email") or "").strip()
        state["attempt_count"] = int(state.get("attempt_count") or 0) + 1
        state["status"] = "DELIVERY_PENDING"
        state["sanitized_error_detail"] = None
        state["error_at"] = None
        _save_state(run_dir, state)
        _log_delivery(run_dir.name, state)

        try:
            if not email:
                raise RuntimeError("Shopify customer email is missing")
            bucket = _required_env("R2_BUCKET_NAME")
            pdf_path = run_dir / PDF_RELATIVE_PATH
            if not pdf_path.is_file():
                raise RuntimeError("Completed Blueprint PDF is missing")

            client = _r2_client()
            if not state.get("uploaded_at"):
                client.upload_file(
                    str(pdf_path),
                    bucket,
                    state["object_key"],
                    ExtraArgs={
                        "ContentType": "application/pdf",
                        "ContentDisposition": 'attachment; filename="Architect-Blueprint.pdf"',
                    },
                )
                state["status"] = "PDF_UPLOADED"
                state["uploaded_at"] = _now()
                _save_state(run_dir, state)
                _log_delivery(run_dir.name, state)

            download_url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": state["object_key"]},
                ExpiresIn=_configured_download_ttl(),
            )
            state["status"] = "DELIVERY_PENDING"
            _save_state(run_dir, state)
            _log_delivery(run_dir.name, state)

            state["provider_message_id"] = _send_resend(
                email,
                download_url,
                f"architect-blueprint-{_delivery_id(run_dir.name)}",
            )
            state["status"] = "DELIVERED"
            state["delivered_at"] = _now()
            _save_state(run_dir, state)
            _log_delivery(run_dir.name, state)
        except Exception as exc:
            state["status"] = "DELIVERY_ERROR"
            state["error_at"] = _now()
            state["sanitized_error_detail"] = _sanitize_error(exc, email)
            _save_state(run_dir, state)
            _log_delivery(run_dir.name, state)
        return state


def deliver_if_manifest_pass(run_dir: Path, intake: dict) -> dict | None:
    manifest_path = Path(run_dir) / MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "PASS":
        return None
    return deliver_blueprint(Path(run_dir), intake)


def attempt_delivery_if_manifest_pass(run_dir: Path, intake: dict) -> dict | None:
    """Keep every delivery failure isolated from successful generation state."""
    try:
        return deliver_if_manifest_pass(run_dir, intake)
    except Exception as exc:
        fallback = {
            "status": "DELIVERY_ERROR",
            "attempt_count": 0,
            "sanitized_error_detail": _sanitize_error(exc),
        }
        _log_delivery(Path(run_dir).name, fallback)
        return fallback
