import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import BackgroundTasks, HTTPException

from bridge_app.app import get_run_pdf, inspect_run, recover_shopify_order
from bridge_app.delivery import (
    _support_object_key,
    _fulfill_shopify_line_item,
    _send_resend,
    _shopify_access_token,
    _shopify_graphql,
    _shopify_token_cache,
    archive_pdf_for_support,
    attempt_delivery_if_manifest_pass,
    deliver_if_manifest_pass,
    fetch_paid_shopify_order,
    load_support_pdf,
)


DELIVERY_ENV = {
    "R2_ACCOUNT_ID": "account-id",
    "R2_ACCESS_KEY_ID": "access-key",
    "R2_SECRET_ACCESS_KEY": "secret-key",
    "R2_BUCKET_NAME": "private-blueprints",
    "BLUEPRINT_DOWNLOAD_TTL_SECONDS": "604800",
    "RESEND_API_KEY": "resend-key",
    "BLUEPRINT_FROM_EMAIL": "The Architect <blueprints@example.com>",
    "SHOPIFY_SHOP_DOMAIN": "example.myshopify.com",
    "SHOPIFY_CLIENT_ID": "shopify-client-id",
    "SHOPIFY_CLIENT_SECRET": "shopify-client-secret",
}


class FakeR2Client:
    def __init__(self, upload_error=None, objects=None):
        self.upload_error = upload_error
        self.objects = objects or {}
        self.upload_calls = []
        self.presign_calls = []

    def upload_file(self, *args, **kwargs):
        self.upload_calls.append((args, kwargs))
        if self.upload_error:
            raise self.upload_error

    def generate_presigned_url(self, *args, **kwargs):
        self.presign_calls.append((args, kwargs))
        return "https://private-download.example/signed"

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            missing = RuntimeError("missing")
            missing.response = {"Error": {"Code": "NoSuchKey"}}
            raise missing
        return {"Body": io.BytesIO(self.objects[Key])}


