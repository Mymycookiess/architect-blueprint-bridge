import io
import json
import unittest
from contextlib import redirect_stdout

from bridge_app.app import _relay_ai_writer_validation_failures


class AIWriterDiagnosticRelayTests(unittest.TestCase):
    def test_422_is_relayed_to_service_stdout_with_only_allowed_fields(self):
        child_diagnostic = {
            "section": "Your Inner Wiring",
            "status": 422,
            "detail": [{
                "loc": ["body", "section_word_target"],
                "msg": "Input should be a valid integer",
                "type": "int_parsing",
            }],
            "attempt": "retry",
            "request_payload": "must-not-be-relayed",
        }
        child_stdout = "customer output must stay captured\n" + (
            "AI_WRITER_VALIDATION_FAILURE "
            + json.dumps(child_diagnostic, separators=(",", ":"))
        )
        output = io.StringIO()

        with redirect_stdout(output):
            _relay_ai_writer_validation_failures(child_stdout)

        line = output.getvalue().strip()
        self.assertTrue(line.startswith("AI_WRITER_VALIDATION_FAILURE "))
        relayed = json.loads(line.split(" ", 1)[1])
        self.assertEqual(
            set(relayed),
            {"section", "status", "detail", "attempt"},
        )
        self.assertEqual(relayed["section"], "Your Inner Wiring")
        self.assertEqual(relayed["status"], 422)
        self.assertEqual(relayed["attempt"], "retry")
        self.assertNotIn("customer output", line)
        self.assertNotIn("must-not-be-relayed", line)


if __name__ == "__main__":
    unittest.main()
