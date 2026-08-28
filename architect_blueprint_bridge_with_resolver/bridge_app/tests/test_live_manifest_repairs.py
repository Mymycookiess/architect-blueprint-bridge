import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge_app.app import AIWriterRequest, ai_writer

from architect_engine.ai_writer_adapter import _extract_section
from architect_engine.context_builder import build_context
from architect_engine.qa import run_qa
from architect_engine.selector import select_sources
from architect_engine.writer import compose_report


REQUIRED_FINAL_SECTIONS = (
    "Personalized Action Plan",
    "Your First / Next Brick",
)
SYNTHESIS_SECTIONS = (
    "Your Inner Wiring",
    "Your Relationship Blueprint",
    "Your Career & Purpose Blueprint",
    "Your Growth Blueprint",
)


class LiveManifestRepairTests(unittest.TestCase):
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
        cls.chart = chart
        cls.config = config
        cls.selector = selector
        cls.context = build_context(chart, selector, "CTX_live_manifest_repairs")
        cls.good_report = compose_report(cls.context, "RPT_live_manifest_repairs")

    def test_all_six_live_failures_are_reproduced_and_repaired(self):
        report = copy.deepcopy(self.good_report)
        sections = {section["title"]: section for section in report["sections"]}

        for title in REQUIRED_FINAL_SECTIONS:
            sections[title]["status"] = "REVIEW_REQUIRED"
        for title in SYNTHESIS_SECTIONS:
            sections[title]["content"] = "This chapter considers the pattern in its life area."

        failed_qa = run_qa(
            self.chart,
            self.selector,
            self.context,
            report,
            self.config,
            rendered_pages=35,
            render_diagnostics={},
        )
        for title in REQUIRED_FINAL_SECTIONS:
            self.assertIn(f"Required final section did not render: {title}", failed_qa["issues"])
        for title in SYNTHESIS_SECTIONS:
            self.assertIn(
                f"{title}: fewer than two validated factors are integrated",
                failed_qa["issues"],
            )

        originals = {section["title"]: section for section in self.good_report["sections"]}
        for title in REQUIRED_FINAL_SECTIONS:
            repaired = _extract_section(
                {
                    **copy.deepcopy(originals[title]),
                    "status": "REVIEW_REQUIRED",
                },
                title,
            )
            self.assertEqual(repaired["status"], "INCLUDED")
            sections[title] = repaired

        for title in SYNTHESIS_SECTIONS:
            calls = []

            def fake_call(payload, output_kind, *, section_title=title):
                calls.append((payload, output_kind))
                if len(calls) == 1:
                    return {
                        "section_id": "generated",
                        "title": section_title,
                        "status": "INCLUDED",
                        "content": "This chapter considers the pattern in its life area.",
                        "evidence_refs": [],
                    }
                return copy.deepcopy(originals[section_title])

            request = AIWriterRequest(
                contract="Use only supplied validated facts.",
                report_id="RPT_live_manifest_repairs",
                personalization_context=self.context,
                section_name=title,
                section_word_target=640,
            )
            with patch("bridge_app.app.ARCHITECT_AI_TOKEN", "token"), patch(
                "bridge_app.app.OPENAI_API_KEY", "key"
            ), patch("bridge_app.app._call_openai", side_effect=fake_call):
                sections[title] = ai_writer(
                    request,
                    authorization=None,
                    x_architect_token="token",
                )

            self.assertEqual(len(calls), 2)
            self.assertIn(
                "rewrite the complete section so at least two are integrated",
                calls[1][0]["instructions"],
            )

        report["sections"] = [sections[section["title"]] for section in report["sections"]]
        repaired_qa = run_qa(
            self.chart,
            self.selector,
            self.context,
            report,
            self.config,
            rendered_pages=35,
            render_diagnostics={},
        )
        final_pass = (
            repaired_qa["status"] == "PASS"
            and repaired_qa["word_target"]["status"] == "PASS"
            and repaired_qa["page_target"]["status"] == "PASS"
            and repaired_qa["source_boundary"] == "PASS"
        )
        self.assertTrue(final_pass, repaired_qa)


if __name__ == "__main__":
    unittest.main()
