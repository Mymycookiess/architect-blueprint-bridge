import io
import json
import unittest
from contextlib import redirect_stdout
from urllib.error import HTTPError
from unittest.mock import patch

from architect_engine.ai_writer_adapter import _request_section_once


class AIWriterDiagnosticTests(unittest.TestCase):
    def test_422_detail_is_logged_for_the_correct_section_and_reraised(self):
        error = HTTPError(
            "https://example.invalid/ai-writer",
            422,
            "Unprocessable Entity",
            {},
            io.BytesIO(json.dumps({
                "detail": [{
                    "loc": ["body", "section_word_target"],
                    "msg": "Input should be a valid integer",
                    "type": "int_parsing",
                    "input": "customer-sensitive-value",
                }]
            }).encode("utf-8")),
        )
        output = io.StringIO()

        with patch(
            "architect_engine.ai_writer_adapter.urlopen",
            side_effect=error,
        ), redirect_stdout(output):
            with self.assertRaises(HTTPError) as raised:
                _request_section_once(
                    {"mode": "FULL"},
                    "RPT_test",
                    "https://example.invalid/ai-writer",
                    "secret-token",
                    "Your Inner Wiring",
                    draft={"content": "existing draft"},
                )

        self.assertIs(raised.exception, error)
        line = output.getvalue().strip()
        self.assertTrue(line.startswith("AI_WRITER_VALIDATION_FAILURE "))
        diagnostic = json.loads(line.split(" ", 1)[1])
        self.assertEqual(diagnostic["section"], "Your Inner Wiring")
        self.assertEqual(diagnostic["status"], 422)
        self.assertEqual(diagnostic["attempt"], "retry")
        self.assertEqual(diagnostic["detail"][0]["type"], "int_parsing")
        self.assertNotIn("customer-sensitive-value", line)
        self.assertNotIn("secret-token", line)

    def test_bridge_503_is_retried_without_regenerating_the_entire_report(self):
        transient = HTTPError(
            "https://example.invalid/ai-writer",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b'{"detail":"temporary upstream failure"}'),
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({
                    "title": "Your Inner Wiring",
                    "content": "A grounded replacement section.",
                    "evidence_refs": [],
                }).encode("utf-8")

        output = io.StringIO()
        with patch(
            "architect_engine.ai_writer_adapter.urlopen",
            side_effect=[transient, Response()],
        ) as request, patch(
            "architect_engine.ai_writer_adapter.time.sleep",
        ) as sleep, redirect_stdout(output):
            section = _request_section_once(
                {"mode": "FULL"},
                "RPT_test",
                "https://example.invalid/ai-writer",
                "secret-token",
                "Your Inner Wiring",
            )

        self.assertEqual(section["content"], "A grounded replacement section.")
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(2)
        self.assertIn('"status":503', output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())

    def test_bridge_502_is_not_retried_after_upstream_retries_are_exhausted(self):
        exhausted = HTTPError(
            "https://example.invalid/ai-writer",
            502,
            "Bad Gateway",
            {},
            io.BytesIO(b'{"detail":"OpenAI retries exhausted"}'),
        )

        with patch(
            "architect_engine.ai_writer_adapter.urlopen",
            side_effect=exhausted,
        ) as request, patch(
            "architect_engine.ai_writer_adapter.time.sleep",
        ) as sleep:
            with self.assertRaises(HTTPError):
                _request_section_once(
                    {"mode": "FULL"},
                    "RPT_test",
                    "https://example.invalid/ai-writer",
                    "secret-token",
                    "Your Inner Wiring",
                )

        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
