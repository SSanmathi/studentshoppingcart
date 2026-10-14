import unittest

from student_tools import (
    affordable_alternatives,
    build_budget_challenge,
    build_hostel_checklist,
    recommend_for_needs,
)


def product(product_id, name, price, category="Stationery", description="", **fields):
    return {
        "id": product_id,
        "name": name,
        "price": price,
        "effective_price": price,
        "category": category,
        "description": description,
        "stock": 5,
        "is_essential": 0,
        "subcategory": "",
        **fields,
    }


class StudentToolRecommendationTests(unittest.TestCase):
    def test_semester_kit_filters_by_need_and_boosts_relevant_department(self):
        products = [
            product(1, "Python Programming Textbook", 500, "Books", "Python programming guide"),
            product(2, "Bedsheet", 400, "Hostel Essentials", "Single hostel bedsheet"),
        ]

        recommendations = recommend_for_needs(
            products, ["revision"], department="Computer Science", semester=2
        )
        writing_recommendations = recommend_for_needs(
            products, ["computing"], department="Computer Science", semester=2
        )

        self.assertEqual(recommendations, [])
        self.assertIn(1, [item["id"] for item in writing_recommendations])
        self.assertIn("Matches:", writing_recommendations[0]["recommendation_reason"])

    def test_move_in_checklist_has_unique_item_keys_and_stocked_matches(self):
        products = [
            product(1, "Bedsheet - Single", 450, "Hostel Essentials", "Cotton bedsheet"),
            product(2, "Out of Stock Bedsheet", 200, "Hostel Essentials", "Bedsheet", stock=0),
        ]

        checklist = build_hostel_checklist(products)

        keys = [item["key"] for item in checklist]
        bedding = next(item for item in checklist if item["key"] == "bedding")
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual([item["id"] for item in bedding["products"]], [1])

    def test_budget_challenge_recommendations_fit_limit_and_match_purpose(self):
        products = [
            product(1, "Exam Pen Pack", 80, description="Pen and pencil for exams"),
            product(2, "Exam Notebook", 120, description="Notebook for exam revision"),
            product(3, "Hostel Bedsheet", 450, "Hostel Essentials", "Hostel bedding"),
        ]

        recommendations, selected_ids = build_budget_challenge(products, "exam", 150)
        selected = [item for item in recommendations if item["id"] in selected_ids]

        self.assertLessEqual(sum(item["effective_price"] for item in selected), 150)
        self.assertTrue(selected)
        self.assertNotIn(3, selected_ids)

    def test_affordable_alternatives_require_relevant_overlap(self):
        expensive = product(
            1, "Premium Gel Pen Set", 200, description="Smooth gel pens for handwritten class notes",
            subcategory="Writing Instruments",
        )
        relevant = product(
            2, "Gel Pen Pack", 90, description="Gel pens for handwritten class notes",
            subcategory="Writing Instruments",
        )
        unrelated = product(
            3, "Hostel Soap", 35, "Hostel Essentials", "Personal care item for hostel use"
        )

        alternatives = affordable_alternatives(expensive, [expensive, relevant, unrelated])

        self.assertEqual([item["id"] for item in alternatives], [2])
        self.assertEqual(alternatives[0]["price_difference"], 110)


if __name__ == "__main__":
    unittest.main()
