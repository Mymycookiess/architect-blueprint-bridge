import unittest
from unittest.mock import patch

from bridge_app.app import AIWriterRequest, ai_writer


def _section(content):
    return {
        "section_id": "generated",
        "title": "generated",
        "status": "INCLUDED",
        "content": content,
        "evidence_refs": [],
    }


class AIWriterDisclaimerRevisionTests(unittest.TestCase):
    def _request(self, title, draft=None):
        return AIWriterRequest(
            contract="Use only supplied facts.",
            report_id="RPT_test",
            personalization_context={
                "mode": "FULL",
                "chart_facts": {},
                "customer": {"name": "Test"},
                "sections": {title: {"source_blocks": []}},
            },
            section_name=title,
            section_word_target=500,
            section_draft=draft,
        )

    def _run_with_rewrite(self, title, rejected, corrected):
        calls = []

        def fake_call(payload, output_kind):
            calls.append((payload, output_kind))
            return _section(rejected if len(calls) == 1 else corrected)

        with patch("bridge_app.app.ARCHITECT_AI_TOKEN", "token"), patch(
            "bridge_app.app.OPENAI_API_KEY", "key"
        ), patch("bridge_app.app._call_openai", side_effect=fake_call):
            result = ai_writer(
                self._request(title),
                authorization=None,
                x_architect_token="token",
            )

        self.assertEqual(result["content"], corrected)
        self.assertEqual(len(calls), 2)
        return calls

    def test_welcome_rewrites_you_might_before_validation(self):
        calls = self._run_with_rewrite(
            "Welcome to Your Blueprint",
            "As you read, you might recognize a familiar pattern.",
            "As you read, you may notice a familiar pattern.",
        )
        self.assertIn('"you might"', calls[1][0]["instructions"])

    def test_houses_rewrites_this_does_not_mean_before_validation(self):
        calls = self._run_with_rewrite(
            "Your Houses / Life Areas",
            "This does not mean every life area carries equal emphasis.",
            "Each life area carries its own degree of emphasis.",
        )
        self.assertIn('"this does not mean"', calls[1][0]["instructions"])

    def test_outer_retry_names_and_removes_the_draft_violation(self):
        calls = []

        def fake_call(payload, output_kind):
            calls.append((payload, output_kind))
            return _section("You may experience the pattern differently over time.")

        draft = _section("You might experience the pattern differently over time.")
        with patch("bridge_app.app.ARCHITECT_AI_TOKEN", "token"), patch(
            "bridge_app.app.OPENAI_API_KEY", "key"
        ), patch("bridge_app.app._call_openai", side_effect=fake_call):
            result = ai_writer(
                self._request("Welcome to Your Blueprint", draft=draft),
                authorization=None,
                x_architect_token="token",
            )

        self.assertEqual(len(calls), 1)
        self.assertIn(
            'The supplied draft failed disclaimer-language QA for: "you might"',
            calls[0][0]["instructions"],
        )
        self.assertNotIn("you might", result["content"].lower())


if __name__ == "__main__":
    unittest.main()
