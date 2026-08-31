from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bridge_app.alerts import notify_failure


DELIVERY_FILENAME = "delivery.json"
PDF_RELATIVE_PATH = Path("engine_output") / "05_architect_blueprint.pdf"
MANIFEST_RELATIVE_PATH = Path("engine_output") / "00_manifest.json"
SUPPORT_PDF_PREFIX = "support-runs"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_shopify_token_lock = threading.Lock()
_shopify_token_cache: dict[str, object] = {
    "access_token": None,
    "expires_at": 0.0,
    "cache_key": None,
}


class ResendHTTPFailure(RuntimeError):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"Resend HTTP {status}: {detail}")


class ShopifyHTTPFailure(RuntimeError):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"Shopify HTTP {status}: {detail}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_lock(run_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(run_id, threading.Lock())


def _object_key(run_id: str) -> str:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:32]
    return f"blueprints/{digest}.pdf"


def _support_object_key(run_id: str) -> str:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:32]
    return f"{SUPPORT_PDF_PREFIX}/{digest}.pdf"


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
        "provider_http_status": None,
        "attempt_count": 0,
        "created_at": now,
        "updated_at": now,
        "uploaded_at": None,
        "delivered_at": None,
        "error_at": None,
        "sanitized_error_detail": None,
        "fulfillment_status": "PENDING",
        "fulfillment_ids": [],
        "fulfilled_at": None,
        "fulfillment_error_at": None,
        "fulfillment_http_status": None,
        "fulfillment_error_detail": None,
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


