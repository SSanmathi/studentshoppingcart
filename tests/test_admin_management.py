import io
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from werkzeug.security import check_password_hash

import app as student_cart
from database import get_db_connection, init_db


class AdminManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "student-cart-admin.db")
        init_db(self.database_path)
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

    def csrf_token(self):
        with self.client.session_transaction() as session:
            token = session.get("_csrf_token")
        if token is None:
            response = self.client.get("/admin/login")
            self.assertEqual(response.status_code, 200)
            with self.client.session_transaction() as session:
                token = session["_csrf_token"]
        return token

    def create_admin(self):
        connection = sqlite3.connect(self.database_path)
        cursor = connection.execute(
            """
            INSERT INTO admins (full_name, email, phone_number, password_hash)
            VALUES (?, ?, ?, ?)
            """,
            (
                "Test Admin",
                "admin@example.edu",
                "+1 555 555 1234",
                student_cart.generate_password_hash("secure-admin-password"),
            ),
        )
        connection.commit()
        connection.close()
        with self.client.session_transaction() as session:
            session["admin_id"] = cursor.lastrowid
            session["_csrf_token"] = "admin-test-csrf"
        return cursor.lastrowid

    def create_student(self):
        connection = sqlite3.connect(self.database_path)
        cursor = connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash, college_name)
            VALUES (?, ?, ?, ?)
            """,
            (
                "Test Student",
                "student@example.edu",
                student_cart.generate_password_hash("secure-student-password"),
                "Test College",
            ),
        )
        student_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO budgets (user_id, monthly_budget) VALUES (?, ?)",
            (student_id, 2000),
        )
        connection.commit()
        connection.close()
        return student_id

    def test_local_setup_command_creates_only_the_first_admin(self):
        runner = student_cart.app.test_cli_runner()
        setup_input = (
            "First Admin\nfirst-admin@example.edu\n+1 555 555 1111\n"
            "secure-admin-password\nsecure-admin-password\n"
        )
        with patch("app.init_db"):
            result = runner.invoke(args=["create-admin"], input=setup_input)
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("First administrator created", result.output)

            repeated_setup = runner.invoke(args=["create-admin"], input=setup_input)
            self.assertNotEqual(repeated_setup.exit_code, 0)
            self.assertIn("An administrator already exists", repeated_setup.output)

        connection = sqlite3.connect(self.database_path)
        password_hash = connection.execute(
            "SELECT password_hash FROM admins WHERE email = ?",
            ("first-admin@example.edu",),
        ).fetchone()[0]
        connection.close()
        self.assertTrue(
            check_password_hash(password_hash, "secure-admin-password")
        )

    def test_local_command_resets_existing_admin_password(self):
        self.create_admin()
        runner = student_cart.app.test_cli_runner()
        with patch("app.init_db"):
            result = runner.invoke(
                args=["reset-admin-password"],
                input=(
                    "admin@example.edu\n"
                    "new-secure-admin-password\n"
                    "new-secure-admin-password\n"
                ),
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Administrator password updated", result.output)

        connection = sqlite3.connect(self.database_path)
        password_hash = connection.execute(
            "SELECT password_hash FROM admins WHERE email = ?",
            ("admin@example.edu",),
        ).fetchone()[0]
        connection.close()
        self.assertTrue(
            check_password_hash(password_hash, "new-secure-admin-password")
        )

    def test_public_signup_creates_first_admin_then_closes_public_signup(self):
        token = self.csrf_token()
        public_signup = self.client.get("/admin/signup")
        self.assertEqual(public_signup.status_code, 200)
        self.assertIn(b"Create Admin Account", public_signup.data)
        self.assertIn(b"Full Name", public_signup.data)
        self.assertIn(b"Phone number", public_signup.data)
        self.assertIn(b"(optional)", public_signup.data)
        self.assertNotIn(b"registration code", public_signup.data.lower())
        self.assertNotIn(b'access_code', public_signup.data)

        invalid_signup = self.client.post(
            "/admin/signup",
            data={
                "csrf_token": token,
                "name": "First Admin",
                "email": "first-admin@example.edu",
                "password": "secure-admin-password",
                "confirm_password": "different-password",
            },
        )
        self.assertEqual(invalid_signup.status_code, 200)
        self.assertIn(b"Password and confirm password do not match", invalid_signup.data)

        student_id = self.create_student()
        with self.client.session_transaction() as session:
            session["user_id"] = student_id
            session["active_role"] = "student"
        student_attempt = self.client.post(
            "/admin/signup",
            data={
                "csrf_token": token,
                "name": "Unauthorized Admin",
                "email": "unauthorized@example.edu",
                "phone": "+1 555 555 4444",
                "password": "secure-admin-password",
                "confirm_password": "secure-admin-password",
            },
        )
        self.assertEqual(student_attempt.status_code, 302)
        self.assertIn("/admin/login", student_attempt.location)
        connection = sqlite3.connect(self.database_path)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM admins").fetchone()[0],
            0,
        )
        connection.close()

        with self.client.session_transaction() as session:
            session.clear()
        token = self.csrf_token()
        created = self.client.post(
            "/admin/signup",
            data={
                "csrf_token": token,
                "name": "First Admin",
                "email": "first-admin@example.edu",
                "phone": "",
                "password": "secure-admin-password",
                "confirm_password": "secure-admin-password",
            },
        )
        self.assertEqual(created.status_code, 302)
        self.assertIn("/admin/login", created.location)
        connection = sqlite3.connect(self.database_path)
        password_hash = connection.execute(
            "SELECT password_hash FROM admins WHERE email = ?",
            ("first-admin@example.edu",),
        ).fetchone()[0]
        self.assertTrue(
            check_password_hash(password_hash, "secure-admin-password")
        )
        connection.close()

        closed_signup = self.client.get("/admin/signup")
        self.assertEqual(closed_signup.status_code, 200)
        self.assertIn(b"Admin Signup Closed", closed_signup.data)
        self.assertNotIn(b'name="password"', closed_signup.data)

        closed_login = self.client.get("/admin/login")
        self.assertEqual(closed_login.status_code, 200)
        self.assertNotIn(b"Create Admin Account", closed_login.data)
        self.assertIn(b"Public signup is disabled", closed_login.data)
        closed_token = self.csrf_token()
        closed_post = self.client.post(
            "/admin/signup",
            data={
                "csrf_token": closed_token,
                "name": "Public Second Admin",
                "email": "public-second@example.edu",
                "phone": "",
                "password": "secure-admin-password",
                "confirm_password": "secure-admin-password",
            },
        )
        self.assertEqual(closed_post.status_code, 200)
        connection = sqlite3.connect(self.database_path)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM admins").fetchone()[0],
            1,
        )
        connection.close()

        login = self.client.post(
            "/admin/login",
            data={
                "csrf_token": token,
                "email": "first-admin@example.edu",
                "password": "secure-admin-password",
            },
        )
        self.assertEqual(login.status_code, 302)
        self.assertIn("/admin", login.location)
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 200)
        token = self.csrf_token()

        extra_admin_form = self.client.get("/admin/signup")
        self.assertEqual(extra_admin_form.status_code, 200)
        self.assertIn(b"Create Admin Account", extra_admin_form.data)
        extra_admin = self.client.post(
            "/admin/signup",
            data={
                "csrf_token": token,
                "name": "Additional Admin",
                "email": "additional-admin@example.edu",
                "phone": "+1 555 555 9876",
                "password": "another-secure-password",
                "confirm_password": "another-secure-password",
            },
        )
        self.assertEqual(extra_admin.status_code, 302)
        self.assertIn("/admin", extra_admin.location)

    def test_admin_can_add_edit_and_deactivate_a_product(self):
        admin_id = self.create_admin()
        create_response = self.client.post(
            "/admin/products/new",
            data={
                "csrf_token": "admin-test-csrf",
                "name": "Campus Test Bag",
                "description": "A sturdy bag for carrying books and daily campus essentials.",
                "category": "Bags",
                "original_price": "1200",
                "discount_price": "950",
                "stock": "12",
                "status": "active",
                "product_image": (
                    io.BytesIO(b"\x89PNG\r\n\x1a\nstudent-cart-test-image"),
                    "campus-bag.png",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(create_response.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        product = connection.execute(
            "SELECT * FROM products WHERE name = ?",
            ("Campus Test Bag",),
        ).fetchone()
        self.assertIsNotNone(product)
        self.assertEqual(product["price"], 950)
        self.assertEqual(product["original_price"], 1200)
        self.assertEqual(product["is_active"], 1)
        self.assertTrue(product["image_url"].startswith("/static/uploads/products/"))
        product_id = product["id"]
        image_path = os.path.join(
            student_cart.app.root_path,
            "static",
            "uploads",
            "products",
            os.path.basename(product["image_url"]),
        )
        connection.close()

        visible = self.client.get("/api/products?q=Campus+Test+Bag")
        self.assertEqual(visible.status_code, 200)
        self.assertEqual(visible.json[0]["id"], product_id)

        updated = self.client.post(
            f"/admin/products/{product_id}/edit",
            data={
                "csrf_token": "admin-test-csrf",
                "name": "Campus Test Bag",
                "description": "A sturdy bag for carrying books and daily campus essentials.",
                "category": "Bags",
                "original_price": "1200",
                "discount_price": "900",
                "stock": "0",
                "status": "inactive",
            },
        )
        self.assertEqual(updated.status_code, 302)
        self.assertEqual(self.client.get(f"/api/products/{product_id}").status_code, 404)
        self.assertEqual(
            self.client.get("/api/products?q=Campus+Test+Bag").json,
            [],
        )

        connection = sqlite3.connect(self.database_path)
        cursor = connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash, college_name)
            VALUES (?, ?, ?, ?)
            """,
            ("Catalogue Student", "catalogue-student@example.edu", "not-used", "Campus"),
        )
        student_id = cursor.lastrowid
        updated_row = connection.execute(
            "SELECT price, stock, is_active FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
        connection.commit()
        connection.close()
        self.assertEqual(updated_row, (900, 0, 0))

        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = student_id
            session["_csrf_token"] = "student-test-csrf"
        listing = self.client.get("/products?q=Campus+Test+Bag")
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn(f'href="/product/{product_id}"'.encode(), listing.data)
        with self.client.session_transaction() as session:
            session.clear()
            session["admin_id"] = admin_id
            session["_csrf_token"] = "admin-test-csrf"

        deleted = self.client.post(
            f"/admin/products/{product_id}/delete",
            data={"csrf_token": "admin-test-csrf"},
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertFalse(os.path.exists(image_path))

    def test_cancelling_order_restores_reserved_stock_once(self):
        self.create_admin()
        connection = sqlite3.connect(self.database_path)
        product_id, initial_stock, price = connection.execute(
            "SELECT id, stock, price FROM products WHERE name = ?",
            ("Blue Ballpoint Pen",),
        ).fetchone()
        cursor = connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash, college_name)
            VALUES (?, ?, ?, ?)
            """,
            ("Order Student", "order-student@example.edu", "not-used", "Campus"),
        )
        user_id = cursor.lastrowid
        order_cursor = connection.execute(
            """
            INSERT INTO orders (
                user_id, order_id, subtotal, discount_amount, total_amount,
                payment_method, delivery_type, order_status
            ) VALUES (?, ?, ?, 0, ?, 'cod', 'pickup', 'Pending')
            """,
            (user_id, "TEST-ORDER-1", price * 2, price * 2),
        )
        order_id = order_cursor.lastrowid
        connection.execute(
            """
            INSERT INTO order_items (
                order_id, product_id, product_name_at_purchase, quantity,
                unit_price, subtotal
            ) VALUES (?, ?, ?, 2, ?, ?)
            """,
            (order_id, product_id, "Blue Ballpoint Pen", price, price * 2),
        )
        connection.execute(
            "UPDATE products SET stock = stock - 2 WHERE id = ?",
            (product_id,),
        )
        connection.commit()
        connection.close()

        deletion = self.client.post(
            f"/admin/products/{product_id}/delete",
            data={"csrf_token": "admin-test-csrf"},
        )
        self.assertEqual(deletion.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        self.assertIsNotNone(
            connection.execute(
                "SELECT id FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
        )
        connection.close()

        response = self.client.post(
            f"/admin/orders/{order_id}/status",
            data={"csrf_token": "admin-test-csrf", "status": "Cancelled"},
        )
        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        stock, status = connection.execute(
            """
            SELECT p.stock, o.order_status FROM products p
            JOIN order_items oi ON oi.product_id = p.id
            JOIN orders o ON o.id = oi.order_id WHERE o.id = ?
            """,
            (order_id,),
        ).fetchone()
        self.assertEqual(stock, initial_stock)
        self.assertEqual(status, "Cancelled")
        connection.close()

        self.client.post(
            f"/admin/orders/{order_id}/status",
            data={"csrf_token": "admin-test-csrf", "status": "Confirmed"},
        )
        connection = sqlite3.connect(self.database_path)
        self.assertEqual(
            connection.execute(
                "SELECT stock FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()[0],
            initial_stock,
        )
        connection.close()

    def test_all_admin_pages_render_and_student_cannot_use_them(self):
        self.create_admin()
        product_id = sqlite3.connect(self.database_path).execute(
            "SELECT id FROM products LIMIT 1"
        ).fetchone()[0]
        pages = (
            "/admin",
            "/admin/products",
            "/admin/products/new",
            "/admin/add-product",
            "/admin/manage-products",
            "/admin/categories",
            f"/admin/products/{product_id}/edit",
            f"/admin/edit-product/{product_id}",
            "/admin/orders",
            "/admin/sales",
            "/admin/profile",
        )
        for path in pages:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = 1
        self.assertEqual(self.client.get("/admin/sales").status_code, 302)

    def test_admin_can_manage_categories_preview_and_product_visibility(self):
        self.create_admin()
        categories_page = self.client.get("/admin/categories")
        self.assertEqual(categories_page.status_code, 200)
        self.assertIn(b"Categories", categories_page.data)

        added_category = self.client.post(
            "/admin/categories",
            data={
                "csrf_token": "admin-test-csrf",
                "action": "add",
                "category_name": "Lab Supplies",
            },
        )
        self.assertEqual(added_category.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        category_names = [
            row[0]
            for row in connection.execute("SELECT name FROM categories").fetchall()
        ]
        connection.close()
        self.assertIn("Lab Supplies", category_names)

        connection = sqlite3.connect(self.database_path)
        product_id, product_name = connection.execute(
            "SELECT id, name FROM products LIMIT 1"
        ).fetchone()
        connection.close()
        preview = self.client.get(f"/admin/products/{product_id}/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(product_name.encode(), preview.data)

        deactivated = self.client.post(
            f"/admin/products/{product_id}/status",
            data={"csrf_token": "admin-test-csrf"},
        )
        self.assertEqual(deactivated.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        self.assertEqual(
            connection.execute(
                "SELECT is_active FROM products WHERE id = ?", (product_id,)
            ).fetchone()[0],
            0,
        )
        connection.close()
        self.assertEqual(
            self.client.get(f"/api/products/{product_id}").status_code,
            404,
        )
        self.assertEqual(self.client.get("/admin/manage-products").status_code, 200)

    def test_admin_login_uses_the_separate_admin_credentials(self):
        self.create_admin()
        with self.client.session_transaction() as session:
            session.clear()
        login_form = self.client.get("/admin/login")
        self.assertEqual(login_form.status_code, 200)
        token = self.csrf_token()
        response = self.client.post(
            "/admin/login",
            data={
                "csrf_token": token,
                "email": "admin@example.edu",
                "password": "secure-admin-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin", response.location)
        with self.client.session_transaction() as session:
            self.assertIn("admin_id", session)
            self.assertNotIn("user_id", session)

    def test_authenticated_admin_and_student_switch_views_without_losing_sessions(self):
        admin_id = self.create_admin()
        student_id = self.create_student()
        connection = sqlite3.connect(self.database_path)
        student_product_id = connection.execute(
            "SELECT id FROM products WHERE name = ?",
            ("Blue Ballpoint Pen",),
        ).fetchone()[0]
        connection.close()
        with self.client.session_transaction() as session:
            session["admin_id"] = admin_id
            session["user_id"] = student_id
            session["active_role"] = "admin"
            session["_csrf_token"] = "admin-test-csrf"

        admin_dashboard = self.client.get("/admin/dashboard")
        self.assertEqual(admin_dashboard.status_code, 200)
        self.assertIn(b"Switch to Student View", admin_dashboard.data)
        added_product = self.client.post(
            "/admin/products/new",
            data={
                "csrf_token": "admin-test-csrf",
                "name": "View Switch Product",
                "description": "A test product added through the admin management page.",
                "category": "Accessories",
                "original_price": "125",
                "discount_price": "100",
                "stock": "7",
                "status": "active",
                "product_image": (
                    io.BytesIO(b"\x89PNG\r\n\x1a\nview-switch-test-image"),
                    "view-switch-product.png",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(added_product.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        product_id, image_url = connection.execute(
            "SELECT id, image_url FROM products WHERE name = ?",
            ("View Switch Product",),
        ).fetchone()
        connection.close()
        uploaded_image = os.path.join(
            student_cart.app.root_path,
            "static",
            "uploads",
            "products",
            os.path.basename(image_url),
        )

        switch_to_student = self.client.post(
            "/switch-view",
            data={"csrf_token": "admin-test-csrf", "target": "student"},
        )
        self.assertEqual(switch_to_student.status_code, 302)
        self.assertIn("/dashboard", switch_to_student.location)
        student_dashboard = self.client.get("/dashboard")
        self.assertEqual(student_dashboard.status_code, 200)
        self.assertIn(b"Switch to Admin View", student_dashboard.data)
        self.assertIn(b"View Switch Product", student_dashboard.data)
        with self.client.session_transaction() as session:
            self.assertEqual(session["active_role"], "student")
            self.assertEqual(session["admin_id"], admin_id)
            self.assertEqual(session["user_id"], student_id)

        product_listing = self.client.get("/products?q=View+Switch+Product")
        self.assertEqual(product_listing.status_code, 200)
        self.assertIn(b"View Switch Product", product_listing.data)
        self.assertEqual(
            self.client.get(f"/api/products/{product_id}").status_code,
            200,
        )
        add_to_cart = self.client.post(
            "/cart/add",
            data={
                "csrf_token": "admin-test-csrf",
                "product_id": str(student_product_id),
                "quantity": "1",
            },
        )
        self.assertEqual(add_to_cart.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        self.assertEqual(
            connection.execute(
                "SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
                (student_id, student_product_id),
            ).fetchone()[0],
            1,
        )
        connection.close()
        checkout = self.client.post(
            "/checkout",
            data={
                "csrf_token": "admin-test-csrf",
                "delivery_type": "pickup",
                "payment_method": "cod",
            },
        )
        self.assertEqual(checkout.status_code, 302)

        switch_to_admin = self.client.post(
            "/switch-view",
            data={"csrf_token": "admin-test-csrf", "target": "admin"},
        )
        self.assertEqual(switch_to_admin.status_code, 302)
        self.assertIn("/admin", switch_to_admin.location)
        admin_page = self.client.get("/admin")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn(b"Switch to Student View", admin_page.data)
        orders_page = self.client.get("/admin/orders")
        self.assertEqual(orders_page.status_code, 200)
        self.assertIn(b"Test Student", orders_page.data)
        with self.client.session_transaction() as session:
            self.assertEqual(session["active_role"], "admin")
            self.assertEqual(session["admin_id"], admin_id)
            self.assertEqual(session["user_id"], student_id)

        self.client.post(
            f"/admin/products/{product_id}/delete",
            data={"csrf_token": "admin-test-csrf"},
        )
        self.assertFalse(os.path.exists(uploaded_image))

        admin_logout = self.client.post(
            "/admin/logout",
            data={"csrf_token": "admin-test-csrf"},
        )
        self.assertEqual(admin_logout.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        with self.client.session_transaction() as session:
            self.assertNotIn("admin_id", session)
            self.assertEqual(session["user_id"], student_id)
            self.assertEqual(session["active_role"], "student")

        self.assertEqual(
            self.client.post(
                "/switch-view",
                data={"csrf_token": "admin-test-csrf", "target": "admin"},
            ).status_code,
            302,
        )
        student_logout = self.client.post(
            "/logout",
            data={"csrf_token": "admin-test-csrf"},
        )
        self.assertEqual(student_logout.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 302)
        self.assertEqual(self.client.get("/admin").status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)
            self.assertNotIn("admin_id", session)

    def test_students_cannot_switch_into_admin_without_authentication(self):
        student_id = self.create_student()
        with self.client.session_transaction() as session:
            session["user_id"] = student_id
            session["active_role"] = "student"
            session["_csrf_token"] = "student-test-csrf"
        response = self.client.post(
            "/switch-view",
            data={"csrf_token": "student-test-csrf", "target": "admin"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.location)
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["active_role"], "student")
            self.assertEqual(session["user_id"], student_id)
            self.assertNotIn("admin_id", session)

    def test_switching_to_student_view_preserves_admin_until_student_login(self):
        admin_id = self.create_admin()
        with self.client.session_transaction() as session:
            session["admin_id"] = admin_id
            session["active_role"] = "admin"
            session["_csrf_token"] = "admin-test-csrf"

        response = self.client.post(
            "/switch-view",
            data={"csrf_token": "admin-test-csrf", "target": "student"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")
        student_home = self.client.get(response.location)
        self.assertEqual(student_home.status_code, 200)
        self.assertIn(b"Student Cart helps students shop smarter", student_home.data)
        with self.client.session_transaction() as session:
            self.assertEqual(session["active_role"], "student")
            self.assertEqual(session["admin_id"], admin_id)

            switch_back = self.client.post(
                "/switch-to-admin",
                data={"csrf_token": "admin-test-csrf"},
            )
            self.assertEqual(switch_back.status_code, 302)
            self.assertIn("/admin", switch_back.location)

            self.client.post(
                "/switch-to-student",
                data={"csrf_token": "admin-test-csrf"},
            )
            student_id = self.create_student()
        login = self.client.post(
            "/login",
            data={
                "csrf_token": "admin-test-csrf",
                "email": "student@example.edu",
                "password": "secure-student-password",
            },
        )
        self.assertEqual(login.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session["active_role"], "student")
            self.assertEqual(session["admin_id"], admin_id)
            self.assertEqual(session["user_id"], student_id)

    def test_product_validation_rejects_invalid_price_and_image(self):
        self.create_admin()
        connection = sqlite3.connect(self.database_path)
        initial_count = connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]
        connection.close()
        invalid_prices = self.client.post(
            "/admin/products/new",
            data={
                "csrf_token": "admin-test-csrf",
                "name": "Invalid Price Product",
                "description": "This product has an invalid discount price.",
                "category": "Accessories",
                "original_price": "100",
                "discount_price": "101",
                "stock": "1",
                "status": "active",
                "product_image": (
                    io.BytesIO(b"\x89PNG\r\n\x1a\nstudent-cart-test-image"),
                    "invalid-price.png",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid_prices.status_code, 200)
        self.assertIn(b"no higher than the original price", invalid_prices.data)

        invalid_image = self.client.post(
            "/admin/products/new",
            data={
                "csrf_token": "admin-test-csrf",
                "name": "Invalid Image Product",
                "description": "This product uses a disallowed image file type.",
                "category": "Accessories",
                "original_price": "100",
                "discount_price": "90",
                "stock": "1",
                "status": "active",
                "product_image": (io.BytesIO(b"<svg></svg>"), "product.svg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid_image.status_code, 200)
        self.assertIn(b"Upload a JPG, PNG, or WebP image", invalid_image.data)
        connection = sqlite3.connect(self.database_path)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            initial_count,
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
