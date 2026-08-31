import json
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge_app.app import AIWriterRequest, ai_writer

from architect_engine.context_builder import build_context
from architect_engine.emotional_rules import section_emotional_rule_issues
from architect_engine.selector import select_sources
from architect_engine.synthesis import section_aspect_repetition_issues, section_synthesis_rule_issues


TITLES = (
    "Your Big Three",
    "Your Inner Wiring",
    "Your Relationship Blueprint",
    "Your Career & Purpose Blueprint",
    "Your Growth Blueprint",
    "Your Blueprint Summary",
)


class InnerWiringEmotionalRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine_dir = Path(__file__).resolve().parents[2] / "blueprint_engine"
        chart = json.loads(
            (engine_dir / "fixtures" / "T01_FULL_Architect_Chart_Record_CORRECTED.json").read_text()
        )
        config = json.loads((engine_dir / "config" / "pipeline_config.json").read_text())
        selector = select_sources(
            chart,
            str(engine_dir / "data" / "Architect_Detailed_Content_Library_v1.xlsx"),
            config["library_sheet"],
        )
        cls.context = build_context(chart, selector, "CTX_inner_wiring_live")
        cls.anchors = cls.context["chart_facts"]["synthesis_anchors"]

    def _request(self, title):
        return AIWriterRequest(
            contract="Use only supplied validated facts.",
            report_id="RPT_inner_wiring_live",
            personalization_context=self.context,
            section_name=title,
            section_word_target=640,
        )

    def _section(self, title, content):
        return {
            "section_id": "generated",
            "title": title,
            "status": "INCLUDED",
            "content": content,
            "evidence_refs": [],
        }

    def _factor_names(self, title):
        return [
            f'{factor["sign"]} {factor["label"]}'
            for factor in self.anchors[title]["factors"][:2]
        ]

    def _grounded_specific_content(self, title):
        first, second = self._factor_names(title)
        return (
            f"Your {first} and {second} shape the same inner conversation. "
            "You notice the pressure first as a conflict between what feels safe and what needs to be said. "
            "When stress rises, you protect time to think before you respond, especially when a quick decision "
            "would leave an important need unheard. In relationship, you decide what to reveal by watching "
            "whether the exchange feels secure enough for an honest response."
        )

    def test_live_style_first_draft_passes_emotional_specificity(self):
        for title in TITLES:
            with self.subTest(title=title):
                content = self._grounded_specific_content(title)
                calls = []

                def fake_call(payload, output_kind):
                    calls.append((payload, output_kind))
                    return self._section(title, content)

                with patch("bridge_app.app.ARCHITECT_AI_TOKEN", "token"), patch(
                    "bridge_app.app.OPENAI_API_KEY", "key"
                ), patch("bridge_app.app._call_openai", side_effect=fake_call):
                    result = ai_writer(
                        self._request(title),
                        authorization=None,
                        x_architect_token="token",
                    )

                self.assertEqual(len(calls), 1)
                self.assertEqual(section_emotional_rule_issues(title, result["content"]), [])
                self.assertEqual(
                    section_synthesis_rule_issues(title, result["content"], self.anchors[title]),
                    [],
                )
                self.assertIn("recognizable lived experience, not a trait list", calls[0][0]["instructions"])

    def test_emotional_failure_gets_targeted_complete_section_retry(self):
        for title in TITLES:
            with self.subTest(title=title):
                first, second = self._factor_names(title)
                weak = f"Your {first} and {second} operate as connected parts of this pattern."
                corrected = self._grounded_specific_content(title)
                calls = []

                def fake_call(payload, output_kind):
                    calls.append((payload, output_kind))
                    return self._section(title, weak if len(calls) == 1 else corrected)

                with patch("bridge_app.app.ARCHITECT_AI_TOKEN", "token"), patch(
                    "bridge_app.app.OPENAI_API_KEY", "key"
                ), patch("bridge_app.app._call_openai", side_effect=fake_call):
                    result = ai_writer(
                        self._request(title),
                        authorization=None,
                        x_architect_token="token",
                    )

                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[1][1], "section emotional revision")
                self.assertIn("failed emotional-specificity QA", calls[1][0]["instructions"])
                self.assertIn("concrete internal reactions and behavioral expression", calls[1][0]["instructions"])
                self.assertEqual(section_emotional_rule_issues(title, result["content"]), [])
                self.assertEqual(
                    section_synthesis_rule_issues(title, result["content"], self.anchors[title]),
                    [],
                )

    def test_repeated_inner_wiring_aspect_gets_targeted_revision(self):
        title = "Your Inner Wiring"
        anchor = self.anchors[title]
        aspect = anchor["aspects"][0]
        first, second = self._factor_names(title)
        aspect_name = f'{aspect["body_a"]} {aspect["type"]} {aspect["body_b"]}'
        repeated = (
            f"Your {first} and {second} describe connected inner reactions. {aspect_name} helps name that connection. "
            "You notice what feels safe before deciding what needs to be said.\n\n"
            f"Under pressure, {aspect_name} returns as the same pattern. You protect time to think before responding, "
            "especially when an important need could go unheard."
        )
        corrected = (
            f"Your {first} and {second} describe connected inner reactions. {aspect_name} helps name that connection. "
            "You notice what feels safe before deciding what needs to be said.\n\n"
            "Under pressure, this connection becomes a practical pause: you protect time to think before responding, "
            "especially when an important need could go unheard."
        )
        calls = []

        def fake_call(payload, output_kind):
            calls.append((payload, output_kind))
            return self._section(title, repeated if len(calls) == 1 else corrected)

        with patch("bridge_app.app.ARCHITECT_AI_TOKEN", "token"), patch(
            "bridge_app.app.OPENAI_API_KEY", "key"
        ), patch("bridge_app.app._call_openai", side_effect=fake_call):
            result = ai_writer(
                self._request(title),
                authorization=None,
                x_architect_token="token",
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][1], "section synthesis revision")
        self.assertIn("name each validated aspect in no more than one paragraph", calls[1][0]["instructions"])
        self.assertEqual(section_aspect_repetition_issues(title, result["content"], anchor), [])


if __name__ == "__main__":
    unittest.main()
