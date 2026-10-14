import unittest
from datetime import datetime

from pricing import calculate_product_price


NOW = datetime(2026, 10, 14, 12, 0, 0)


def offer(offer_type, value, min_quantity=1, starts_at="2026-10-01 00:00:00",
          ends_at="2026-12-31 23:59:59", is_active=1):
    return {
        "title": "Test offer",
        "offer_type": offer_type,
        "value": value,
        "min_quantity": min_quantity,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "is_active": is_active,
    }


class ProductPricingTests(unittest.TestCase):
    def test_no_offer_keeps_list_price(self):
        result = calculate_product_price(200, now=NOW)

        self.assertEqual(result["effective_price"], 200)
        self.assertEqual(result["subtotal"], 200)
        self.assertEqual(result["discount_amount"], 0)
        self.assertIsNone(result["applied_offer"])

    def test_percentage_discount_calculates_amount_and_final_price(self):
        result = calculate_product_price(200, [offer("percentage", 10)], now=NOW)

        self.assertEqual(result["discount_amount"], 20)
        self.assertEqual(result["effective_price"], 180)
        self.assertEqual(result["total"], 180)
        self.assertEqual(result["discount_percentage"], 10)

    def test_fixed_discount_applies_per_unit_and_scales_with_quantity(self):
        result = calculate_product_price(100, [offer("fixed", 15)], quantity=3, now=NOW)

        self.assertEqual(result["discount_amount"], 45)
        self.assertEqual(result["effective_price"], 85)
        self.assertEqual(result["total"], 255)

    def test_expired_or_inactive_offer_is_not_applied(self):
        expired = offer("percentage", 50, ends_at="2026-10-13 23:59:59")
        inactive = offer("fixed", 30, is_active=0)

        result = calculate_product_price(100, [expired, inactive], now=NOW)

        self.assertEqual(result["total"], 100)
        self.assertEqual(result["available_offers"], [])

    def test_quantity_offer_is_only_applied_when_requirement_is_met(self):
        quantity_offer = offer("fixed", 10, min_quantity=2)

        one_item = calculate_product_price(100, [quantity_offer], quantity=1, now=NOW)
        two_items = calculate_product_price(100, [quantity_offer], quantity=2, now=NOW)

        self.assertEqual(one_item["total"], 100)
        self.assertIsNone(one_item["applied_offer"])
        self.assertEqual(two_items["total"], 180)
        self.assertEqual(two_items["discount_amount"], 20)

    def test_multiple_offers_do_not_stack(self):
        offers = [offer("percentage", 10), offer("fixed", 30)]

        result = calculate_product_price(100, offers, now=NOW)

        self.assertEqual(result["discount_amount"], 30)
        self.assertEqual(result["total"], 70)
        self.assertEqual(result["applied_offer"]["offer_type"], "fixed")

    def test_invalid_offer_cannot_create_negative_or_full_discount(self):
        with self.assertRaises(ValueError):
            calculate_product_price(100, [offer("fixed", 101)], now=NOW)
        with self.assertRaises(ValueError):
            calculate_product_price(100, [offer("percentage", 100)], now=NOW)
        with self.assertRaises(ValueError):
            calculate_product_price(100, [offer("percentage", -1)], now=NOW)

    def test_invalid_product_price_and_quantity_are_rejected(self):
        with self.assertRaises(ValueError):
            calculate_product_price(-10, now=NOW)
        with self.assertRaises(ValueError):
            calculate_product_price(10, quantity=0, now=NOW)


if __name__ == "__main__":
    unittest.main()
