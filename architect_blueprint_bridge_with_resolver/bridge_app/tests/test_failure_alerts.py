import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from bridge_app.app import send_temporary_deployment_alert_test, test_failure_alert
from bridge_app.alerts import notify_failure


class FakeResponse:
    status = 200

    def __init__(self, body=b'{"id":"alert_123"}'):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class FailureAlertTests(unittest.TestCase):
    def test_temporary_startup_test_is_isolated_from_customer_orders(self):
        with patch(
            "bridge_app.app.notify_failure",
            return_value={"status": "SENT", "channels": [{"channel": "email", "status": "SENT"}]},
        ) as alert:
            send_temporary_deployment_alert_test()

        call = alert.call_args
        self.assertEqual(call.kwargs["stage"], "protection_self_test")
        self.assertEqual(call.kwargs["status"], "TEST_ALERT")
        self.assertEqual(call.kwargs["order_name"], "CONTROLLED TEST")
        serialized = json.dumps(call.kwargs).lower()
        self.assertNotIn("@", serialized)
        self.assertNotIn("birth_date", serialized)
        self.assertNotIn("birth_time", serialized)

    def test_protected_route_sends_controlled_alert_without_customer_data(self):
        with patch.dict(os.environ, {"INSPECT_KEY": "support-secret"}, clear=False), patch(
            "bridge_app.app.notify_failure",
            return_value={"status": "SENT", "channels": [{"channel": "email", "status": "SENT"}]},
        ) as alert:
            result = test_failure_alert(x_inspect_key="support-secret")

        self.assertTrue(result["ok"])
        self.assertEqual(result["alert_status"], "SENT")
        call = alert.call_args
        self.assertEqual(call.kwargs["stage"], "protection_self_test")
        self.assertEqual(call.kwargs["status"], "TEST_ALERT")
        self.assertEqual(call.kwargs["order_name"], "CONTROLLED TEST")
        serialized = json.dumps(call.kwargs).lower()
        self.assertNotIn("@", serialized)
        self.assertNotIn("birth_date", serialized)
        self.assertNotIn("birth_time", serialized)

    def test_protected_route_rejects_missing_key(self):
        with patch.dict(os.environ, {"INSPECT_KEY": "support-secret"}, clear=False):
            with self.assertRaises(HTTPException) as error:
                test_failure_alert(x_inspect_key=None)
        self.assertEqual(error.exception.status_code, 403)

    def test_protected_route_reports_unconfigured_channel(self):
        with patch.dict(os.environ, {"INSPECT_KEY": "support-secret"}, clear=False), patch(
            "bridge_app.app.notify_failure",
            return_value={"status": "NOT_CONFIGURED", "channels": []},
        ):
            with self.assertRaises(HTTPException) as error:
                test_failure_alert(x_inspect_key="support-secret")
        self.assertEqual(error.exception.status_code, 503)

    def test_email_alert_is_private_and_deduplicated(self):
        env = {
            "BLUEPRINT_FAILURE_ALERT_EMAIL": "owner@example.com",
            "RESEND_API_KEY": "resend-secret",
            "BLUEPRINT_FROM_EMAIL": "The Architect <blueprints@example.com>",
        }
        captured = []

        def fake_urlopen(request, timeout):
            captured.append(request)
            return FakeResponse()

        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ, env, clear=True
        ), patch("bridge_app.alerts.urlopen", side_effect=fake_urlopen):
            run_dir = Path(root) / "order_1001_line_2002"
            first = notify_failure(
                run_dir,
                stage="customer_pdf_delivery",
                status="DELIVERY_ERROR",
                detail="Could not email customer@example.com with resend-secret",
                order_name="#1001",
            )
            second = notify_failure(
                run_dir,
                stage="customer_pdf_delivery",
                status="DELIVERY_ERROR",
                detail="Could not email customer@example.com with resend-secret",
                order_name="#1001",
            )

        self.assertEqual(first["status"], "SENT")
        self.assertEqual(second["status"], "SENT")
        self.assertEqual(len(captured), 1)
        payload = json.loads(captured[0].data.decode("utf-8"))
        self.assertEqual(payload["to"], ["owner@example.com"])
        self.assertIn("#1001", payload["html"])
        self.assertNotIn("customer@example.com", payload["html"])
        self.assertNotIn("resend-secret", payload["html"])
        self.assertTrue(captured[0].get_header("Idempotency-key").startswith("blueprint-failure-"))

    def test_unconfigured_alert_logs_without_raising(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ, {}, clear=True
        ):
            result = notify_failure(
                Path(root) / "order_1001_line_2002",
                stage="blueprint_generation",
                status="ENGINE_ERROR",
                detail="test failure",
            )
        self.assertEqual(result, {"status": "NOT_CONFIGURED", "channels": []})

    def test_webhook_failure_is_isolated(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ,
            {"BLUEPRINT_FAILURE_ALERT_WEBHOOK_URL": "https://alerts.example/hook"},
            clear=True,
        ), patch("bridge_app.alerts.urlopen", side_effect=OSError("network down")):
            result = notify_failure(
                Path(root) / "order_1001_line_2002",
                stage="shopify_fulfillment",
                status="FULFILLMENT_ERROR",
                detail="temporary failure",
            )
        self.assertEqual(result["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
