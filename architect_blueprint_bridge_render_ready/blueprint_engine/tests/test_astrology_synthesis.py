from pathlib import Path
import json
import re
import unittest

from architect_engine.context_builder import build_context
from architect_engine.selector import select_sources
from architect_engine.synthesis import (
    SECTION_FACTORS,
    SYNTHESIS_PREFIXES,
    report_synthesis_rule_issues,
)
from architect_engine.writer import compose_report


class AstrologySynthesisRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_dir = Path(__file__).resolve().parents[1]
        cls.library = str(cls.engine_dir / "data" / "Architect_Detailed_Content_Library_v1.xlsx")

    def _build(self, fixture):
        chart = json.loads((self.engine_dir / "fixtures" / fixture).read_text())
        selector = select_sources(chart, self.library)
        context = build_context(chart, selector, "CTX_synthesis")
        report = compose_report(context, "RPT_synthesis")
        return chart, context, report

    def test_full_big_three_integrates_sun_moon_and_rising(self):
        _, context, report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        sections = {section["title"]: section for section in report["sections"]}
        content = sections["Your Big Three"]["content"]
        self.assertIn("Scorpio Sun", content)
        self.assertIn("Taurus Moon", content)
        self.assertIn("Virgo Rising", content)
        self.assertIn("Big Three synthesis:", content)
        self.assertEqual(report_synthesis_rule_issues(context, report), [])

    def test_partial_big_three_integrates_only_stable_sun_and_moon(self):
        _, context, report = self._build("T02_PARTIAL_Chart_Record_SYNTHETIC.json")
        sections = {section["title"]: section for section in report["sections"]}
        content = sections["Your Big Three"]["content"]
        self.assertIn("Taurus Sun", content)
        self.assertIn("Libra Moon", content)
        self.assertNotRegex(content, r"(?i)\b(?:rising|ascendant|house\s+\d+)\b")
        factors = context["chart_facts"]["synthesis_anchors"]["Your Big Three"]["factors"]
        self.assertEqual([factor["key"] for factor in factors], ["sun", "moon"])
        self.assertEqual(report_synthesis_rule_issues(context, report), [])

    def test_synthesis_heavy_chapters_combine_multiple_validated_factors(self):
        _, context, report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        sections = {section["title"]: section for section in report["sections"]}
        anchors = context["chart_facts"]["synthesis_anchors"]
        for title in SECTION_FACTORS:
            with self.subTest(title=title):
                factors = anchors[title]["factors"]
                self.assertGreaterEqual(len(factors), 2)
                referenced = [
                    factor for factor in factors
                    if f'{factor["sign"]} {factor["label"]}' in sections[title]["content"]
                ]
                self.assertGreaterEqual(len(referenced), 2)
        self.assertIn("show where these connected patterns become most visible", sections["Your Inner Wiring"]["content"])
        self.assertIn("The conjunction between Sun and Mercury", sections["Your Career & Purpose Blueprint"]["content"])

    def test_synthesis_anchors_introduce_no_unvalidated_factors_or_aspects(self):
        chart, context, _ = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        anchors = context["chart_facts"]["synthesis_anchors"]
        valid_planets = {
            key: (value.get("sign"), value.get("house"))
            for key, value in chart["placements"].items()
        }
        valid_angles = {
            "rising": chart["angles"]["ascendant"].get("sign"),
            "midheaven": chart["angles"]["midheaven"].get("sign"),
        }
        valid_aspects = {
            (aspect["body_a"], aspect["type"], aspect["body_b"])
            for aspect in chart["aspects"] if aspect.get("allowed_for_v1") is not False
        }
        for anchor in anchors.values():
            for factor in anchor["factors"]:
                if factor["key"] in valid_angles:
                    self.assertEqual(factor["sign"], valid_angles[factor["key"]])
                else:
                    self.assertEqual(
                        (factor["sign"], factor["house"]),
                        valid_planets[factor["key"]],
                    )
            for aspect in anchor["aspects"]:
                self.assertIn(
                    (aspect["body_a"], aspect["type"], aspect["body_b"]),
                    valid_aspects,
                )

    def test_exact_synthesis_text_is_unique_to_each_chapter(self):
        _, _, report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        seen = set()
        for section in report["sections"]:
            for paragraph in section["content"].split("\n\n"):
                text = paragraph.strip()
                if text.startswith(SYNTHESIS_PREFIXES):
                    self.assertNotIn(text, seen)
                    seen.add(text)
        self.assertGreaterEqual(len(seen), 6)


if __name__ == "__main__":
    unittest.main()
