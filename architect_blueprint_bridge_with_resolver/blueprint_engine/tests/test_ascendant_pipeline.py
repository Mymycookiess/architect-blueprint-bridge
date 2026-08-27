from pathlib import Path
import unittest

from architect_engine.context_builder import build_context
from architect_engine.normalizer import normalize_provider_bundle
from architect_engine.qa import run_qa
from architect_engine.selector import select_sources
from architect_engine.writer import compose_report


class AscendantPipelineRegressionTests(unittest.TestCase):
    def setUp(self):
        self.intake = {
            "customer_name": "Rising Regression",
            "birth_date": "1996-10-27",
            "birth_time": "02:18",
            "birth_time_status": "KNOWN",
            "birth_location": "Oakland, California, USA",
        }
        self.raw = {
            "planets": [
                {"name": "Sun", "sign": "Scorpio", "full_degree": 214.0},
                {"name": "Moon", "sign": "Taurus", "full_degree": 44.0},
            ],
            "houses": [
                {"house_id": house, "start_degree": (155.5 + (house - 1) * 30) % 360}
                for house in range(1, 13)
            ],
            "ascendant": 12.0,
        }

    def test_astrologyapi_houses_feed_rising_big_three_and_payload(self):
        chart = normalize_provider_bundle(self.raw, self.intake, "ACR_rising")

        self.assertEqual([h["house"] for h in chart["houses"]], list(range(1, 13)))
        self.assertEqual(chart["houses"][0]["cusp_absolute_longitude"], 155.5)
        self.assertEqual(chart["angles"]["ascendant"]["absolute_longitude"], 155.5)
        self.assertEqual(chart["angles"]["ascendant"]["sign"], "Virgo")
        self.assertTrue(chart["availability"]["rising"])
        self.assertTrue(chart["availability"]["houses"])

        engine_dir = Path(__file__).resolve().parents[1]
        selector = select_sources(
            chart,
            str(engine_dir / "data" / "Architect_Detailed_Content_Library_v1.xlsx"),
        )
        context = build_context(chart, selector, "CTX_rising")
        report = compose_report(context, "RPT_rising")
        sections = {section["title"]: section for section in report["sections"]}

        self.assertEqual(context["chart_facts"]["angles"]["ascendant"]["sign"], "Virgo")
        self.assertIn("Virgo Rising", sections["How the World Meets You — Rising"]["content"])
        self.assertIn("Virgo", sections["Your Big Three"]["content"])
        self.assertEqual(report["mode"], "FULL")

    def test_full_mode_requires_exactly_twelve_valid_houses(self):
        for houses in (self.raw["houses"][:-1], self.raw["houses"][:-1] + [self.raw["houses"][0]]):
            with self.subTest(houses=len(houses)):
                chart = normalize_provider_bundle({**self.raw, "houses": houses}, self.intake, "ACR_invalid")
                self.assertEqual(chart["record_status"], "REVIEW_REQUIRED")
                self.assertEqual(chart["calculation"]["validation_status"], "REVIEW_REQUIRED")
                self.assertFalse(chart["availability"]["rising"])
                self.assertFalse(chart["availability"]["houses"])
                self.assertIsNone(chart["angles"]["ascendant"]["absolute_longitude"])
                qa = run_qa(
                    chart,
                    {"status": "VALID"},
                    {"context_status": "VALID", "source_trace": []},
                    {"mode": "FULL", "sections": []},
                    {"report": {"mode_full_word_min": 0, "mode_full_word_max": 0,
                                "mode_partial_word_min": 0, "mode_partial_word_max": 0,
                                "mode_full_page_min": 0, "mode_full_page_max": 0,
                                "mode_partial_page_min": 0, "mode_partial_page_max": 0}},
                )
                self.assertEqual(qa["status"], "FIX")
                self.assertIn("FULL mode missing Ascendant", qa["issues"])
                self.assertIn("FULL mode missing or invalid houses", qa["issues"])

    def test_partial_mode_remains_gated(self):
        partial = {**self.intake, "birth_time": None, "birth_time_status": "UNKNOWN"}
        chart = normalize_provider_bundle(self.raw, partial, "ACR_partial")
        self.assertEqual(chart["calculation"]["mode"], "PARTIAL")
        self.assertFalse(chart["availability"]["rising"])
        self.assertFalse(chart["availability"]["houses"])
        self.assertEqual(chart["houses"], [])
        self.assertIsNone(chart["angles"]["ascendant"]["absolute_longitude"])


if __name__ == "__main__":
    unittest.main()
