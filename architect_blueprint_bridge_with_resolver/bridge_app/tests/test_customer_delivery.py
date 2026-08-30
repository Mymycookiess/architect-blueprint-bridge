import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import HTTPException

from bridge_app.app import get_run_pdf, inspect_run
from bridge_app.delivery import (
    _fulfill_shopify_line_item,
    _send_resend,
    attempt_delivery_if_manifest_pass,
    deliver_if_manifest_pass,
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
    "SHOPIFY_ADMIN_ACCESS_TOKEN": "shopify-token",
}


class FakeR2Client:
    def __init__(self, upload_error=None):
        self.upload_error = upload_error
        self.upload_calls = []
        self.presign_calls = []

    def upload_file(self, *args, **kwargs):
        self.upload_calls.append((args, kwargs))
        if self.upload_error:
            raise self.upload_error

    def generate_presigned_url(self, *args, **kwargs):
        self.presign_calls.append((args, kwargs))
        return "https://private-download.example/signed"


class FakeHTTPResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"id":"email_789"}'


class CustomerDeliveryTests(unittest.TestCase):
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

    def test_internal_run_endpoints_remain_inspect_key_protected(self):
        with patch.dict(os.environ, {"INSPECT_KEY": "support-secret"}, clear=False):
            with self.assertRaises(HTTPException) as inspect_error:
                inspect_run("example", x_inspect_key=None)
            with self.assertRaises(HTTPException) as pdf_error:
                get_run_pdf("example", x_inspect_key=None)
        self.assertEqual(inspect_error.exception.status_code, 403)
        self.assertEqual(pdf_error.exception.status_code, 403)

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
