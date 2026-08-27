from pathlib import Path
import json
import unittest

from architect_engine.context_builder import build_context
from architect_engine.repetition_rules import (
    meaningful_sentences,
    report_repetition_rule_issues,
    section_progression_rules,
)
from architect_engine.selector import select_sources
from architect_engine.writer import compose_report


class BlueprintRepetitionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_dir = Path(__file__).resolve().parents[1]
        cls.library = str(cls.engine_dir / "data" / "Architect_Detailed_Content_Library_v1.xlsx")

    def _build(self, fixture):
        chart = json.loads((self.engine_dir / "fixtures" / fixture).read_text())
        selector = select_sources(chart, self.library)
        context = build_context(chart, selector, "CTX_repetition")
        return compose_report(context, "RPT_repetition")

    def test_no_exact_meaningful_sentences_repeat_across_chapters(self):
        for fixture in (
            "T01_FULL_Architect_Chart_Record_CORRECTED.json",
            "T02_PARTIAL_Chart_Record_SYNTHETIC.json",
        ):
            with self.subTest(fixture=fixture):
                report = self._build(fixture)
                self.assertEqual(report_repetition_rule_issues(report), [])
                seen = {}
                for section in report["sections"]:
                    if section["status"] != "INCLUDED":
                        continue
                    for _, normalized in meaningful_sentences(section["content"]):
                        self.assertNotIn(normalized, seen)
                        seen[normalized] = section["title"]

    def test_reused_chart_factors_gain_distinct_life_area_applications(self):
        report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        sections = {section["title"]: section["content"] for section in report["sections"]}
        expected = {
            "Your Big Three": "Big Three synthesis:",
            "Your Career & Purpose Blueprint": "Career synthesis:",
            "Your Growth Blueprint": "Growth synthesis:",
            "Your Blueprint Summary": "Whole-chart synthesis:",
        }
        for title, prefix in expected.items():
            with self.subTest(title=title):
                self.assertIn("Scorpio Sun", sections[title])
                self.assertIn(prefix, sections[title])

    def test_summary_does_not_copy_earlier_meaningful_sentences(self):
        report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        sections = {section["title"]: section["content"] for section in report["sections"]}
        summary = {normalized for _, normalized in meaningful_sentences(sections["Your Blueprint Summary"])}
        earlier = {
            normalized
            for title, content in sections.items()
            if title != "Your Blueprint Summary"
            for _, normalized in meaningful_sentences(content)
        }
        self.assertFalse(summary & earlier)

    def test_duplicate_and_near_duplicate_core_insights_are_rejected(self):
        report = {
            "sections": [
                {"title": "Your Big Three", "status": "INCLUDED",
                 "content": "Big Three synthesis: Your inner needs and outward choices work together when pressure rises."},
                {"title": "Your Growth Blueprint", "status": "INCLUDED",
                 "content": "Growth synthesis: Your inner needs and outward choices work together whenever pressure rises."},
                {"title": "Your Blueprint Summary", "status": "INCLUDED",
                 "content": "Big Three synthesis: Your inner needs and outward choices work together when pressure rises."},
            ]
        }
        issues = report_repetition_rule_issues(report)
        self.assertTrue(any("Exact meaningful sentence repeated" in issue for issue in issues))
        self.assertTrue(any("Near-duplicate core insight" in issue for issue in issues))

    def test_progression_rules_require_new_context_for_callbacks(self):
        relationship = section_progression_rules("Your Relationship Blueprint")
        summary = section_progression_rules("Your Blueprint Summary")
        self.assertIn("new context, consequence, tension, choice, or application", relationship)
        self.assertIn("without copying", summary)


if __name__ == "__main__":
    unittest.main()
