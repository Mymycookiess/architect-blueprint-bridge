import io
import json
import unittest
from contextlib import redirect_stdout

from bridge_app.app import _log_manifest_failures


class ManifestFailureLoggingTests(unittest.TestCase):
    def test_failed_manifest_reasons_are_emitted_to_service_stdout(self):
        manifest = {
            "status": "REVIEW_REQUIRED",
            "customer": "Sensitive Customer",
        }
        qa = {
            "status": "FIX",
            "issues": [
                "Your Big Three: insufficient concrete emotional language for Sensitive Customer",
            ],
            "word_count": 8200,
            "word_target": {
                "min": 8500,
                "max": 11500,
                "status": "REVIEW_REQUIRED",
            },
            "page_target": {
                "min": 30,
                "max": 45,
                "actual": 29,
                "status": "REVIEW_REQUIRED",
            },
            "source_boundary": "PASS",
        }
        output = io.StringIO()

        with redirect_stdout(output):
            _log_manifest_failures(manifest, qa)

        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        records = []
        for line in lines:
            self.assertTrue(line.startswith("BLUEPRINT_MANIFEST_FAILURE "))
            records.append(json.loads(line.split(" ", 1)[1]))

        by_check = {record["check"]: record for record in records}
        self.assertEqual(by_check["qa_issue"]["manifest_status"], "REVIEW_REQUIRED")
        self.assertEqual(by_check["qa_issue"]["section"], "Your Big Three")
        self.assertEqual(by_check["qa_issue"]["expected"], "no QA issues")
        self.assertEqual(by_check["word_target"]["actual"], 8200)
        self.assertEqual(by_check["word_target"]["expected"], "8500 <= words <= 11500")
        self.assertEqual(by_check["page_target"]["actual"], 29)
        self.assertEqual(by_check["page_target"]["expected"], "30 <= pages <= 45")
        self.assertNotIn("Sensitive Customer", output.getvalue())


if __name__ == "__main__":
    unittest.main()
