from pathlib import Path
import json
import re
import unittest

from architect_engine.context_builder import build_context
from architect_engine.emotional_rules import (
    EMOTIONAL_SECTIONS,
    EXPERIENTIAL_MARKERS,
    report_emotional_rule_issues,
)
from architect_engine.selector import select_sources
from architect_engine.synthesis import report_synthesis_rule_issues
from architect_engine.writer import compose_report


class EmotionalSpecificityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_dir = Path(__file__).resolve().parents[1]
        cls.library = str(cls.engine_dir / "data" / "Architect_Detailed_Content_Library_v1.xlsx")

    def _build(self, fixture):
        chart = json.loads((self.engine_dir / "fixtures" / fixture).read_text())
        selector = select_sources(chart, self.library)
        context = build_context(chart, selector, "CTX_emotional")
        report = compose_report(context, "RPT_emotional")
        return chart, selector, context, report

    def test_emotional_chapters_contain_concrete_experiential_language(self):
        _, _, _, report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        self.assertEqual(report_emotional_rule_issues(report), [])
        sections = {section["title"]: section["content"] for section in report["sections"]}
        for title in EMOTIONAL_SECTIONS:
            with self.subTest(title=title):
                content = sections[title]
                markers = {
                    marker for marker in EXPERIENTIAL_MARKERS
                    if re.search(rf"\b{re.escape(marker)}\w*\b", content, re.I)
                }
                self.assertGreaterEqual(len(markers), 3)
                self.assertRegex(
                    content,
                    r"(?i)\byou\s+(?:feel|need|notice|protect|hide|trust|respond|react|decide|choose|settle|struggle|hold)\b",
                )

    def test_exact_moon_source_replaces_generic_only_description(self):
        chart, selector, _, report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        moon_sources = [
            source for source in selector["selected_sources"]
            if source["section_name"] == "Your Emotional World — Moon"
        ]
        self.assertTrue(any(source["source_priority_score"] == 170 for source in moon_sources))
        self.assertTrue(any("MOON_TAURUS" in source["source_content_id"] for source in moon_sources))
        moon = next(section["content"] for section in report["sections"] if section["title"] == "Your Emotional World — Moon")
        self.assertIn("You feel most secure when your environment is peaceful, predictable, and comfortable.", moon)
        self.assertIn(f'Your {chart["placements"]["moon"]["sign"]} Moon', moon)
        self.assertNotIn("This placement means", moon)
        self.assertNotIn("This placement suggests", moon)

    def test_emotional_specificity_remains_chart_and_source_grounded(self):
        _, selector, context, report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        selected_ids = {source["source_content_id"] for source in selector["selected_sources"]}
        used_ids = {
            evidence
            for section in report["sections"]
            for evidence in section.get("evidence_refs", [])
        }
        self.assertTrue(used_ids.issubset(selected_ids))
        self.assertEqual(report_synthesis_rule_issues(context, report), [])
        self.assertEqual(report_emotional_rule_issues(report), [])

    def test_diagnosis_trauma_and_fabricated_biography_are_rejected(self):
        _, _, _, report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        report["sections"][0]["content"] += "\nYour trauma began in childhood."
        issues = report_emotional_rule_issues(report)
        self.assertTrue(any("Unsupported emotional overreach" in issue for issue in issues))

    def test_partial_emotional_content_uses_only_available_factors(self):
        _, _, context, report = self._build("T02_PARTIAL_Chart_Record_SYNTHETIC.json")
        self.assertEqual(report_emotional_rule_issues(report), [])
        self.assertEqual(report_synthesis_rule_issues(context, report), [])
        big_three = next(section["content"] for section in report["sections"] if section["title"] == "Your Big Three")
        self.assertNotRegex(big_three, r"(?i)\b(?:rising|ascendant|house\s+\d+)\b")


if __name__ == "__main__":
    unittest.main()
