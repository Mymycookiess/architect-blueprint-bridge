from pathlib import Path
import json
import unittest

from architect_engine.confidence_rules import (
    hedge_count,
    report_confidence_rule_issues,
    strengthen_supported_language,
)
from architect_engine.context_builder import build_context
from architect_engine.selector import select_sources
from architect_engine.writer import compose_report


class ConfidenceLanguageRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_dir = Path(__file__).resolve().parents[1]
        cls.library = str(cls.engine_dir / "data" / "Architect_Detailed_Content_Library_v1.xlsx")

    def _build(self, fixture):
        chart = json.loads((self.engine_dir / "fixtures" / fixture).read_text())
        selector = select_sources(chart, self.library)
        context = build_context(chart, selector, "CTX_confidence")
        report = compose_report(context, "RPT_confidence")
        raw_source = "\n".join(
            block["source_text"]
            for section in context["sections"].values()
            for block in section["source_blocks"]
        )
        return raw_source, report

    def test_repetitive_hedging_is_substantially_reduced(self):
        for fixture in (
            "T01_FULL_Architect_Chart_Record_CORRECTED.json",
            "T02_PARTIAL_Chart_Record_SYNTHETIC.json",
        ):
            with self.subTest(fixture=fixture):
                raw, report = self._build(fixture)
                finished = "\n".join(section["content"] for section in report["sections"])
                self.assertLessEqual(hedge_count(finished), int(hedge_count(raw) * 0.40))
                self.assertEqual(report_confidence_rule_issues(report), [])

    def test_supported_interpretations_use_direct_language(self):
        weak = (
            "This may suggest emotional steadiness. "
            "This placement can offer insight into your values. "
            "Your Blueprint may help you recognize the pattern."
        )
        strengthened = strengthen_supported_language(weak)
        self.assertEqual(
            strengthened,
            "This shows emotional steadiness. "
            "This placement offers insight into your values. "
            "Your Blueprint helps you recognize the pattern.",
        )

    def test_partial_limitations_appear_once_in_front_matter(self):
        _, report = self._build("T02_PARTIAL_Chart_Record_SYNTHETIC.json")
        sections = {section["title"]: section["content"] for section in report["sections"]}
        welcome = sections["Welcome to Your Blueprint"]
        self.assertEqual(welcome.count("Chart scope:"), 1)
        self.assertIn("birth time is unknown", welcome)
        self.assertIn("Rising and houses are intentionally omitted", welcome)
        elsewhere = "\n".join(
            content for title, content in sections.items()
            if title != "Welcome to Your Blueprint"
        )
        self.assertNotIn("Chart scope:", elsewhere)

    def test_prohibited_deterministic_language_is_rejected(self):
        _, report = self._build("T01_FULL_Architect_Chart_Record_CORRECTED.json")
        report["sections"][0]["content"] += "\nYou will definitely achieve this."
        issues = report_confidence_rule_issues(report)
        self.assertTrue(any("Prohibited deterministic phrase" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
