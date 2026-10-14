import os
import re
import sqlite3
import tempfile
import unittest
from urllib.parse import unquote
from unittest.mock import patch

from werkzeug.security import check_password_hash

import app as student_cart
import database
from database import get_db_connection, init_db


class BackendIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "student_cart.db")
        self.product_count = init_db(self.database_path)
        self.connection_factory = patch(
            "app.get_db_connection",
            side_effect=lambda: get_db_connection(self.database_path),
        )
        self.connection_factory.start()
        self.config_patch = patch.dict(
            student_cart.app.config,
            TESTING=True,
            STUDENT_CART_DATABASE_INITIALIZED=True,
        )
        self.config_patch.start()
        self.client = student_cart.app.test_client()

    def tearDown(self):
        self.config_patch.stop()
        self.connection_factory.stop()
        self.temp_dir.cleanup()

    def csrf_from(self, response):
        match = re.search(
            rb'name="csrf_token" value="([^"]+)"',
            response.data,
        )
        self.assertIsNotNone(match, "Rendered form should contain a CSRF token.")
        return match.group(1).decode()

    def test_registration_login_product_cart_and_checkout_use_sqlite(self):
        login_form = self.client.get("/register")
        register_token = self.csrf_from(login_form)
        registration = self.client.post(
            "/register",
            data={
                "csrf_token": register_token,
                "name": "Demo Student",
                "email": "demo.student@example.edu",
                "password": "demo-password-123",
                "college_name": "Example College",
                "department": "Computer Science",
            },
        )
        self.assertEqual(registration.status_code, 302)

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        user = connection.execute(
            "SELECT * FROM users WHERE email = ?",
            ("demo.student@example.edu",),
        ).fetchone()
        self.assertEqual(user["full_name"], "Demo Student")
        self.assertEqual(user["department"], "Computer Science")
        self.assertNotEqual(user["password_hash"], "demo-password-123")
        self.assertTrue(check_password_hash(user["password_hash"], "demo-password-123"))
        user_id = user["id"]
        product = connection.execute(
            "SELECT id, name, stock, price FROM products WHERE name = ?",
            ("Blue Ballpoint Pen",),
        ).fetchone()
        initial_stock = product["stock"]
        connection.close()

        self.assertEqual(self.client.get("/api/health").json["database"], "available")
        self.assertEqual(self.client.get("/api/health").json["products"], self.product_count)
        products_response = self.client.get("/api/products?q=Blue+Ballpoint")
        self.assertEqual(products_response.status_code, 200)
        self.assertEqual(products_response.json[0]["name"], "Blue Ballpoint Pen")
        self.assertEqual(
            self.client.get(f"/api/products/{product['id']}").json["name"],
            "Blue Ballpoint Pen",
        )
        self.assertEqual(self.client.get("/api/cart").json["items"], [])

        dashboard = self.client.get("/dashboard")
        csrf = self.csrf_from(dashboard)
        logout = self.client.post(
            "/logout",
            data={"csrf_token": csrf},
        )
        self.assertEqual(logout.status_code, 302)
        login_form = self.client.get("/login")
        login = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf_from(login_form),
                "email": "demo.student@example.edu",
                "password": "demo-password-123",
            },
        )
        self.assertEqual(login.status_code, 302)
        csrf = self.csrf_from(self.client.get("/dashboard"))

        add_response = self.client.post(
            "/cart/add",
            data={
                "csrf_token": csrf,
                "product_id": product["id"],
                "quantity": "2",
            },
        )
        self.assertEqual(add_response.status_code, 302)
        self.assertEqual(
            self.client.get("/api/cart").json["items"][0]["quantity"],
            2,
        )

        update_response = self.client.post(
            "/cart",
            data={
                "csrf_token": csrf,
                "action": "update",
                "product_id": product["id"],
                "quantity": "3",
            },
        )
        self.assertEqual(update_response.status_code, 302)
        self.assertEqual(
            self.client.get("/api/cart").json["items"][0]["quantity"],
            3,
        )

        checkout = self.client.post(
            "/checkout",
            data={
                "csrf_token": csrf,
                "delivery_type": "invalid",
                "delivery_address": "",
                "payment_method": "cod",
            },
        )
        self.assertEqual(checkout.status_code, 200)
        self.assertIn(b"Please choose a valid delivery option", checkout.data)

        checkout = self.client.post(
            "/checkout",
            data={
                "csrf_token": csrf,
                "delivery_type": "delivery",
                "delivery_address": "a" * 501,
                "payment_method": "cod",
            },
        )
        self.assertEqual(checkout.status_code, 200)
        self.assertIn(b"Delivery address must be 500 characters or fewer", checkout.data)

        checkout = self.client.get("/checkout")
        self.assertEqual(checkout.status_code, 200)
        self.assertIn(b"No real payment will be processed", checkout.data)

        checkout = self.client.post(
            "/checkout",
            data={
                "csrf_token": csrf,
                "delivery_type": "pickup",
                "payment_method": "cod",
            },
            follow_redirects=True,
        )
        self.assertEqual(checkout.status_code, 200)
        self.assertIn(b"Order confirmed", checkout.data)

        connection = sqlite3.connect(self.database_path)
        order = connection.execute(
            "SELECT id, user_id, subtotal, discount_amount, total_amount FROM orders"
        ).fetchone()
        item = connection.execute(
            """
            SELECT product_name_at_purchase, quantity, unit_price, subtotal
            FROM order_items WHERE order_id = ?
            """,
            (order[0],),
        ).fetchone()
        remaining_stock = connection.execute(
            "SELECT stock FROM products WHERE id = ?",
            (product["id"],),
        ).fetchone()[0]
        cart_count = connection.execute(
            "SELECT COUNT(*) FROM cart_items WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(order[1:], (user_id, 75.0, 0.0, 75.0))
        self.assertEqual(item, ("Blue Ballpoint Pen", 3, 25.0, 75.0))
        self.assertEqual(remaining_stock, initial_stock - 3)
        self.assertEqual(cart_count, 0)
        self.assertEqual(self.client.get("/orders").status_code, 200)

        self.assertEqual(init_db(self.database_path), self.product_count)
        connection = sqlite3.connect(self.database_path)
        order_number = connection.execute(
            "SELECT order_id FROM orders WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0],
            1,
        )
        other_user_id = connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash, college_name)
            VALUES (?, ?, ?, ?)
            """,
            ("Other Student", "other.student@example.edu", "unused", "Other College"),
        ).lastrowid
        connection.close()
        other_client = student_cart.app.test_client()
        with other_client.session_transaction() as session:
            session["user_id"] = other_user_id
        private_order = other_client.get(f"/order-success/{order_number}")
        self.assertEqual(private_order.status_code, 302)
        self.assertIn("/orders", private_order.headers["Location"])

    def test_seeded_product_images_are_unique_local_assets(self):
        connection = sqlite3.connect(self.database_path)
        rows = connection.execute(
            "SELECT name, image_url, image_alt FROM products ORDER BY id"
        ).fetchall()
        connection.close()
        root = os.path.dirname(os.path.dirname(__file__))
        paths = []
        for name, image_url, image_alt in rows:
            self.assertTrue(image_url.startswith("/static/"), name)
            local_path = os.path.join(
                root,
                unquote(image_url.lstrip("/")).replace("/", os.sep),
            )
            self.assertTrue(os.path.isfile(local_path), f"{name}: {image_url}")
            self.assertTrue(image_alt.strip(), name)
            paths.append(image_url)
        self.assertEqual(len(paths), len(set(paths)))
        self.assertNotIn("/static/images/placeholder-product.svg", paths)

        for fallback_name in (
            "stationery-image-fallback.svg",
            "books-image-fallback.svg",
            "hostel-image-fallback.svg",
        ):
            with self.client.get(f"/static/images/{fallback_name}") as response:
                self.assertEqual(response.status_code, 200)

    def test_login_rejects_bad_credentials_and_posts_require_csrf(self):
        home = self.client.get("/")
        self.assertIn(b"public-navbar", home.data)
        self.assertIn(b"site-footer", home.data)

        response = self.client.post(
            "/register",
            data={
                "name": "No Token",
                "email": "no-token@example.edu",
                "password": "valid-password",
                "college_name": "Example College",
            },
        )
        self.assertEqual(response.status_code, 400)

        login_form = self.client.get("/login")
        csrf = self.csrf_from(login_form)
        response = self.client.post(
            "/login",
            data={
                "csrf_token": csrf,
                "email": "nobody@example.edu",
                "password": "incorrect",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid email or password", response.data)
        self.assertEqual(self.client.get("/api/cart").status_code, 401)

    def test_each_connection_enforces_foreign_keys_and_positive_cart_quantity(self):
        connection = get_db_connection(self.database_path)
        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (999, 999, 1)"
            )
        connection.close()

    def test_cart_rejects_invalid_and_over_stock_quantities(self):
        connection = sqlite3.connect(self.database_path)
        cursor = connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash, college_name)
            VALUES (?, ?, ?, ?)
            """,
            ("Cart Student", "cart.student@example.edu", "unused", "Example College"),
        )
        user_id = cursor.lastrowid
        product_id = connection.execute(
            "SELECT id FROM products WHERE name = ?",
            ("Blue Ballpoint Pen",),
        ).fetchone()[0]
        connection.execute(
            "UPDATE products SET stock = 1 WHERE id = ?",
            (product_id,),
        )
        connection.commit()
        connection.close()
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["_csrf_token"] = "cart-test-token"

        response = self.client.post(
            "/cart/add",
            data={
                "csrf_token": "cart-test-token",
                "product_id": str(product_id),
                "quantity": "2",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/api/cart").json["items"], [])

        self.client.post(
            "/cart/add",
            data={
                "csrf_token": "cart-test-token",
                "product_id": str(product_id),
                "quantity": "1",
            },
        )
        response = self.client.post(
            "/cart",
            data={
                "csrf_token": "cart-test-token",
                "action": "update",
                "product_id": str(product_id),
                "quantity": "2",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/api/cart").json["items"][0]["quantity"], 1)

        response = self.client.post(
            "/cart",
            data={
                "csrf_token": "cart-test-token",
                "action": "update",
                "product_id": str(product_id),
                "quantity": "not-a-number",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/api/cart").json["items"][0]["quantity"], 1)

        response = self.client.post(
            "/cart",
            data={
                "csrf_token": "cart-test-token",
                "action": "update",
                "product_id": str(product_id),
                "quantity": "0",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/api/cart").json["items"][0]["quantity"], 1)

        response = self.client.post(
            "/cart",
            data={
                "csrf_token": "cart-test-token",
                "action": "remove",
                "product_id": str(product_id),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/api/cart").json["items"], [])

    def test_checkout_insufficient_stock_does_not_create_partial_order(self):
        connection = sqlite3.connect(self.database_path)
        cursor = connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash, college_name)
            VALUES (?, ?, ?, ?)
            """,
            ("Stock Student", "stock.student@example.edu", "unused", "Example College"),
        )
        user_id = cursor.lastrowid
        product_id = connection.execute(
            "SELECT id FROM products WHERE name = ?",
            ("Blue Ballpoint Pen",),
        ).fetchone()[0]
        connection.execute(
            "UPDATE products SET stock = 1 WHERE id = ?",
            (product_id,),
        )
        connection.execute(
            "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, 2)",
            (user_id, product_id),
        )
        connection.commit()
        connection.close()
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["_csrf_token"] = "checkout-test-token"

        response = self.client.post(
            "/checkout",
            data={
                "csrf_token": "checkout-test-token",
                "delivery_type": "pickup",
                "payment_method": "cod",
            },
        )
        self.assertEqual(response.status_code, 302)

        connection = sqlite3.connect(self.database_path)
        order_count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        item_count = connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
        cart_quantity = connection.execute(
            "SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        ).fetchone()[0]
        stock = connection.execute(
            "SELECT stock FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()[0]
        connection.close()
        self.assertEqual((order_count, item_count, cart_quantity, stock), (0, 0, 2, 1))

    def test_existing_database_is_backed_up_to_the_stable_data_path(self):
        legacy_path = os.path.join(self.temp_dir.name, "campuscart.db")
        destination_path = os.path.join(self.temp_dir.name, "data", "student_cart.db")
        legacy = sqlite3.connect(legacy_path)
        legacy.execute("CREATE TABLE preserved_data (value TEXT NOT NULL)")
        legacy.execute("INSERT INTO preserved_data VALUES ('kept')")
        legacy.commit()
        legacy.close()

        with patch.object(database, "DB_PATH", destination_path), patch.object(
            database, "LEGACY_DB_PATH", legacy_path
        ):
            connection = get_db_connection(destination_path)
            self.assertEqual(
                connection.execute("SELECT value FROM preserved_data").fetchone()[0],
                "kept",
            )
            connection.close()

        self.assertTrue(os.path.exists(legacy_path))
        self.assertTrue(os.path.exists(destination_path))


if __name__ == "__main__":
    unittest.main()
