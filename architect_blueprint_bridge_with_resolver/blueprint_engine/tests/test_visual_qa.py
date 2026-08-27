import tempfile
import unittest
from pathlib import Path

from architect_engine.renderer import _customer_text, render_pdf


class VisualQATests(unittest.TestCase):
    def test_customer_labels_are_removed_without_removing_chart_fact(self):
        self.assertEqual(
            _customer_text("Verified chart note — Sun: Scorpio — House 2."),
            "Sun: Scorpio — House 2.",
        )
        self.assertEqual(
            _customer_text("Validated synthesis aspect: Sun conjunct Mercury reinforces focus."),
            "Sun conjunct Mercury reinforces focus.",
        )

    def test_renderer_reports_clean_pages_and_keeps_heading_with_body(self):
        payload = {
            "sections": [{
                "title": "Your Blueprint",
                "status": "INCLUDED",
                "content": "INTRODUCTION\nThis is nearby body content. " * 60,
            }]
        }
        with tempfile.TemporaryDirectory() as tmp:
            pages, diagnostics = render_pdf(
                payload, str(Path(tmp) / "report.pdf"), return_diagnostics=True
            )
        self.assertGreaterEqual(pages, 1)
        self.assertEqual(diagnostics["blank_pages"], [])
        self.assertEqual(diagnostics["orphaned_headings"], [])
        self.assertEqual(diagnostics["unresolved_placeholders"], [])
        self.assertEqual(diagnostics["internal_terms"], [])
        self.assertEqual(diagnostics["raw_orb_values"], [])

    def test_keep_with_next_survives_page_balancing(self):
        payload={"sections":[{"title":"Relationship","status":"INCLUDED","content":
            ("OPENING\n"+("Opening paragraph text. "*150)+"\n\nCOMMUNICATION IN LOVE\n"+
             ("The first communication paragraph stays attached. "*12)+"\n\nWHAT YOU NEED\n"+
             ("The first needs paragraph stays attached. "*12))}]}
        with tempfile.TemporaryDirectory() as tmp:
            _,diagnostics=render_pdf(payload,str(Path(tmp)/"report.pdf"),return_diagnostics=True)
        self.assertEqual(diagnostics["orphaned_headings"],[])

    def test_renderer_flags_customer_facing_pipeline_artifacts(self):
        payload = {
            "sections": [{
                "title": "Your Blueprint",
                "status": "INCLUDED",
                "content": "A context payload leaked here with {{PLACEHOLDER}}.",
            }]
        }
        with tempfile.TemporaryDirectory() as tmp:
            _, diagnostics = render_pdf(
                payload, str(Path(tmp) / "report.pdf"), return_diagnostics=True
            )
        self.assertIn("context payload", diagnostics["internal_terms"])
        self.assertIn("{{PLACEHOLDER}}", diagnostics["unresolved_placeholders"])

    def test_renderer_flags_customer_name_and_raw_orb(self):
        payload = {
            "sections": [{
                "title": "Your Blueprint",
                "status": "INCLUDED",
                "content": "Prepared for CUSTOMER NAME. Sun conjunct Mercury, orb 3.63°.",
            }]
        }
        with tempfile.TemporaryDirectory() as tmp:
            _, diagnostics = render_pdf(
                payload, str(Path(tmp) / "report.pdf"), return_diagnostics=True
            )
        self.assertIn("CUSTOMER NAME", diagnostics["unresolved_placeholders"])
        self.assertIn("orb 3.63°", diagnostics["raw_orb_values"])


if __name__ == "__main__":
    unittest.main()
