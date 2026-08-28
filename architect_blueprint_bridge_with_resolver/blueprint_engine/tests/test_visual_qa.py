import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from architect_engine.renderer import _customer_text, _display_birth_location, render_pdf


class VisualQATests(unittest.TestCase):
    def test_customer_front_matter_and_finished_titles_are_rendered(self):
        payload = {
            "mode": "FULL",
            "customer": {
                "name": "Paul Miller",
                "birth_date": "1984-06-12",
                "birth_time_local": "10:30",
                "birth_time_status": "KNOWN",
                "birth_location_display": "Oakland, California, USA",
            },
            "sections": [
                {"title": "Personalized Cover", "status": "INCLUDED", "content": "Internal cover draft"},
                {"title": "Birth Chart Snapshot", "status": "INCLUDED", "content": "**Sun:** Gemini."},
                {"title": "Your First / Next Brick", "status": "INCLUDED", "content": "**BRICK ONE - START**\nChoose one action."},
                {"title": "Your Next Chapter / Continue", "status": "INCLUDED", "content": "Return when your priorities change."},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.pdf"
            _, diagnostics = render_pdf(payload, str(path), return_diagnostics=True)
            text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        self.assertIn("YOUR BLUEPRINT JOURNEY", text)
        self.assertIn("Birth Information Used for Your Blueprint", text)
        self.assertIn("Paul Miller", text)
        self.assertIn("YOUR NEXT BRICK", text)
        self.assertIn("CONTINUE BUILDING", text)
        self.assertNotIn("PERSONALIZED COVER", text)
        self.assertNotIn("**", text)
        self.assertFalse(diagnostics["markdown_bold_markers"])

    def test_customer_identity_birth_details_and_sentence_dashes_are_polished(self):
        payload = {
            "mode": "FULL",
            "customer": {
                "name": "paul miller",
                "birth_date": "1997-06-04",
                "birth_time_local": "06:07",
                "birth_time_status": "KNOWN",
                "birth_location_display": "Los Angeles ca usa",
            },
            "sections": [{
                "title": "Birth Chart Snapshot",
                "status": "INCLUDED",
                "content": "Choose clarity—not confusion—and keep moving.",
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "polished-details.pdf"
            _, diagnostics = render_pdf(payload, str(path), return_diagnostics=True)
            text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        self.assertIn("Paul Miller", text)
        self.assertIn("June 4, 1997", text)
        self.assertIn("6:07 AM", text)
        self.assertIn("Los Angeles, California, USA", text)
        self.assertIn("clarity - not confusion - and", text)
        self.assertNotIn("clarity-not", text)
        self.assertEqual(diagnostics["joined_dash_words"], [])

    def test_single_markdown_emphasis_is_rendered_and_not_visible(self):
        payload = {
            "customer": {"name": "Paul Miller"},
            "sections": [{
                "title": "Your Next Chapter / Continue",
                "status": "INCLUDED",
                "content": "Ask: *What structure would help this effort last?*",
            }],
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "italic-check.pdf"
            _, diagnostics = render_pdf(payload, str(out), return_diagnostics=True)
            extracted = "\n".join(page.extract_text() or "" for page in PdfReader(out).pages)
        self.assertNotIn("*", extracted)
        self.assertFalse(diagnostics["markdown_emphasis_markers"])

    def test_big_three_glance_and_customer_friendly_location(self):
        payload = {
            "mode": "FULL",
            "customer": {
                "name": "Elizabeth Hunter",
                "birth_date": "1998-04-04",
                "birth_time_local": "19:53",
                "birth_time_status": "KNOWN",
                "birth_location_display": "Las Vegas USA",
            },
            "chart_summary": {
                "sun": {"sign": "Aries", "house": 6},
                "moon": {"sign": "Leo", "house": 9},
                "rising": {"sign": "Scorpio"},
            },
            "sections": [{
                "title": "Birth Chart Snapshot",
                "status": "INCLUDED",
                "content": "These placements form the foundation of your Blueprint.",
            }],
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "big-three-check.pdf"
            render_pdf(payload, str(out))
            extracted = "\n".join(page.extract_text() or "" for page in PdfReader(out).pages)
        self.assertEqual(_display_birth_location("Las Vegas USA"), "Las Vegas, Nevada, USA")
        self.assertIn("Your Big Three at a Glance", extracted)
        self.assertIn("Aries · House 6", extracted)
        self.assertIn("Leo · House 9", extracted)
        self.assertIn("Scorpio", extracted)

    def test_major_chapters_share_a_page_when_space_is_available(self):
        payload = {
            "customer": {"name": "Paul Miller"},
            "sections": [
                {
                    "title": "Your Relationship Blueprint",
                    "status": "INCLUDED",
                    "content": "Connection becomes clearer through honest communication. " * 20,
                },
                {
                    "title": "Your Career & Purpose Blueprint",
                    "status": "INCLUDED",
                    "content": "Purpose grows through focused contribution. " * 10,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "balanced-chapters.pdf"
            pages, _ = render_pdf(payload, str(path), return_diagnostics=True)
        self.assertEqual(pages, 3)

    def test_customer_pdf_embeds_spacing_safe_fonts(self):
        payload = {
            "mode": "FULL",
            "customer": {"name": "Paul Miller"},
            "sections": [
                {"title": "Welcome to Your Blueprint", "status": "INCLUDED", "content": "**Clear words** stay readable."},
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "font-check.pdf"
            render_pdf(payload, str(out))
            reader = PdfReader(str(out))
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertIn("Paul Miller", extracted)
            self.assertNotIn("**", extracted)
            base_fonts = set()
            for page in reader.pages:
                fonts = page["/Resources"].get("/Font", {})
                for font_ref in fonts.values():
                    font = font_ref.get_object()
                    base_fonts.add(str(font.get("/BaseFont", "")))
            self.assertTrue(any("Vera" in name for name in base_fonts), base_fonts)
            self.assertFalse(any("Times" in name for name in base_fonts), base_fonts)

    def test_markdown_qa_checks_rendered_pdf_not_source(self):
        payload = {
            "sections": [{
                "title": "Personalized Action Plan",
                "status": "INCLUDED",
                "content": "**A bold heading** becomes real formatting.",
            }]
        }
        with tempfile.TemporaryDirectory() as td:
            _, diagnostics = render_pdf(
                payload, str(Path(td) / "bold-check.pdf"), return_diagnostics=True
            )
        self.assertFalse(diagnostics["markdown_bold_markers"])
        self.assertFalse(diagnostics["markdown_emphasis_markers"])

    def test_renderer_removes_unmatched_markdown_delimiter(self):
        payload = {
            "sections": [{
                "title": "Personalized Action Plan",
                "status": "INCLUDED",
                "content": "A broken **bold marker remains visible.",
            }]
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "broken-bold-check.pdf"
            _, diagnostics = render_pdf(payload, str(out), return_diagnostics=True)
            extracted = "\n".join(
                page.extract_text() or "" for page in PdfReader(out).pages
            )
        self.assertFalse(diagnostics["markdown_bold_markers"])
        self.assertNotIn("**", extracted)

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
        self.assertEqual(diagnostics["sparse_pages"], [])
        self.assertEqual(diagnostics["orphaned_headings"], [])
        self.assertEqual(diagnostics["unresolved_placeholders"], [])
        self.assertEqual(diagnostics["internal_terms"], [])
        self.assertEqual(diagnostics["raw_orb_values"], [])

    def test_continue_chapter_does_not_leave_a_sparse_final_page(self):
        payload = {
            "customer": {"name": "Elizabeth Hunter"},
            "sections": [
                {
                    "title": "Your Blueprint Summary",
                    "status": "INCLUDED",
                    "content": "Your summary carries the central pattern forward. " * 75,
                },
                {
                    "title": "Your Next Chapter / Continue",
                    "status": "INCLUDED",
                    "content": "Continue building with awareness and steady structure. " * 58,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "balanced-ending.pdf"
            _, diagnostics = render_pdf(payload, str(out), return_diagnostics=True)
        self.assertEqual(diagnostics["sparse_pages"], [])

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
