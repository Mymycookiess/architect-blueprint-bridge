from pathlib import Path
import json
import unittest

from architect_engine.content_rules import (
    ACTION_PLAN_SECTION,
    FIRST_BRICK_SECTION,
    action_plan_headings,
    report_content_rule_issues,
    section_content_rule_issues,
    section_writing_rules,
)
from architect_engine.context_builder import build_context
from architect_engine.selector import select_sources
from architect_engine.writer import compose_report


class ActionPlanContentRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_dir = Path(__file__).resolve().parents[1]
        cls.library = str(cls.engine_dir / "data" / "Architect_Detailed_Content_Library_v1.xlsx")

    def _report_from_fixture(self, fixture_name):
        chart = json.loads((self.engine_dir / "fixtures" / fixture_name).read_text())
        selector = select_sources(chart, self.library)
        context = build_context(chart, selector, "CTX_action_plan")
        return compose_report(context, "RPT_action_plan")

    def test_full_and_partial_reports_keep_action_plan_structure_in_final_section(self):
        for fixture in (
            "T01_FULL_Architect_Chart_Record_CORRECTED.json",
            "T02_PARTIAL_Chart_Record_SYNTHETIC.json",
        ):
            with self.subTest(fixture=fixture):
                report = self._report_from_fixture(fixture)
                sections = {section["title"]: section for section in report["sections"]}
                self.assertEqual(report_content_rule_issues(report), [])
                self.assertEqual(sections[ACTION_PLAN_SECTION]["status"], "INCLUDED")
                self.assertEqual(sections[FIRST_BRICK_SECTION]["status"], "INCLUDED")

                for title, section in sections.items():
                    if title != ACTION_PLAN_SECTION:
                        self.assertEqual(action_plan_headings(section["content"]), [])

    def test_repeated_action_plan_headings_are_rejected_outside_dedicated_section(self):
        repeated = """Strengths
One.
Supporting Habits
Two.
Patterns to Watch
Three.
Challenge
Four.
Encouraging Message
Five.
Next Brick
Six."""
        self.assertEqual(section_content_rule_issues(ACTION_PLAN_SECTION, repeated), [])
        issues = section_content_rule_issues("Your Emotional World — Moon", repeated)
        self.assertTrue(any("Action Plan headings outside" in issue for issue in issues))

    def test_architect_reflection_is_limited_to_two_prompts_and_ninety_words(self):
        brief = """Architect Reflection
Where do you already honor this part of yourself?
What would change if you trusted it one step sooner?"""
        self.assertEqual(section_content_rule_issues("Your Core Identity — Sun", brief), [])

        long_reflection = "Architect Reflection\n" + " ".join(["notice"] * 91)
        self.assertTrue(any("exceeds 90 words" in issue for issue in section_content_rule_issues(
            "Your Core Identity — Sun", long_reflection
        )))
        checklist = "Architect Reflection\n- One\n- Two\n- Three"
        self.assertTrue(any("large checklist" in issue for issue in section_content_rule_issues(
            "Your Core Identity — Sun", checklist
        )))

    def test_ai_rules_are_section_specific(self):
        early = section_writing_rules("How the World Meets You — Rising")
        action = section_writing_rules(ACTION_PLAN_SECTION)
        brick = section_writing_rules(FIRST_BRICK_SECTION)
        self.assertIn("Do not use Action Plan headings", early)
        self.assertIn("60–90 words maximum", early)
        self.assertIn("one dedicated full Action Plan", action)
        self.assertIn("Preserve this focused First / Next Brick", brick)


if __name__ == "__main__":
    unittest.main()
