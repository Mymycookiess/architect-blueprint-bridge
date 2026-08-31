from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ALERT_STATE_FILENAME = "failure_alerts.json"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _alert_lock(run_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(run_id, threading.Lock())


def _sanitize(detail: str) -> str:
    for name in (
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "RESEND_API_KEY",
        "SHOPIFY_ADMIN_ACCESS_TOKEN",
        "SHOPIFY_CLIENT_SECRET",
        "BLUEPRINT_FAILURE_ALERT_WEBHOOK_TOKEN",
    ):
        secret = os.getenv(name, "")
        if secret:
            detail = detail.replace(secret, "<redacted>")
    detail = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "<redacted-email>",
        detail,
        flags=re.I,
    )
    detail = re.sub(r"https?://\S+", "<redacted-url>", detail, flags=re.I)
    return detail[:500]


def _delivery_id(run_id: str) -> str:
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]


def _fingerprint(run_id: str, stage: str, status: str, detail: str) -> str:
    value = "\0".join((run_id, stage, status, detail))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _load_state(run_dir: Path) -> dict:
    path = run_dir / ALERT_STATE_FILENAME
    if not path.exists():
        return {"alerts": {}}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"alerts": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), dict):
        return {"alerts": {}}
    return payload


def _save_state(run_dir: Path, state: dict) -> None:
    path = run_dir / ALERT_STATE_FILENAME
    temporary = run_dir / f".{ALERT_STATE_FILENAME}.tmp"
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(path)


def _send_email(payload: dict, idempotency_key: str) -> str | None:
    recipient = os.getenv("BLUEPRINT_FAILURE_ALERT_EMAIL", "").strip()
    if not recipient:
        return None
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("BLUEPRINT_FROM_EMAIL", "").strip()
    if not api_key or not sender:
        raise RuntimeError(
            "Failure alert email requires RESEND_API_KEY and BLUEPRINT_FROM_EMAIL"
        )

    safe = {key: html.escape(str(value)) for key, value in payload.items()}
    body = {
        "from": sender,
        "to": [recipient],
        "subject": f"Blueprint order needs attention: {payload['status']}",
        "html": (
            '<div style="font-family:Arial,sans-serif;color:#26231f;max-width:640px;margin:auto;">'
            '<h1 style="font-size:24px;font-weight:600;">A paid Blueprint order needs attention</h1>'
            f"<p><strong>Order:</strong> {safe['order_name']}</p>"
            f"<p><strong>Stage:</strong> {safe['stage']}</p>"
            f"<p><strong>Status:</strong> {safe['status']}</p>"
            f"<p><strong>Support ID:</strong> {safe['delivery_id']}</p>"
            f"<p><strong>Detail:</strong> {safe['detail']}</p>"
            '<p style="font-size:13px;color:#6b665f;">The customer\'s email and birth details are intentionally omitted.</p>'
            "</div>"
        ),
    }
    request = Request(
        "https://api.resend.com/emails",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "User-Agent": "architect-blueprint-alerts/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Resend alert HTTP {exc.code}") from None
    return str(result.get("id") or "") or None


def _send_webhook(payload: dict) -> bool:
    endpoint = os.getenv("BLUEPRINT_FAILURE_ALERT_WEBHOOK_URL", "").strip()
    if not endpoint:
        return False
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "architect-blueprint-alerts/1.0",
    }
    token = os.getenv("BLUEPRINT_FAILURE_ALERT_WEBHOOK_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Failure alert webhook HTTP {response.status}")
    return True


def notify_failure(
    run_dir: Path,
    *,
    stage: str,
    status: str,
    detail: str,
    order_name: str = "unknown",
    http_status: int | None = None,
) -> dict:
    """Send a private, deduplicated owner alert without breaking order processing."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    clean_detail = _sanitize(str(detail or "No additional detail"))
    clean_order = _sanitize(str(order_name or "unknown"))
    fingerprint = _fingerprint(run_dir.name, stage, status, clean_detail)
    payload = {
        "event": "BLUEPRINT_FAILURE",
        "delivery_id": _delivery_id(run_dir.name),
        "order_name": clean_order,
        "stage": _sanitize(stage),
        "status": _sanitize(status),
        "detail": clean_detail,
        "http_status": http_status,
        "occurred_at": _now(),
    }

    with _alert_lock(run_dir.name):
        state = _load_state(run_dir)
        record = state["alerts"].setdefault(
            fingerprint,
            {"channels": [], "created_at": payload["occurred_at"]},
        )
        configured = []
        if os.getenv("BLUEPRINT_FAILURE_ALERT_EMAIL", "").strip():
            configured.append("email")
        if os.getenv("BLUEPRINT_FAILURE_ALERT_WEBHOOK_URL", "").strip():
            configured.append("webhook")

        if not configured:
            print(
                "BLUEPRINT_FAILURE_ALERT "
                + json.dumps(
                    {**payload, "alert_status": "NOT_CONFIGURED"},
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                flush=True,
            )
            return {"status": "NOT_CONFIGURED", "channels": []}

        results = []
        for channel in configured:
            if channel in record["channels"]:
                results.append({"channel": channel, "status": "ALREADY_SENT"})
                continue
            try:
                if channel == "email":
                    _send_email(payload, f"blueprint-failure-{fingerprint}")
                else:
                    _send_webhook(payload)
                record["channels"].append(channel)
                record["last_sent_at"] = _now()
                _save_state(run_dir, state)
                results.append({"channel": channel, "status": "SENT"})
            except Exception as exc:
                results.append(
                    {"channel": channel, "status": "ERROR", "detail": _sanitize(str(exc))}
                )

        alert_status = "SENT" if any(
            item["status"] in {"SENT", "ALREADY_SENT"} for item in results
        ) else "ERROR"
        print(
            "BLUEPRINT_FAILURE_ALERT "
            + json.dumps(
                {
                    "delivery_id": payload["delivery_id"],
                    "stage": payload["stage"],
                    "failure_status": payload["status"],
                    "alert_status": alert_status,
                    "channels": results,
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return {"status": alert_status, "channels": results}
