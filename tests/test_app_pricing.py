import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as student_cart
from database import get_db_connection, init_db


class CartOfferIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "student-cart-test.db")
        init_db(self.database_path)
        self.connection_factory = patch(
            "app.get_db_connection",
            side_effect=lambda: get_db_connection(self.database_path),
        )
        self.connection_factory.start()

        student_cart.app.config.update(
            TESTING=True,
            STUDENT_CART_DATABASE_INITIALIZED=True,
        )
        connection = sqlite3.connect(self.database_path)
        cursor = connection.execute(
            "INSERT INTO users (full_name, email, password_hash, college_name) VALUES (?, ?, ?, ?)",
            ("Test Student", "test@example.com", "not-used", "Test College"),
        )
        self.user_id = cursor.lastrowid
        products = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT name, id FROM products WHERE name IN (?, ?)",
                ("Gel Pen Pack", "A4 Ruled Notebook"),
            )
        }
        gel_pen_id = products["Gel Pen Pack"]
        notebook_id = products["A4 Ruled Notebook"]
        connection.execute(
            "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, 1)",
            (self.user_id, gel_pen_id),
        )
        connection.execute(
            "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, 2)",
            (self.user_id, notebook_id),
        )
        connection.commit()
        connection.close()

        self.client = student_cart.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["_csrf_token"] = "test-csrf-token"

    def tearDown(self):
        self.connection_factory.stop()
        student_cart.app.config["STUDENT_CART_DATABASE_INITIALIZED"] = False
        self.temp_dir.cleanup()

    def test_cart_page_and_checkout_use_the_same_recalculated_offers(self):
        cart_response = self.client.get("/cart")
        self.assertEqual(cart_response.status_code, 200)
        self.assertIn(b"Student Cart demo offer: 10% off", cart_response.data)
        self.assertIn(b"Delivery charge", cart_response.data)
        connection = sqlite3.connect(self.database_path)
        expected_subtotal = connection.execute(
            "SELECT SUM(p.price * ci.quantity) FROM cart_items ci JOIN products p ON p.id = ci.product_id WHERE ci.user_id = ?",
            (self.user_id,),
        ).fetchone()[0]
        connection.close()
        self.assertIn(f"₹{expected_subtotal:.2f}".encode(), cart_response.data)

        checkout_response = self.client.post(
            "/checkout",
            data={
                "csrf_token": "test-csrf-token",
                "delivery_type": "pickup",
                "payment_method": "cod",
            },
            follow_redirects=True,
        )
        self.assertEqual(checkout_response.status_code, 200)
        self.assertIn(b"Order confirmed", checkout_response.data)

        connection = sqlite3.connect(self.database_path)
        order = connection.execute(
            "SELECT subtotal, discount_amount, total_amount FROM orders WHERE user_id = ?",
            (self.user_id,),
        ).fetchone()
        order_items = connection.execute(
            "SELECT p.name, quantity, unit_price, discount_applied FROM order_items oi JOIN products p ON p.id = oi.product_id ORDER BY p.name"
        ).fetchall()
        remaining_cart_items = connection.execute(
            "SELECT COUNT(*) FROM cart_items WHERE user_id = ?",
            (self.user_id,),
        ).fetchone()[0]
        connection.close()

        self.assertIsNotNone(order)
        self.assertEqual(order, (330.0, 29.0, 301.0))
        self.assertEqual(len(order_items), 2)
        self.assertEqual(remaining_cart_items, 0)
        self.assertEqual(order_items, [
            ("A4 Ruled Notebook", 2, 110.0, 20.0),
            ("Gel Pen Pack", 1, 81.0, 9.0),
        ])

    def test_demo_catalogue_prices_are_distinct(self):
        connection = sqlite3.connect(self.database_path)
        product_count, distinct_price_count = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT price) FROM products"
        ).fetchone()
        connection.close()

        self.assertEqual(product_count, distinct_price_count)

    def test_student_planner_pages_render_from_catalogue_data(self):
        for route, expected in (
            ("/kit-planner?department=Computer+Science&semester=3&needs=writing&kit_budget=250", b"Smart Semester Kit"),
            ("/hostel-move-in", b"Hostel Move-In Planner"),
            ("/budget-challenge?purpose=exam&budget=300", b"Student Budget Challenge"),
            ("/compare", b"Compare products"),
        ):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.data)

    def test_semester_kit_enforces_the_submitted_budget_on_server(self):
        connection = sqlite3.connect(self.database_path)
        product_id = connection.execute(
            "SELECT id FROM products WHERE name = 'Introduction to Algorithms'"
        ).fetchone()[0]
        connection.close()

        response = self.client.post(
            "/kit-planner",
            data={
                "department": "Computer Science",
                "semester": "3",
                "kit_budget": "100",
                "needs": ["writing"],
                "product_ids": [str(product_id)],
                "csrf_token": "test-csrf-token",
            },
        )
        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        count = connection.execute(
            "SELECT COUNT(*) FROM cart_items WHERE user_id = ?",
            (self.user_id,),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(count, 2)

    def test_hostel_move_in_owned_items_are_removed_from_server_estimate(self):
        before = self.client.get("/hostel-move-in")
        after = self.client.get("/hostel-move-in?owned_items=bedding")

        self.assertEqual(before.status_code, 200)
        self.assertEqual(after.status_code, 200)
        self.assertIn(b'data-estimated-price="450.0"', before.data)
        self.assertIn(b'data-estimated-price="0.0"', after.data)
        self.assertIn(b'value="bedding" checked', after.data)

    def test_budget_challenge_rejects_a_basket_over_the_limit(self):
        connection = sqlite3.connect(self.database_path)
        product_id = connection.execute(
            "SELECT id FROM products WHERE name = 'Introduction to Algorithms'"
        ).fetchone()[0]
        connection.close()

        response = self.client.post(
            "/budget-challenge",
            data={
                "purpose": "exam",
                "budget": "100",
                "product_ids": [str(product_id)],
                "csrf_token": "test-csrf-token",
            },
        )
        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        count = connection.execute(
            "SELECT COUNT(*) FROM cart_items WHERE user_id = ?",
            (self.user_id,),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(count, 2)

    def test_comparison_requires_two_to_three_real_products(self):
        connection = sqlite3.connect(self.database_path)
        product_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT id FROM products WHERE name IN (?, ?) ORDER BY name",
                ("Gel Pen Pack", "A4 Ruled Notebook"),
            )
        ]
        connection.close()

        response = self.client.post(
            "/compare",
            data={
                "csrf_token": "test-csrf-token",
                "product_ids": product_ids,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Side-by-side comparison", response.data)
        self.assertIn(b"Gel Pen Pack", response.data)

    def test_catalogue_minimum_price_filter_uses_current_selling_price(self):
        response = self.client.get("/products?min_price=100&max_price=125")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"A4 Ruled Notebook", response.data)
        self.assertNotIn(b"Gel Pen Pack", response.data)


if __name__ == "__main__":
    unittest.main()
