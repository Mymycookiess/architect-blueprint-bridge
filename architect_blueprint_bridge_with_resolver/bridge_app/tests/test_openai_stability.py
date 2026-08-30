import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from fastapi import HTTPException

from bridge_app.app import _call_openai, _openai_retry_after_seconds


class OpenAIStabilityTests(unittest.TestCase):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def test_transient_upstream_failure_retries_then_succeeds(self):
        transient = HTTPError(
            "https://api.openai.com/v1/responses",
            429,
            "Too Many Requests",
            {"Retry-After": "7"},
            io.BytesIO(json.dumps({
                "error": {
                    "message": "Please retry later.",
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            }).encode("utf-8")),
        )
        success = self.Response({"output_text": '{"content":"complete"}'})

        with patch(
            "bridge_app.app.urlopen",
            side_effect=[transient, success],
        ) as request, patch("bridge_app.app.time_module.sleep") as sleep:
            result = _call_openai({"model": "test"}, "section")

        self.assertEqual(result, {"content": "complete"})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(7.0)

    def test_permanent_upstream_error_is_safe_and_not_retried(self):
        rejected = HTTPError(
            "https://api.openai.com/v1/responses",
            400,
            "Bad Request",
            {},
            io.BytesIO(json.dumps({
                "error": {
                    "message": "Unsupported request setting.",
                    "type": "invalid_request_error",
                    "request_payload": "customer-sensitive-value",
                }
            }).encode("utf-8")),
        )

        with patch("bridge_app.app.urlopen", side_effect=rejected) as request:
            with self.assertRaises(HTTPException) as raised:
                _call_openai({"secret": "must-not-appear"}, "section")

        self.assertEqual(request.call_count, 1)
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("HTTP 400", raised.exception.detail)
        self.assertNotIn("customer-sensitive-value", raised.exception.detail)
        self.assertNotIn("must-not-appear", raised.exception.detail)

    def test_retry_after_is_capped(self):
        self.assertEqual(_openai_retry_after_seconds({"Retry-After": "900"}), 60.0)


if __name__ == "__main__":
    unittest.main()