def _sanitize_text(detail: str, email: str = "") -> str:
    secrets = (
        os.getenv("R2_ACCESS_KEY_ID", ""),
        os.getenv("R2_SECRET_ACCESS_KEY", ""),
        os.getenv("RESEND_API_KEY", ""),
        os.getenv("R2_ACCOUNT_ID", ""),
        os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN", ""),
        os.getenv("SHOPIFY_CLIENT_SECRET", ""),
        os.getenv("SHOPIFY_SHOP_DOMAIN", ""),
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
    detail = re.sub(r"https?://\S+", "<redacted-url>", detail, flags=re.I)
    return detail[:500]


def _safe_resend_response_detail(raw: bytes, email: str) -> str:
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "<non-UTF-8 response body omitted>"
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return _sanitize_text(decoded, email) or "<empty response body>"
    if isinstance(payload, dict):
        allowed = {
            key: payload[key]
            for key in ("statusCode", "name", "message", "error")
            if key in payload
        }
        detail = json.dumps(allowed or {"detail": "<structured response detail omitted>"})
    else:
        detail = json.dumps(payload)
    return _sanitize_text(detail, email)


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


def archive_pdf_for_support(run_dir: Path) -> bool:
    """Persist a private support copy without delivering it to the customer."""
    run_dir = Path(run_dir)
    pdf_path = run_dir / PDF_RELATIVE_PATH
    if not pdf_path.is_file():
        return False
    bucket = _required_env("R2_BUCKET_NAME")
    _r2_client().upload_file(
        str(pdf_path),
        bucket,
        _support_object_key(run_dir.name),
        ExtraArgs={
            "ContentType": "application/pdf",
            "ContentDisposition": 'attachment; filename="Architect-Blueprint-Review.pdf"',
        },
    )
    return True


def load_support_pdf(run_id: str) -> bytes | None:
    """Return a private archived PDF, or None when no archive exists."""
    try:
        response = _r2_client().get_object(
            Bucket=_required_env("R2_BUCKET_NAME"),
            Key=_support_object_key(run_id),
        )
        return response["Body"].read()
    except Exception as exc:
        error = getattr(exc, "response", {}) or {}
        code = str((error.get("Error") or {}).get("Code") or "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise


def fetch_paid_shopify_order(order_number: str) -> dict:
    """Fetch one exact paid Shopify order and convert it to webhook shape."""
    normalized = str(order_number or "").strip().lstrip("#")
    if not normalized.isdigit():
        raise ValueError("Shopify order number must contain digits only")

    query = """
    query RecoverBlueprintOrder($query: String!) {
      orders(first: 10, query: $query) {
        nodes {
          id
          name
          email
          displayFinancialStatus
          lineItems(first: 250) {
            nodes {
              id
              title
              quantity
              unfulfilledQuantity
              product { id }
              variant { id }
              customAttributes { key value }
            }
          }
        }
      }
    }
    """
    data = _shopify_graphql(query, {"query": f"name:{normalized}"})
    matches = [
        order
        for order in (data.get("orders") or {}).get("nodes") or []
        if str(order.get("name") or "").lstrip("#") == normalized
    ]
    if len(matches) != 1:
        raise LookupError("Shopify order was not found uniquely")

    source = matches[0]
    if str(source.get("displayFinancialStatus") or "").upper() != "PAID":
        raise PermissionError("Shopify order is not currently paid")

    def legacy_id(gid: object) -> str | None:
        value = str(gid or "").strip()
        return value.rsplit("/", 1)[-1] if value else None

    items = []
    for item in (source.get("lineItems") or {}).get("nodes") or []:
        items.append(
            {
                "id": legacy_id(item.get("id")),
                "title": item.get("title"),
                "quantity": item.get("quantity"),
                "unfulfilled_quantity": item.get("unfulfilledQuantity"),
                "product_id": legacy_id((item.get("product") or {}).get("id")),
                "variant_id": legacy_id((item.get("variant") or {}).get("id")),
                "properties": [
                    {"name": attribute.get("key"), "value": attribute.get("value")}
                    for attribute in item.get("customAttributes") or []
                ],
            }
        )

    return {
        "id": legacy_id(source.get("id")),
        "name": source.get("name"),
        "email": source.get("email"),
        "financial_status": "paid",
        "line_items": items,
    }


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
            "User-Agent": "architect-blueprint/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _safe_resend_response_detail(exc.read(), email)
        raise ResendHTTPFailure(exc.code, detail) from None
    return result.get("id")


def _shopify_fulfillment_configured() -> bool:
    has_domain = bool(os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip())
    has_legacy_token = bool(os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN", "").strip())
    has_client_credentials = bool(
        os.getenv("SHOPIFY_CLIENT_ID", "").strip()
        and os.getenv("SHOPIFY_CLIENT_SECRET", "").strip()
    )
    return has_domain and (has_legacy_token or has_client_credentials)


def _shopify_domain() -> str:
    domain = _required_env("SHOPIFY_SHOP_DOMAIN").lower()
    if domain.startswith("http://") or domain.startswith("https://") or "/" in domain:
        raise RuntimeError("SHOPIFY_SHOP_DOMAIN must be a bare myshopify.com domain")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", domain):
        raise RuntimeError("SHOPIFY_SHOP_DOMAIN must end in .myshopify.com")
    return domain


def _shopify_access_token() -> str:
    """Return a valid Admin API token without requiring daily manual rotation."""
    legacy_token = os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN", "").strip()
    if legacy_token:
        return legacy_token

    domain = _shopify_domain()
    client_id = _required_env("SHOPIFY_CLIENT_ID")
    client_secret = _required_env("SHOPIFY_CLIENT_SECRET")
    cache_key = hashlib.sha256(f"{domain}\0{client_id}".encode("utf-8")).hexdigest()

    with _shopify_token_lock:
        now = time.time()
        cached_token = _shopify_token_cache.get("access_token")
        if (
            cached_token
            and _shopify_token_cache.get("cache_key") == cache_key
            and now < float(_shopify_token_cache.get("expires_at") or 0) - 60
        ):
            return str(cached_token)

        request = Request(
            f"https://{domain}/admin/oauth/access_token",
            data=urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "architect-blueprint/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = _sanitize_text(exc.read().decode("utf-8", errors="replace"))
            raise ShopifyHTTPFailure(
                exc.code, detail or "Shopify token request failed"
            ) from None

        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("Shopify token response did not include an access token")
        try:
            expires_in = int(payload.get("expires_in") or 0)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Shopify token response had an invalid expiration") from exc
        if expires_in <= 60:
            raise RuntimeError("Shopify token response had an invalid expiration")

        _shopify_token_cache.update(
            {
                "access_token": access_token,
                "expires_at": now + expires_in,
                "cache_key": cache_key,
            }
        )
        return access_token


def _shopify_graphql(query: str, variables: dict) -> dict:
    domain = _shopify_domain()
    version = os.getenv("SHOPIFY_API_VERSION", "2026-07").strip() or "2026-07"
    request = Request(
        f"https://{domain}/admin/api/{version}/graphql.json",
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": _shopify_access_token(),
            "User-Agent": "architect-blueprint/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _sanitize_text(exc.read().decode("utf-8", errors="replace"))
        raise ShopifyHTTPFailure(exc.code, detail or "Shopify request failed") from None

    if payload.get("errors"):
        raise RuntimeError(
            "Shopify GraphQL error: " + _sanitize_text(json.dumps(payload["errors"]))
        )
    return payload.get("data") or {}


def _fulfill_shopify_line_item(intake: dict) -> list[str]:
    shopify = intake.get("_shopify") or {}
    order_id = str(shopify.get("order_id") or "").strip()
    line_item_id = str(shopify.get("line_item_id") or "").strip()
    if not order_id or not line_item_id:
        raise RuntimeError("Shopify order or line-item ID is missing")

    order_gid = f"gid://shopify/Order/{order_id}"
    line_item_gid = f"gid://shopify/LineItem/{line_item_id}"
    query = """
    query BlueprintFulfillmentOrders($id: ID!) {
      order(id: $id) {
        fulfillmentOrders(first: 50) {
          nodes {
            id
            lineItems(first: 250) {
              nodes {
                id
                remainingQuantity
                lineItem { id }
              }
            }
          }
        }
      }
    }
    """
    data = _shopify_graphql(query, {"id": order_gid})
    order = data.get("order")
    if not order:
        raise RuntimeError("Shopify order was not found")

    matching_items = []
    found = False
    for fulfillment_order in (order.get("fulfillmentOrders") or {}).get("nodes") or []:
        for fulfillment_item in (fulfillment_order.get("lineItems") or {}).get("nodes") or []:
            if (fulfillment_item.get("lineItem") or {}).get("id") != line_item_gid:
                continue
            found = True
            remaining = int(fulfillment_item.get("remainingQuantity") or 0)
            if remaining > 0:
                matching_items.append(
                    {
                        "fulfillment_order_id": fulfillment_order["id"],
                        "fulfillment_order_line_item_id": fulfillment_item["id"],
                        "quantity": remaining,
                    }
                )

    if not found:
        raise RuntimeError("Blueprint line item was not found in Shopify fulfillment orders")
    if not matching_items:
        return []

    mutation = """
    mutation FulfillDeliveredBlueprint($fulfillment: FulfillmentInput!) {
      fulfillmentCreate(fulfillment: $fulfillment) {
        fulfillment { id status }
        userErrors { field message }
      }
    }
    """
    fulfillment_ids = []
    for item in matching_items:
        variables = {
            "fulfillment": {
                "notifyCustomer": False,
                "lineItemsByFulfillmentOrder": [
                    {
                        "fulfillmentOrderId": item["fulfillment_order_id"],
                        "fulfillmentOrderLineItems": [
                            {
                                "id": item["fulfillment_order_line_item_id"],
                                "quantity": item["quantity"],
                            }
                        ],
                    }
                ],
            }
        }
        result = _shopify_graphql(mutation, variables).get("fulfillmentCreate") or {}
        if result.get("userErrors"):
            raise RuntimeError(
                "Shopify fulfillment error: "
                + _sanitize_text(json.dumps(result["userErrors"]))
            )
        fulfillment = result.get("fulfillment") or {}
        if not fulfillment.get("id"):
            raise RuntimeError("Shopify did not return a fulfillment ID")
        fulfillment_ids.append(str(fulfillment["id"]))
    return fulfillment_ids


def _sanitize_error(exc: Exception, email: str = "") -> str:
    return _sanitize_text(str(exc), email) or exc.__class__.__name__


def _log_delivery(run_id: str, state: dict) -> None:
    record = {
        "delivery_id": _delivery_id(run_id),
        "status": state["status"],
        "attempt": state["attempt_count"],
    }
    if state["status"] == "DELIVERY_ERROR":
        if state.get("provider_http_status") is not None:
            record["http_status"] = state["provider_http_status"]
        record["detail"] = state.get("sanitized_error_detail")
    print(
        "BLUEPRINT_DELIVERY_STATUS "
        + json.dumps(record, ensure_ascii=True, separators=(",", ":")),
        flush=True,
    )


def _log_fulfillment(run_id: str, state: dict) -> None:
    record = {
        "delivery_id": _delivery_id(run_id),
        "status": state.get("fulfillment_status"),
    }
    if state.get("fulfillment_status") == "FULFILLMENT_ERROR":
        if state.get("fulfillment_http_status") is not None:
            record["http_status"] = state["fulfillment_http_status"]
        record["detail"] = state.get("fulfillment_error_detail")
    print(
        "BLUEPRINT_FULFILLMENT_STATUS "
        + json.dumps(record, ensure_ascii=True, separators=(",", ":")),
        flush=True,
    )


def _attempt_shopify_fulfillment(run_dir: Path, state: dict, intake: dict) -> dict:
    if state.get("fulfillment_status") == "FULFILLED":
        return state
    if not _shopify_fulfillment_configured():
        state["fulfillment_status"] = "NOT_CONFIGURED"
        state["fulfillment_error_detail"] = "Shopify fulfillment automation is not configured"
        _save_state(run_dir, state)
        _log_fulfillment(run_dir.name, state)
        return state

    state["fulfillment_status"] = "FULFILLMENT_PENDING"
    state["fulfillment_http_status"] = None
    state["fulfillment_error_detail"] = None
    state["fulfillment_error_at"] = None
    _save_state(run_dir, state)
    _log_fulfillment(run_dir.name, state)
    try:
        state["fulfillment_ids"] = _fulfill_shopify_line_item(intake)
        state["fulfillment_status"] = "FULFILLED"
        state["fulfilled_at"] = _now()
    except Exception as exc:
        state["fulfillment_status"] = "FULFILLMENT_ERROR"
        state["fulfillment_http_status"] = getattr(exc, "status", None)
        state["fulfillment_error_at"] = _now()
        state["fulfillment_error_detail"] = _sanitize_error(exc)
        shopify = intake.get("_shopify") or {}
        notify_failure(
            run_dir,
            stage="shopify_fulfillment",
            status=state["fulfillment_status"],
            detail=state["fulfillment_error_detail"],
            order_name=str(shopify.get("order_name") or shopify.get("order_id") or "unknown"),
            http_status=state.get("fulfillment_http_status"),
        )
    _save_state(run_dir, state)
    _log_fulfillment(run_dir.name, state)
    return state


def deliver_blueprint(run_dir: Path, intake: dict) -> dict:
    run_dir = Path(run_dir)
    with _run_lock(run_dir.name):
        state = _load_state(run_dir)
        if state.get("status") == "DELIVERED":
            return _attempt_shopify_fulfillment(run_dir, state, intake)

        email = str((intake.get("_shopify") or {}).get("email") or "").strip()
        state["attempt_count"] = int(state.get("attempt_count") or 0) + 1
        state["status"] = "DELIVERY_PENDING"
        state["provider_http_status"] = None
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
            state = _attempt_shopify_fulfillment(run_dir, state, intake)
        except Exception as exc:
            state["status"] = "DELIVERY_ERROR"
            state["provider_http_status"] = getattr(exc, "status", None)
            state["error_at"] = _now()
            state["sanitized_error_detail"] = _sanitize_error(exc, email)
            shopify = intake.get("_shopify") or {}
            notify_failure(
                run_dir,
                stage="customer_pdf_delivery",
                status=state["status"],
                detail=state["sanitized_error_detail"],
                order_name=str(shopify.get("order_name") or shopify.get("order_id") or "unknown"),
                http_status=state.get("provider_http_status"),
            )
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
            "provider_http_status": getattr(exc, "status", None),
            "sanitized_error_detail": _sanitize_error(exc),
        }
        _log_delivery(Path(run_dir).name, fallback)
        shopify = intake.get("_shopify") or {}
        notify_failure(
            Path(run_dir),
            stage="customer_pdf_delivery",
            status=fallback["status"],
            detail=fallback["sanitized_error_detail"],
            order_name=str(shopify.get("order_name") or shopify.get("order_id") or "unknown"),
            http_status=fallback.get("provider_http_status"),
        )
        return fallback
