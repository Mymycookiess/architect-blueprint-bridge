import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from bridge_app.app import LocationResolveRequest, resolve_location_endpoint


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ShopifyLocationResolutionTests(unittest.TestCase):
    def test_shopify_style_location_resolves_in_full_and_partial_modes(self):
        def fake_urlopen(request, timeout):
            query = parse_qs(urlparse(request.full_url).query)
            self.assertEqual(query["name"], ["Los Angeles"])
            self.assertEqual(timeout, 20)
            return _Response({
                "results": [{
                    "name": "Los Angeles",
                    "admin1": "California",
                    "country": "United States",
                    "country_code": "US",
                    "latitude": 34.0522,
                    "longitude": -118.2437,
                    "timezone": "America/Los_Angeles",
                    "population": 3898747,
                }]
            })

        with patch("bridge_app.app.urlopen", side_effect=fake_urlopen):
            for birth_time in ("12:30", None):
                with self.subTest(birth_time=birth_time):
                    payload = resolve_location_endpoint(LocationResolveRequest(
                        birth_location="Los Angeles ca usa",
                        birth_date="1990-01-15",
                        birth_time=birth_time,
                    ))
                    self.assertEqual(payload["latitude"], 34.0522)
                    self.assertEqual(payload["longitude"], -118.2437)
                    self.assertEqual(payload["timezone"], "America/Los_Angeles")
                    self.assertEqual(payload["timezone_offset"], -8.0)


if __name__ == "__main__":
    unittest.main()
