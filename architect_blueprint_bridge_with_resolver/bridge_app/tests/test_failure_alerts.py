import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
