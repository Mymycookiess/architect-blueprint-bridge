import base64
import json
import os
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs

from architect_engine import provider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ProviderAuthTests(unittest.TestCase):
    def test_subscription_credentials_use_basic_auth_and_form_body(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse({"ok": True})

        with patch.object(provider, "urlopen", fake_urlopen):
            result = provider._post_json(
                "https://json.astrologyapi.com/v1/planets/tropical",
                {"day": 4, "lat": 36.17},
                "customer-id",
                "subscription-key",
            )

        request = captured["request"]
        expected = base64.b64encode(b"customer-id:subscription-key").decode("ascii")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Authorization"), f"Basic {expected}")
        self.assertEqual(request.get_header("Content-type"), "application/x-www-form-urlencoded")
        self.assertIsNone(request.get_header("X-astrologyapi-key"))
        self.assertEqual(parse_qs(request.data.decode("utf-8")), {
            "day": ["4"],
            "lat": ["36.17"],
        })

    def test_wallet_access_token_uses_custom_header_and_json(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            return FakeResponse([{"name": "Sun"}])

        with patch.object(provider, "urlopen", fake_urlopen):
            result = provider._post_json(
                "https://json.astrologyapi.com/v1/planets/tropical",
                {"day": 4},
                "",
                "wallet-token",
            )

        request = captured["request"]
        self.assertEqual(result, [{"name": "Sun"}])
        self.assertEqual(request.get_header("X-astrologyapi-key"), "wallet-token")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"day": 4})

    def test_stale_user_id_falls_back_to_access_token(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            if len(requests) == 1:
                raise HTTPError(
                    request.full_url,
                    405,
                    "Method Not Allowed",
                    {},
                    BytesIO(b'{"message":"wrong auth contract"}'),
                )
            return FakeResponse({"ok": True})

        with patch.object(provider, "urlopen", fake_urlopen):
            result = provider._post_json(
                "https://example.test/v1/test",
                {"day": 4},
                "old-id",
                "token",
            )

        self.assertEqual(result, {"ok": True})
        self.assertTrue(requests[0].get_header("Authorization", "").startswith("Basic "))
        self.assertEqual(requests[1].get_header("X-astrologyapi-key"), "token")

    def test_credentials_accept_both_modes_and_normalize_v1(self):
        config = {
            "provider": {
                "base_url_env": "TEST_ASTROLOGY_BASE",
                "user_id_env": "TEST_ASTROLOGY_USER",
                "api_key_env": "TEST_ASTROLOGY_KEY",
            }
        }
        env = {
            "TEST_ASTROLOGY_BASE": "https://json.astrologyapi.com/v1/",
            "TEST_ASTROLOGY_USER": " customer-id ",
            "TEST_ASTROLOGY_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            credentials = provider._creds(config)

        self.assertEqual(credentials, (
            "https://json.astrologyapi.com",
            "customer-id",
            "secret",
        ))


if __name__ == "__main__":
    unittest.main()
