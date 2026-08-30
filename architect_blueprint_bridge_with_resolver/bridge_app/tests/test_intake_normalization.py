import unittest
from datetime import date

from bridge_app.intake_normalization import normalize_birth_date


class BirthDateNormalizationTests(unittest.TestCase):
    TODAY = date(2026, 8, 30)

    def test_zero_padded_two_digit_year_becomes_recent_past_century(self):
        self.assertEqual(
            normalize_birth_date("0099-04-04", today=self.TODAY),
            "1999-04-04",
        )

    def test_unpadded_two_digit_year_is_supported(self):
        self.assertEqual(
            normalize_birth_date("99-04-04", today=self.TODAY),
            "1999-04-04",
        )

    def test_recent_two_digit_year_uses_current_century(self):
        self.assertEqual(
            normalize_birth_date("04-06-12", today=self.TODAY),
            "2004-06-12",
        )

    def test_future_two_digit_year_rolls_back_one_century(self):
        self.assertEqual(
            normalize_birth_date("27-01-15", today=self.TODAY),
            "1927-01-15",
        )

    def test_valid_four_digit_year_is_unchanged(self):
        self.assertEqual(
            normalize_birth_date("1998-04-04", today=self.TODAY),
            "1998-04-04",
        )

    def test_invalid_and_future_dates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "valid calendar date"):
            normalize_birth_date("1998-02-30", today=self.TODAY)
        with self.assertRaisesRegex(ValueError, "cannot be in the future"):
            normalize_birth_date("2027-01-01", today=self.TODAY)


if __name__ == "__main__":
    unittest.main()
