import unittest

from architect_engine.qa import proofreading_issues
from architect_engine.writer import _proofread_customer_text


class V1ProofreadingTests(unittest.TestCase):
 def test_known_agreement_and_punctuation_errors_are_corrected(self):
    source = ("Different themes appears. Others offers insight. Together, these five areas helps. "
              "Choose goals that allows growth. This reveals what need development. "
              "Confirm your birth information .")
    result = _proofread_customer_text(source)
    self.assertIn("themes appear", result)
    self.assertIn("Others offer", result)
    self.assertIn("these five areas help", result)
    self.assertIn("goals that allow", result)
    self.assertIn("reveals what needs development", result)
    self.assertIn("birth information.", result)


 def test_only_identical_opening_or_adjacent_headings_are_removed(self):
    content = "YOUR INNER WIRING\nYOUR INNER WIRING\nHow Different Parts of You Operate\nBody copy."
    result = _proofread_customer_text(content, "YOUR INNER WIRING")
    self.assertTrue(result.startswith("How Different Parts of You Operate"))
    self.assertNotIn("YOUR INNER WIRING", result)
    self.assertIn("How Different Parts of You Operate", result)


 def test_proofreading_qa_rejects_customer_facing_copy_defects(self):
    report = {"sections": [{"title": "Example", "content": "Example\nThemes appears ."}]}
    issues = proofreading_issues(report)
    self.assertTrue(any("Copyediting error" in issue for issue in issues))
    self.assertTrue(any("Space before punctuation" in issue for issue in issues))
    self.assertTrue(any("Duplicate opening chapter heading" in issue for issue in issues))