class FakeHTTPResponse:
    def __init__(self, body=b'{"id":"email_789"}'):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class CustomerDeliveryTests(unittest.TestCase):
    def setUp(self):
        _shopify_token_cache.update(
            {"access_token": None, "expires_at": 0.0, "cache_key": None}
        )

    def _run_dir(self, root, manifest_status="PASS"):
        run_dir = Path(root) / "order_1001_line_2002"
        engine_dir = run_dir / "engine_output"
        engine_dir.mkdir(parents=True)
        (engine_dir / "00_manifest.json").write_text(json.dumps({"status": manifest_status}))
        (engine_dir / "05_architect_blueprint.pdf").write_bytes(b"%PDF-test")
        return run_dir

    def _intake(self):
        return {
            "_shopify": {
                "email": "customer@example.com",
                "order_id": 1001,
                "line_item_id": 2002,
            }
        }

    def test_pass_manifest_uploads_and_delivers_once(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = self._run_dir(root)
            r2 = FakeR2Client()
            with patch.dict(os.environ, DELIVERY_ENV, clear=False), patch(
                "bridge_app.delivery._r2_client", return_value=r2
            ), patch(
                "bridge_app.delivery._send_resend", return_value="email_123"
            ) as resend, patch(
                "bridge_app.delivery._fulfill_shopify_line_item",
                return_value=["gid://shopify/Fulfillment/3003"],
            ) as fulfill:
                first = deliver_if_manifest_pass(run_dir, self._intake())
                second = deliver_if_manifest_pass(run_dir, self._intake())

            self.assertEqual(first["status"], "DELIVERED")
            self.assertEqual(second["status"], "DELIVERED")
            self.assertEqual(first["provider_message_id"], "email_123")
            self.assertEqual(first["attempt_count"], 1)
            self.assertEqual(len(r2.upload_calls), 1)
            self.assertNotIn("ACL", r2.upload_calls[0][1]["ExtraArgs"])
            self.assertEqual(r2.presign_calls[0][1]["ExpiresIn"], 604800)
            self.assertEqual(resend.call_count, 1)
            self.assertEqual(fulfill.call_count, 1)
            self.assertEqual(first["fulfillment_status"], "FULFILLED")
            self.assertNotIn("customer", first["object_key"])
            persisted = json.loads((run_dir / "delivery.json").read_text())
            self.assertEqual(persisted["status"], "DELIVERED")
            self.assertNotIn("private-download", json.dumps(persisted))

    def test_non_pass_manifest_never_delivers(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = self._run_dir(root, manifest_status="REVIEW_REQUIRED")
            with patch("bridge_app.delivery._r2_client") as r2, patch(
                "bridge_app.delivery._send_resend"
            ) as resend:
                result = deliver_if_manifest_pass(run_dir, self._intake())
            self.assertIsNone(result)
            r2.assert_not_called()
            resend.assert_not_called()
            self.assertFalse((run_dir / "delivery.json").exists())

    def test_support_archive_is_private_and_retrievable(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = self._run_dir(root, manifest_status="REVIEW_REQUIRED")
            key = _support_object_key(run_dir.name)
            r2 = FakeR2Client(objects={key: b"%PDF-archived"})
            with patch.dict(os.environ, DELIVERY_ENV, clear=False), patch(
                "bridge_app.delivery._r2_client", return_value=r2
            ):
                self.assertTrue(archive_pdf_for_support(run_dir))
                archived = load_support_pdf(run_dir.name)

            self.assertEqual(archived, b"%PDF-archived")
            self.assertEqual(r2.upload_calls[0][0][2], key)
            self.assertNotIn("ACL", r2.upload_calls[0][1]["ExtraArgs"])

    def test_pdf_endpoint_falls_back_to_private_support_archive(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ,
            {"INSPECT_KEY": "support-secret", "BLUEPRINT_OUTPUT_ROOT": root},
            clear=False,
        ), patch("bridge_app.app.BLUEPRINT_OUTPUT_ROOT", Path(root)), patch(
            "bridge_app.app.load_support_pdf", return_value=b"%PDF-archived"
        ):
            response = get_run_pdf("1069_17319153303804", "support-secret")

        self.assertEqual(response.body, b"%PDF-archived")
        self.assertEqual(response.media_type, "application/pdf")

    def test_r2_failure_persists_delivery_error(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = self._run_dir(root)
            r2 = FakeR2Client(RuntimeError("R2 unavailable secret-key"))
            with patch.dict(os.environ, DELIVERY_ENV, clear=False), patch(
                "bridge_app.delivery._r2_client", return_value=r2
            ), patch("bridge_app.delivery._send_resend") as resend:
                state = deliver_if_manifest_pass(run_dir, self._intake())

            self.assertEqual(state["status"], "DELIVERY_ERROR")
            self.assertEqual(state["attempt_count"], 1)
            self.assertNotIn("secret-key", state["sanitized_error_detail"])
            resend.assert_not_called()

    def test_resend_failure_is_retryable_without_reupload(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = self._run_dir(root)
            r2 = FakeR2Client()
            with patch.dict(os.environ, DELIVERY_ENV, clear=False), patch(
                "bridge_app.delivery._r2_client", return_value=r2
            ), patch(
                "bridge_app.delivery._send_resend",
                side_effect=[RuntimeError("Resend unavailable customer@example.com"), "email_456"],
            ) as resend, patch(
                "bridge_app.delivery._fulfill_shopify_line_item", return_value=[]
            ):
                failed = deliver_if_manifest_pass(run_dir, self._intake())
                delivered = deliver_if_manifest_pass(run_dir, self._intake())

            self.assertEqual(failed["status"], "DELIVERY_ERROR")
            self.assertNotIn("customer@example.com", failed["sanitized_error_detail"])
            self.assertEqual(delivered["status"], "DELIVERED")
            self.assertEqual(delivered["attempt_count"], 2)
            self.assertEqual(delivered["provider_message_id"], "email_456")
            self.assertEqual(len(r2.upload_calls), 1)
            self.assertEqual(resend.call_count, 2)

    def test_fulfillment_failure_retries_without_resending_email(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = self._run_dir(root)
            r2 = FakeR2Client()
            with patch.dict(os.environ, DELIVERY_ENV, clear=False), patch(
                "bridge_app.delivery._r2_client", return_value=r2
            ), patch(
                "bridge_app.delivery._send_resend", return_value="email_123"
            ) as resend, patch(
                "bridge_app.delivery._fulfill_shopify_line_item",
                side_effect=[RuntimeError("temporary Shopify error"), ["gid://shopify/Fulfillment/3003"]],
            ) as fulfill:
                first = deliver_if_manifest_pass(run_dir, self._intake())
                second = deliver_if_manifest_pass(run_dir, self._intake())

            self.assertEqual(first["status"], "DELIVERED")
            self.assertEqual(first["fulfillment_status"], "FULFILLMENT_ERROR")
            self.assertEqual(second["fulfillment_status"], "FULFILLED")
            self.assertEqual(resend.call_count, 1)
            self.assertEqual(fulfill.call_count, 2)

    def test_shopify_fulfillment_targets_only_blueprint_line_item_without_notification(self):
        responses = [
            {
                "order": {
                    "fulfillmentOrders": {
                        "nodes": [{
                            "id": "gid://shopify/FulfillmentOrder/10",
                            "lineItems": {"nodes": [
                                {
                                    "id": "gid://shopify/FulfillmentOrderLineItem/20",
                                    "remainingQuantity": 1,
                                    "lineItem": {"id": "gid://shopify/LineItem/2002"},
                                },
                                {
                                    "id": "gid://shopify/FulfillmentOrderLineItem/21",
                                    "remainingQuantity": 1,
                                    "lineItem": {"id": "gid://shopify/LineItem/9999"},
                                },
                            ]},
                        }]}
                }
            },
            {
                "fulfillmentCreate": {
                    "fulfillment": {"id": "gid://shopify/Fulfillment/30", "status": "SUCCESS"},
                    "userErrors": [],
                }
            },
        ]
        calls = []

        def fake_graphql(query, variables):
            calls.append((query, variables))
            return responses.pop(0)

        with patch("bridge_app.delivery._shopify_graphql", side_effect=fake_graphql):
            ids = _fulfill_shopify_line_item(self._intake())

        self.assertEqual(ids, ["gid://shopify/Fulfillment/30"])
        fulfillment = calls[1][1]["fulfillment"]
        self.assertFalse(fulfillment["notifyCustomer"])
        selected = fulfillment["lineItemsByFulfillmentOrder"][0]["fulfillmentOrderLineItems"]
        self.assertEqual(selected, [{
            "id": "gid://shopify/FulfillmentOrderLineItem/20",
            "quantity": 1,
        }])

    def test_shopify_client_credentials_token_is_cached_and_used_for_graphql(self):
        captured = []

        def fake_urlopen(request, timeout):
            captured.append((request, timeout))
            if request.full_url.endswith("/admin/oauth/access_token"):
                return FakeHTTPResponse(json.dumps({
                    "access_token": "short-lived-token",
                    "scope": "read_orders,write_merchant_managed_fulfillment_orders",
                    "expires_in": 86399,
                }).encode("utf-8"))
            return FakeHTTPResponse(b'{"data":{"shop":{"name":"Blueprint"}}}')

        env = dict(DELIVERY_ENV)
        env.pop("SHOPIFY_ADMIN_ACCESS_TOKEN", None)
        with patch.dict(os.environ, env, clear=True), patch(
            "bridge_app.delivery.urlopen", side_effect=fake_urlopen
        ):
            first_token = _shopify_access_token()
            second_token = _shopify_access_token()
            result = _shopify_graphql("{ shop { name } }", {})

        self.assertEqual(first_token, "short-lived-token")
        self.assertEqual(second_token, "short-lived-token")
        self.assertEqual(result, {"shop": {"name": "Blueprint"}})
        self.assertEqual(len(captured), 2)
        token_request = captured[0][0]
        self.assertEqual(token_request.method, "POST")
        self.assertEqual(
            token_request.get_header("Content-type"),
            "application/x-www-form-urlencoded",
        )
        token_body = token_request.data.decode("utf-8")
        self.assertIn("grant_type=client_credentials", token_body)
        self.assertIn("client_id=shopify-client-id", token_body)
        self.assertIn("client_secret=shopify-client-secret", token_body)
        graphql_request = captured[1][0]
        self.assertEqual(
            graphql_request.get_header("X-shopify-access-token"),
            "short-lived-token",
        )

    def test_fetch_paid_shopify_order_converts_graphql_to_webhook_shape(self):
        response = {
            "orders": {
                "nodes": [
                    {
                        "id": "gid://shopify/Order/1001",
                        "name": "#1069",
                        "email": "customer@example.com",
                        "displayFinancialStatus": "PAID",
                        "lineItems": {
                            "nodes": [
                                {
                                    "id": "gid://shopify/LineItem/2002",
                                    "title": "The Architect Blueprint",
                                    "quantity": 1,
                                    "unfulfilledQuantity": 1,
                                    "product": {"id": "gid://shopify/Product/3003"},
                                    "variant": {"id": "gid://shopify/ProductVariant/4004"},
                                    "customAttributes": [
                                        {"key": "_Architect Product", "value": "true"},
                                        {"key": "Blueprint Full Name", "value": "Sample Customer"},
                                    ],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        with patch("bridge_app.delivery._shopify_graphql", return_value=response) as graphql:
            order = fetch_paid_shopify_order("#1069")

        self.assertEqual(order["id"], "1001")
        self.assertEqual(order["name"], "#1069")
        self.assertEqual(order["line_items"][0]["id"], "2002")
        self.assertEqual(order["line_items"][0]["unfulfilled_quantity"], 1)
        self.assertEqual(
            order["line_items"][0]["properties"][0],
            {"name": "_Architect Product", "value": "true"},
        )
        self.assertEqual(graphql.call_args.args[1], {"query": "name:1069"})

    def test_recovery_endpoint_requires_paid_unfulfilled_blueprint(self):
        order = {
            "id": "1001",
            "name": "#1069",
            "email": "customer@example.com",
            "line_items": [
                {
                    "id": "17319153303804",
                    "unfulfilled_quantity": 1,
                    "properties": [{"name": "_Architect Product", "value": "true"}],
                }
            ],
        }
        tasks = BackgroundTasks()
        with patch.dict(os.environ, {"INSPECT_KEY": "support-secret"}, clear=False), patch(
            "bridge_app.app.fetch_paid_shopify_order", return_value=order
        ):
            result = recover_shopify_order("1069", tasks, "support-secret")

        self.assertTrue(result["accepted"])
        self.assertEqual(result["run_ids"], ["1069_17319153303804"])
        self.assertEqual(len(tasks.tasks), 1)

        order["line_items"][0]["unfulfilled_quantity"] = 0
        with patch.dict(os.environ, {"INSPECT_KEY": "support-secret"}, clear=False), patch(
            "bridge_app.app.fetch_paid_shopify_order", return_value=order
        ), self.assertRaises(HTTPException) as blocked:
            recover_shopify_order("1069", BackgroundTasks(), "support-secret")
        self.assertEqual(blocked.exception.status_code, 409)

    def test_legacy_shopify_token_remains_supported_during_migration(self):
        env = {
            "SHOPIFY_SHOP_DOMAIN": "example.myshopify.com",
            "SHOPIFY_ADMIN_ACCESS_TOKEN": "legacy-token",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "bridge_app.delivery.urlopen"
        ) as urlopen_mock:
            token = _shopify_access_token()
        self.assertEqual(token, "legacy-token")
        urlopen_mock.assert_not_called()

    def test_internal_run_endpoints_remain_inspect_key_protected(self):
        with patch.dict(os.environ, {"INSPECT_KEY": "support-secret"}, clear=False):
            with self.assertRaises(HTTPException) as inspect_error:
                inspect_run("example", x_inspect_key=None)
            with self.assertRaises(HTTPException) as pdf_error:
                get_run_pdf("example", x_inspect_key=None)
            with self.assertRaises(HTTPException) as recovery_error:
                recover_shopify_order("1069", BackgroundTasks(), x_inspect_key=None)
        self.assertEqual(inspect_error.exception.status_code, 403)
        self.assertEqual(pdf_error.exception.status_code, 403)
        self.assertEqual(recovery_error.exception.status_code, 403)

    def test_resend_email_has_branded_copy_link_and_no_attachment(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHTTPResponse()

        with patch.dict(os.environ, DELIVERY_ENV, clear=False), patch(
            "bridge_app.delivery.urlopen", side_effect=fake_urlopen
        ):
            message_id = _send_resend(
                "customer@example.com",
                "https://private-download.example/signed?a=1&b=2",
                "stable-delivery-key",
            )

        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(message_id, "email_789")
        self.assertEqual(captured["request"].full_url, "https://api.resend.com/emails")
        self.assertEqual(captured["request"].method, "POST")
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer resend-key")
        self.assertEqual(captured["request"].get_header("Content-type"), "application/json")
        self.assertEqual(captured["request"].get_header("User-agent"), "architect-blueprint/1.0")
        self.assertEqual(payload["from"], DELIVERY_ENV["BLUEPRINT_FROM_EMAIL"])
        self.assertEqual(payload["to"], ["customer@example.com"])
        self.assertEqual(payload["subject"], "Your Architect Blueprint Is Ready")
        self.assertIn("Your personalized Architect Blueprint is complete.", payload["html"])
        self.assertIn("Download Your Blueprint", payload["html"])
        self.assertNotIn("attachments", payload)
        self.assertEqual(captured["request"].get_header("Idempotency-key"), "stable-delivery-key")

    def test_unhandled_delivery_io_failure_does_not_escape(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = self._run_dir(root)
            with patch(
                "bridge_app.delivery.deliver_if_manifest_pass",
                side_effect=OSError("temporary delivery state failure"),
            ):
                state = attempt_delivery_if_manifest_pass(run_dir, self._intake())
        self.assertEqual(state["status"], "DELIVERY_ERROR")

    def test_resend_403_body_is_sanitized_and_logged_with_delivery_id(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = self._run_dir(root)
            r2 = FakeR2Client()
            response_body = json.dumps({
                "statusCode": 403,
                "name": "validation_error",
                "message": (
                    "Sender blueprints@example.com is not verified; resend-key; "
                    "https://private-download.example/signed"
                ),
                "request": "full request body must not be logged",
            }).encode("utf-8")
            forbidden = HTTPError(
                "https://api.resend.com/emails",
                403,
                "Forbidden",
                {},
                io.BytesIO(response_body),
            )
            output = io.StringIO()
            with patch.dict(os.environ, DELIVERY_ENV, clear=False), patch(
                "bridge_app.delivery._r2_client", return_value=r2
            ), patch(
                "bridge_app.delivery.urlopen", side_effect=forbidden
            ), redirect_stdout(output):
                state = deliver_if_manifest_pass(run_dir, self._intake())

        self.assertEqual(state["status"], "DELIVERY_ERROR")
        self.assertEqual(state["provider_http_status"], 403)
        self.assertIn("validation_error", state["sanitized_error_detail"])
        error_line = output.getvalue().splitlines()[-1]
        diagnostic = json.loads(error_line.split(" ", 1)[1])
        self.assertEqual(diagnostic["http_status"], 403)
        self.assertEqual(diagnostic["delivery_id"], "9cf44e303b202fbd")
        self.assertNotIn("customer@example.com", error_line)
        self.assertNotIn("blueprints@example.com", error_line)
        self.assertNotIn("resend-key", error_line)
        self.assertNotIn("private-download.example", error_line)
        self.assertNotIn("full request body", error_line)


if __name__ == "__main__":
    unittest.main()
