import sqlite3
import uuid
import re
import math
import os
import secrets
from collections import deque
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

import click
from dotenv import load_dotenv
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from database import DB_PATH, get_db_connection, init_db

from catalog import find_products as search_catalog, index_products
from pricing import calculate_product_price
from seed import CATEGORY_IMAGES, PRODUCT_CATEGORIES
from student_tools import (
    DEPARTMENTS,
    HOSTEL_CHECKLIST,
    PURPOSE_TERMS,
    SEMESTER_NEEDS,
    affordable_alternatives,
    build_budget_challenge,
    build_hostel_checklist,
    recommend_for_needs,
)

# Load project-local settings for both `python app.py` and VS Code runs.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
environment = os.environ.get("STUDENT_CART_ENV", "development").strip().lower()
secret_key = os.environ.get("STUDENT_CART_SECRET_KEY")
if environment == "production" and not secret_key:
    raise RuntimeError("STUDENT_CART_SECRET_KEY must be set in production.")
app.secret_key = secret_key or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=environment == "production",
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
)

PRODUCT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PRODUCT_IMAGE_BYTES = 3 * 1024 * 1024


@app.before_request
def ensure_db():
    if not app.config.get("STUDENT_CART_DATABASE_INITIALIZED"):
        init_db()
        app.config["STUDENT_CART_DATABASE_INITIALIZED"] = True

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected_token = session.get("_csrf_token", "")
        submitted_token = request.form.get("csrf_token", "")
        if (
            not expected_token
            or not submitted_token
            or not secrets.compare_digest(expected_token, submitted_token)
        ):
            return jsonify(error="Your session expired. Refresh the page and try again."), 400


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": csrf_token}


def product_image_fallback(category):
    if category == "Books":
        image_name = "books-image-fallback.svg"
    elif category == "Hostel Essentials":
        image_name = "hostel-image-fallback.svg"
    else:
        image_name = "stationery-image-fallback.svg"
    return url_for("static", filename=f"images/{image_name}")


@app.context_processor
def inject_product_image_fallback():
    return {"product_image_fallback": product_image_fallback}


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    app.logger.exception("Student Cart database operation failed: %s", error)
    if request.path.startswith("/api/"):
        return jsonify(error="The database is temporarily unavailable."), 503
    return (
        "Student Cart is temporarily unable to reach its database. "
        "Your changes were not confirmed; please try again.",
        503,
    )


@app.teardown_appcontext
def close_db(_exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def get_db():
    if "db" not in g:
        g.db = get_db_connection()
    return g.db


def active_role():
    selected_role = session.get("active_role")
    if selected_role in {"admin", "student"}:
        return selected_role
    if "admin_id" in session and "user_id" not in session:
        return "admin"
    if "user_id" in session:
        return "student"
    return None


def establish_role_session(role, identity_key, identity_id):
    other_identity = "admin_id" if identity_key == "user_id" else "user_id"
    other_id = session.get(other_identity)
    session.clear()
    if other_id is not None:
        session[other_identity] = other_id
    session[identity_key] = identity_id
    session["active_role"] = role
    session.permanent = True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if active_role() == "admin":
            return redirect(url_for("admin_dashboard"))
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "admin_id" not in session or active_role() != "admin":
            flash("Please log in with an administrator account.", "error")
            return redirect(url_for("admin_login"))
        if current_admin() is None:
            session.clear()
            flash("Administrator account not found. Please sign in again.", "error")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped


def get_user_by_id(user_id):
    return get_db().execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def get_user_by_email(email):
    return get_db().execute(
        "SELECT * FROM users WHERE email = ?",
        (email.lower().strip(),),
    ).fetchone()


def get_product_by_id(product_id):
    return get_db().execute(
        "SELECT * FROM products WHERE id = ? AND is_active = 1",
        (product_id,),
    ).fetchone()


def with_product_pricing(products, quantities=None, now=None):
    products = [dict(product) for product in products]
    if not products:
        return []

    product_ids = list({
        product.get("product_id", product.get("id"))
        for product in products
    })
    placeholders = ", ".join("?" for _ in product_ids)
    offer_rows = get_db().execute(
        f"SELECT * FROM product_offers WHERE product_id IN ({placeholders})",
        product_ids,
    ).fetchall()
    offer_index = {}
    for offer in offer_rows:
        offer_index.setdefault(offer["product_id"], []).append(dict(offer))

    priced_products = []
    for product in products:
        product_id = product.get("product_id", product.get("id"))
        quantity = (quantities or {}).get(product_id, 1)
        calculation = calculate_product_price(
            product["price"],
            offer_index.get(product_id, ()),
            quantity=quantity,
            now=now,
        )
        priced = dict(product)
        priced.update(calculation)
        priced["unit_price"] = calculation["effective_price"]
        priced["line_total"] = calculation["total"]
        original_price = priced.get("original_price")
        if original_price is not None and original_price > calculation["effective_price"]:
            priced["display_original_price"] = original_price
        elif calculation["applied_offer"]:
            priced["display_original_price"] = calculation["list_price"]
        else:
            priced["display_original_price"] = None
        if priced["display_original_price"]:
            priced["display_discount_percentage"] = round(
                (1 - calculation["effective_price"] / priced["display_original_price"]) * 100,
                2,
            )
        else:
            priced["display_discount_percentage"] = 0
        priced_products.append(priced)
    return priced_products


def with_review_summaries(products, enrich_prices=True):
    products = list(products)
    if not products:
        return []
    if enrich_prices:
        products = with_product_pricing(products)

    product_ids = list({product["id"] for product in products})
    placeholders = ", ".join("?" for _ in product_ids)
    summaries = get_db().execute(
        f"""
        SELECT product_id, COUNT(*) AS review_count, AVG(rating) AS customer_rating
        FROM product_reviews
        WHERE product_id IN ({placeholders})
        GROUP BY product_id
        """,
        product_ids,
    ).fetchall()
    review_index = {summary["product_id"]: summary for summary in summaries}
    reviewed_products = []
    for product in products:
        reviewed = dict(product)
        summary = review_index.get(product["id"])
        reviewed["review_count"] = summary["review_count"] if summary else 0
        reviewed["customer_rating"] = summary["customer_rating"] if summary else None
        reviewed_products.append(reviewed)
    return reviewed_products


def find_products(query="", category="all", max_price=None, in_stock=False, sort="featured", limit=None, min_price=None):
    query = query.strip().lower()
    budget_match = re.search(r"\bunder\s*₹?\s*(\d+(?:\.\d+)?)", query)
    if budget_match:
        parsed_budget = float(budget_match.group(1))
        if not math.isfinite(parsed_budget):
            return []
        max_price = parsed_budget if max_price is None else min(max_price, parsed_budget)
        query = (query[:budget_match.start()] + query[budget_match.end():]).strip()

    catalogue = get_db().execute(
        """
        SELECT p.*,
            (SELECT AVG(pr.rating) FROM product_reviews pr WHERE pr.product_id = p.id) AS customer_rating
        FROM products p
        WHERE p.is_active = 1
        """
    ).fetchall()
    catalogue = with_product_pricing(catalogue)
    return with_review_summaries(
        search_catalog(
            catalogue, query, category, max_price, in_stock, sort, limit,
            min_price=min_price,
        ),
        enrich_prices=False,
    )


def get_recently_viewed_products(exclude_ids=()):
    viewed_ids = session.get("recently_viewed", [])
    if not isinstance(viewed_ids, list):
        return []
    unique_ids = []
    seen_ids = set(exclude_ids)
    for viewed_id in viewed_ids:
        if type(viewed_id) is int and viewed_id not in seen_ids:
            unique_ids.append(viewed_id)
            seen_ids.add(viewed_id)
        if len(unique_ids) == 5:
            break
    if not unique_ids:
        return []

    placeholders = ", ".join("?" for _ in unique_ids)
    products = get_db().execute(
        f"SELECT * FROM products WHERE is_active = 1 AND id IN ({placeholders})",
        unique_ids,
    ).fetchall()
    product_index = index_products(products)
    return with_review_summaries(
        [product_index[product_id] for product_id in unique_ids if product_id in product_index]
    )


@app.context_processor
def navigation_context():
    user_id = session.get("user_id")
    if user_id is None:
        return {
            "cart_count": 0,
            "wishlist_count": 0,
            "wishlisted_product_ids": [],
            "category_images": CATEGORY_IMAGES,
        }
    counts = get_db().execute(
        """
        SELECT
            COALESCE((
                SELECT SUM(ci.quantity)
                FROM cart_items ci JOIN products p ON p.id = ci.product_id
                WHERE ci.user_id = ? AND p.is_active = 1
            ), 0) AS cart_count,
            COALESCE((SELECT COUNT(*) FROM wishlist_items WHERE user_id = ?), 0) AS wishlist_count
        """,
        (user_id, user_id),
    ).fetchone()
    wishlisted_product_ids = [
        row["product_id"]
        for row in get_db().execute(
            "SELECT product_id FROM wishlist_items WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    ]
    return {
        **dict(counts),
        "wishlisted_product_ids": wishlisted_product_ids,
        "category_images": CATEGORY_IMAGES,
    }


def get_cart_items(user_id):
    return get_db().execute(
        """
        SELECT ci.*, p.name, p.price, p.image_url, p.stock, p.category
        FROM cart_items ci
        JOIN products p ON p.id = ci.product_id
        WHERE ci.user_id = ? AND p.is_active = 1
        ORDER BY ci.id DESC
        """,
        (user_id,),
    ).fetchall()


def calculate_cart(user_id):
    rows = get_cart_items(user_id)
    quantities = {item["product_id"]: item["quantity"] for item in rows}
    cart_items = with_product_pricing(rows, quantities=quantities)
    subtotal = sum(item["subtotal"] for item in cart_items)
    discount_amount = sum(item["discount_amount"] for item in cart_items)
    total = sum(item["line_total"] for item in cart_items)

    return {
        "items": cart_items,
        "subtotal": round(subtotal, 2),
        "discount_amount": round(discount_amount, 2),
        "delivery_charge": 0.0,
        "total": round(total, 2),
        "item_count": sum(item["quantity"] for item in cart_items),
    }


def add_products_to_cart(user_id, product_ids):
    """Atomically validate stock and add one of each unique product to a cart."""
    selected_ids = list(dict.fromkeys(product_ids))
    if not selected_ids:
        raise ValueError("Select at least one product before adding it to your cart.")

    connection = get_db()
    connection.execute("BEGIN IMMEDIATE")
    try:
        validated = []
        for product_id in selected_ids:
            product = get_product_by_id(product_id)
            if product is None or product["stock"] < 1:
                raise ValueError("A selected product is no longer available. Review your selection.")
            current = connection.execute(
                "SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
                (user_id, product_id),
            ).fetchone()
            current_quantity = current["quantity"] if current else 0
            if current_quantity + 1 > product["stock"]:
                raise ValueError(
                    f"Not enough stock for {product['name']} to add it to your cart."
                )
            validated.append((product_id, current is not None))

        for product_id, already_in_cart in validated:
            if already_in_cart:
                connection.execute(
                    "UPDATE cart_items SET quantity = quantity + 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND product_id = ?",
                    (user_id, product_id),
                )
            else:
                connection.execute(
                    "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, 1)",
                    (user_id, product_id),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def add_product_quantity_to_cart(user_id, product_id, quantity):
    connection = get_db()
    connection.execute("BEGIN IMMEDIATE")
    try:
        product = get_product_by_id(product_id)
        if product is None:
            raise ValueError("Product not found.")
        if quantity > product["stock"]:
            raise ValueError(
                f"Only {product['stock']} units available for {product['name']}."
            )
        connection.execute(
            """
            INSERT INTO cart_items (user_id, product_id, quantity, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, product_id) DO UPDATE SET
                quantity = cart_items.quantity + excluded.quantity,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, product_id, quantity),
        )
        total_quantity = connection.execute(
            "SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        ).fetchone()["quantity"]
        if total_quantity > product["stock"]:
            raise ValueError(
                f"Your cart already has {total_quantity - quantity} items. "
                f"Only {product['stock']} total are available."
            )
        connection.commit()
        return product
    except Exception:
        connection.rollback()
        raise


def update_cart_quantity(user_id, product_id, quantity):
    connection = get_db()
    connection.execute("BEGIN IMMEDIATE")
    try:
        product = get_product_by_id(product_id)
        if product is None:
            raise ValueError("Product not found.")
        if quantity > product["stock"]:
            raise ValueError(
                f"Only {product['stock']} units available for {product['name']}."
            )
        cursor = connection.execute(
            """
            UPDATE cart_items
            SET quantity = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND product_id = ?
            """,
            (quantity, user_id, product_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("That product is not in your cart.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def parse_quantity(raw_quantity, maximum=None):
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError) as error:
        raise ValueError("Enter a valid quantity.") from error
    if quantity < 1 or (maximum is not None and quantity > maximum):
        if maximum is not None:
            raise ValueError(f"Choose a quantity between 1 and {maximum}.")
        raise ValueError("Enter a quantity of at least 1.")
    return quantity


def get_budget_summary(user_id):
    budget = get_db().execute(
        "SELECT monthly_budget FROM budgets WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if budget is None:
        budget_value = 2000.0
        get_db().execute(
            "INSERT INTO budgets (user_id, monthly_budget) VALUES (?, ?)",
            (user_id, budget_value),
        )
        get_db().commit()
    else:
        budget_value = budget["monthly_budget"]

    spent = get_db().execute(
        "SELECT COALESCE(SUM(total_amount), 0) AS spent FROM orders WHERE user_id = ?",
        (user_id,),
    ).fetchone()["spent"]

    cart_total = calculate_cart(user_id)["total"]
    remaining = budget_value - cart_total
    percent = 0 if budget_value <= 0 else min(100, (cart_total / budget_value) * 100)

    category_breakdown = get_db().execute(
        """
        SELECT p.category, SUM(oi.quantity * oi.unit_price) AS amount
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        JOIN orders o ON o.id = oi.order_id
        WHERE o.user_id = ?
        GROUP BY p.category
        ORDER BY amount DESC
        """,
        (user_id,),
    ).fetchall()

    return {
        "budget": round(float(budget_value), 2),
        "spent": round(float(spent), 2),
        "cart_total": round(cart_total, 2),
        "remaining": round(remaining, 2),
        "percent": round(percent, 2),
        "category_breakdown": category_breakdown,
    }


def build_dashboard_context(user_id):
    products = get_db().execute(
        "SELECT * FROM products WHERE is_active = 1 ORDER BY created_at DESC LIMIT 8"
    ).fetchall()
    featured = get_db().execute(
        "SELECT * FROM products WHERE is_active = 1 AND category = 'Stationery' AND featured = 1 ORDER BY price ASC LIMIT 6"
    ).fetchall()
    essential = get_db().execute(
        "SELECT * FROM products WHERE is_active = 1 AND is_essential = 1 ORDER BY price ASC LIMIT 6"
    ).fetchall()
    latest_products = get_db().execute(
        "SELECT * FROM products WHERE is_active = 1 ORDER BY created_at DESC, id DESC LIMIT 8"
    ).fetchall()
    special_offers = get_db().execute(
        """
        SELECT p.* FROM products p
        WHERE p.is_active = 1 AND p.stock > 0
          AND (
              (p.original_price IS NOT NULL AND p.original_price > p.price)
              OR EXISTS (
                  SELECT 1 FROM product_offers po
                  WHERE po.product_id = p.id AND po.is_active = 1
                    AND po.starts_at <= CURRENT_TIMESTAMP AND po.ends_at >= CURRENT_TIMESTAMP
              )
          )
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT 8
        """
    ).fetchall()
    cart_summary = calculate_cart(user_id)
    budget_summary = get_budget_summary(user_id)
    context = {
        "products": products,
        "catalog_count": get_db().execute(
            "SELECT COUNT(*) FROM products WHERE is_active = 1"
        ).fetchone()[0],
        "recently_viewed_products": get_recently_viewed_products(),
        "latest_products": latest_products,
        "special_offers": special_offers,
        "featured": featured,
        "essential": essential,
        "international_products": get_db().execute(
            "SELECT * FROM products WHERE is_active = 1 AND is_international = 1 AND stock > 0 ORDER BY price ASC LIMIT 8"
        ).fetchall(),
        "hostel_products": get_db().execute(
            "SELECT * FROM products WHERE is_active = 1 AND category = 'Hostel Essentials' AND stock > 0 ORDER BY featured DESC, price ASC LIMIT 8"
        ).fetchall(),
        "snack_products": get_db().execute(
            "SELECT * FROM products WHERE is_active = 1 AND category = 'Hostel Essentials' AND subcategory = 'Food and Snacks' AND stock > 0 ORDER BY featured DESC, price ASC LIMIT 6"
        ).fetchall(),
        "books": get_db().execute(
            """
            SELECT p.* FROM products p
            WHERE p.is_active = 1 AND p.category = 'Books' AND p.stock > 0
            ORDER BY p.featured DESC,
                COALESCE((SELECT AVG(pr.rating) FROM product_reviews pr WHERE pr.product_id = p.id), 0) DESC,
                p.price ASC
            LIMIT 6
            """
        ).fetchall(),
        "low_stock_products": get_db().execute(
            "SELECT * FROM products WHERE is_active = 1 AND stock BETWEEN 1 AND 5 ORDER BY stock ASC, name ASC LIMIT 6"
        ).fetchall(),
        "budget_recommendations": get_db().execute(
            """
            SELECT p.* FROM products p
            WHERE p.is_active = 1 AND p.stock > 0 AND p.price <= ?
            ORDER BY p.featured DESC,
                COALESCE((SELECT AVG(pr.rating) FROM product_reviews pr WHERE pr.product_id = p.id), 0) DESC,
                p.price ASC
            LIMIT 6
            """,
            (get_budget_summary(user_id)["budget"],),
        ).fetchall(),
        "cart_count": cart_summary["item_count"],
        "budget_summary": budget_summary,
        "savings": cart_summary["discount_amount"],
    }
    for key in (
        "products",
        "latest_products",
        "special_offers",
        "featured",
        "essential",
        "international_products",
        "hostel_products",
        "snack_products",
        "books",
        "low_stock_products",
        "budget_recommendations",
    ):
        context[key] = with_review_summaries(context[key])
    return context


def get_recommendations(user_id):
    cart_products = get_db().execute(
        """
        SELECT p.category, p.price, p.id
        FROM cart_items ci
        JOIN products p ON p.id = ci.product_id
        WHERE ci.user_id = ? AND p.is_active = 1
        LIMIT 5
        """,
        (user_id,),
    ).fetchall()

    categories = list(dict.fromkeys(row["category"] for row in cart_products))
    if categories:
        category_filter = f"category IN ({', '.join('?' for _ in categories)})"
        category_parameters = categories
    else:
        category_filter = "0"
        category_parameters = []
    recommended = get_db().execute(
        f"""
        SELECT * FROM products
        WHERE is_active = 1 AND (({category_filter})
        OR is_essential = 1
        OR featured = 1)
        ORDER BY price ASC
        LIMIT 6
        """,
        category_parameters,
    ).fetchall()

    seen = set()
    unique = []
    for product in recommended:
        if product["id"] not in seen:
            seen.add(product["id"])
            unique.append(product)
    return with_review_summaries(unique[:4])


def get_user_orders(user_id):
    return get_db().execute(
        """
        SELECT o.*, COUNT(oi.id) AS item_count
        FROM orders o
        LEFT JOIN order_items oi ON oi.order_id = o.id
        WHERE o.user_id = ?
        GROUP BY o.id
        ORDER BY o.created_at DESC
        """,
        (user_id,),
    ).fetchall()


@app.route("/")
def home():
    if active_role() == "admin":
        return redirect(url_for("admin_dashboard"))
    if active_role() == "student":
        if "user_id" in session:
            return redirect(url_for("dashboard"))
        return render_template("index.html")
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        college_name = request.form.get("college_name", "").strip()
        department = request.form.get("department", "").strip()

        errors = []
        if not 2 <= len(name) <= 100:
            errors.append("Name must be between 2 and 100 characters.")
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            errors.append("Please enter a valid email address.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters long.")
        if not 2 <= len(college_name) <= 150:
            errors.append("College name is required.")
        if len(department) > 100:
            errors.append("Department must be 100 characters or fewer.")

        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)
        connection = get_db()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if get_user_by_email(email):
                connection.rollback()
                flash("An account with this email already exists.", "error")
                return render_template("register.html")
            cursor = connection.execute(
                """
                INSERT INTO users (full_name, email, password_hash, college_name, department)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, email, hashed_password, college_name, department),
            )
            user_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO budgets (user_id, monthly_budget) VALUES (?, ?)",
                (user_id, 2000.0),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            if "users.email" not in str(error):
                raise
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        establish_role_session("student", "user_id", user_id)
        flash("Registration successful! Welcome to Student Cart.", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_user_by_email(email)
        if user and check_password_hash(user["password_hash"], password):
            establish_role_session("student", "user_id", user["id"])
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")
        return render_template("login.html")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.pop("user_id", None)
    if session.get("admin_id") is not None:
        session["active_role"] = "admin"
    else:
        session.clear()
    flash("You have been logged out.", "success")
    return redirect(
        url_for("admin_dashboard") if active_role() == "admin" else url_for("login")
    )


@app.route("/dashboard")
@login_required
def dashboard():
    if active_role() == "admin":
        return redirect(url_for("admin_dashboard"))
    user = get_user_by_id(session["user_id"])
    context = build_dashboard_context(session["user_id"])
    context["user"] = user
    context["recommendations"] = get_recommendations(session["user_id"])
    return render_template("dashboard.html", **context)


@app.route("/products")
@login_required
def products():
    user = get_user_by_id(session["user_id"])
    category = request.args.get("category", "all")
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "featured")

    max_price_input = request.args.get("max_price", "").strip()
    min_price_input = request.args.get("min_price", "").strip()
    max_price = None
    min_price = None
    if max_price_input:
        try:
            max_price = float(max_price_input)
            if max_price < 0 or not math.isfinite(max_price):
                raise ValueError
        except ValueError:
            flash("Enter a valid non-negative maximum price.", "error")
            max_price = None
    if min_price_input:
        try:
            min_price = float(min_price_input)
            if min_price < 0 or not math.isfinite(min_price):
                raise ValueError
        except ValueError:
            flash("Enter a valid non-negative minimum price.", "error")
            min_price = None
    if min_price is not None and max_price is not None and min_price > max_price:
        flash("Minimum price cannot be greater than maximum price.", "error")
        min_price = None
    in_stock = request.args.get("stock") == "available"
    products_list = find_products(
        query, category, max_price, in_stock, sort,
        min_price=min_price,
    )
    categories = get_db().execute(
        "SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category"
    ).fetchall()
    cart_summary = calculate_cart(session["user_id"])
    return render_template(
        "products.html",
        user=user,
        products=products_list,
        categories=categories,
        active_category=category,
        search_query=query,
        sort=sort,
        max_price=max_price_input,
        min_price=min_price_input,
        in_stock=in_stock,
        cart_count=cart_summary["item_count"],
    )


@app.route("/product/<int:product_id>")
@login_required
def product_detail(product_id):
    product = get_product_by_id(product_id)
    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("products"))
    product = with_product_pricing([product])[0]

    # Keep a bounded stack of recent product visits in the signed browser session.
    viewed_ids = session.get("recently_viewed", [])
    if not isinstance(viewed_ids, list):
        viewed_ids = []
    recent_stack = [product_id]
    seen_ids = {product_id}
    for viewed_id in viewed_ids:
        if isinstance(viewed_id, int) and viewed_id not in seen_ids:
            recent_stack.append(viewed_id)
            seen_ids.add(viewed_id)
        if len(recent_stack) == 6:
            break
    session["recently_viewed"] = recent_stack

    all_products = with_product_pricing(get_db().execute(
        """
        SELECT p.* FROM products p
        WHERE p.is_active = 1 AND p.stock > 0
        ORDER BY COALESCE(
            (SELECT AVG(pr.rating) FROM product_reviews pr WHERE pr.product_id = p.id),
            0
        ) DESC, p.price ASC
        """
    ).fetchall())
    related = [
        item for item in all_products
        if item["category"] == product["category"] and item["id"] != product_id
    ][:4]
    lower_price_alternatives = affordable_alternatives(product, all_products)
    recently_viewed = get_recently_viewed_products(exclude_ids=(product_id,))
    reviews = get_db().execute(
        """
        SELECT pr.*, u.name AS reviewer_name
        FROM product_reviews pr
        JOIN users u ON u.id = pr.user_id
        WHERE pr.product_id = ?
        ORDER BY pr.updated_at DESC
        LIMIT 20
        """,
        (product_id,),
    ).fetchall()
    review_summary = get_db().execute(
        """
        SELECT COUNT(*) AS review_count, AVG(rating) AS average_rating
        FROM product_reviews
        WHERE product_id = ?
        """,
        (product_id,),
    ).fetchone()
    my_review = get_db().execute(
        "SELECT rating, review_text FROM product_reviews WHERE product_id = ? AND user_id = ?",
        (product_id, session["user_id"]),
    ).fetchone()
    cart_summary = calculate_cart(session["user_id"])
    return render_template(
        "product_detail.html",
        product=product,
        related=with_review_summaries(related),
        lower_price_alternatives=with_review_summaries(lower_price_alternatives[:4]),
        recently_viewed=recently_viewed,
        reviews=reviews,
        review_count=review_summary["review_count"],
        average_rating=review_summary["average_rating"],
        my_review=my_review,
        cart_count=cart_summary["item_count"],
        user=get_user_by_id(session["user_id"]),
        is_wishlisted=get_db().execute(
            "SELECT 1 FROM wishlist_items WHERE user_id = ? AND product_id = ?",
            (session["user_id"], product_id),
        ).fetchone() is not None,
    )


@app.route("/product/<int:product_id>/reviews", methods=["POST"])
@login_required
def submit_product_review(product_id):
    product = get_product_by_id(product_id)
    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("products"))

    rating = request.form.get("rating", type=int)
    review_text = request.form.get("review_text", "").strip()
    if rating is None or rating < 1 or rating > 5:
        flash("Choose a rating from 1 to 5 stars.", "error")
    elif len(review_text) < 3 or len(review_text) > 1000:
        flash("Write a review between 3 and 1,000 characters.", "error")
    else:
        get_db().execute(
            """
            INSERT INTO product_reviews (user_id, product_id, rating, review_text)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, product_id) DO UPDATE SET
                rating = excluded.rating,
                review_text = excluded.review_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (session["user_id"], product_id, rating, review_text),
        )
        get_db().commit()
        flash("Your review has been saved.", "success")
    return redirect(url_for("product_detail", product_id=product_id) + "#reviews")


@app.route("/cart", methods=["GET", "POST"])
@login_required
def cart():
    user_id = session["user_id"]
    cart_summary = calculate_cart(user_id)
    if request.method == "POST":
        action = request.form.get("action")
        product_id = request.form.get("product_id", type=int)
        if action == "update":
            try:
                quantity = parse_quantity(request.form.get("quantity", ""))
            except ValueError as error:
                flash(str(error), "error")
                return redirect(url_for("cart"))
            if product_id is None or product_id <= 0:
                flash("Choose a valid product.", "error")
                return redirect(url_for("cart"))
            try:
                update_cart_quantity(user_id, product_id, quantity)
            except ValueError as error:
                flash(str(error), "error")
                return redirect(url_for("cart"))
            flash("Cart updated successfully.", "success")
        elif action == "remove":
            if product_id is None or product_id <= 0:
                flash("Choose a valid product.", "error")
                return redirect(url_for("cart"))
            cursor = get_db().execute(
                "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
                (user_id, product_id),
            )
            if cursor.rowcount == 0:
                flash("That product is not in your cart.", "error")
                return redirect(url_for("cart"))
            get_db().commit()
            flash("Item removed from cart.", "success")
        elif action == "clear":
            get_db().execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
            get_db().commit()
            flash("Your cart has been cleared.", "success")
        else:
            flash("Choose a valid cart action.", "error")
        return redirect(url_for("cart"))

    return render_template(
        "cart.html",
        cart=cart_summary,
        user=get_user_by_id(user_id),
        budget_summary=get_budget_summary(user_id),
    )


@app.route("/cart/add", methods=["POST"])
@login_required
def add_to_cart():
    product_id = request.form.get("product_id", type=int)
    try:
        quantity = parse_quantity(request.form.get("quantity", "1"), maximum=99)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("products"))
    if product_id is None or product_id <= 0:
        flash("Choose a valid product.", "error")
        return redirect(url_for("products"))
    try:
        product = add_product_quantity_to_cart(
            session["user_id"], product_id, quantity
        )
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("product_detail", product_id=product_id))
    flash("Item added to cart successfully.", "success")
    if request.form.get("buy_now") == "1":
        return redirect(url_for("checkout"))
    return redirect(request.referrer or url_for("products"))


@app.route("/budget", methods=["GET", "POST"])
@login_required
def budget():
    user_id = session["user_id"]
    if request.method == "POST":
        if request.form.get("action") == "reset":
            monthly_budget = 2000.0
        else:
            try:
                monthly_budget = float(request.form.get("monthly_budget", 0))
            except ValueError:
                flash("Enter a valid budget amount.", "error")
                return redirect(url_for("budget"))
            if not 0 < monthly_budget <= 10000000:
                flash("Budget must be greater than zero and no more than ₹1,00,00,000.", "error")
                return redirect(url_for("budget"))
        get_db().execute(
            """
            INSERT INTO budgets (user_id, monthly_budget, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET monthly_budget = excluded.monthly_budget, updated_at = excluded.updated_at
            """,
            (user_id, monthly_budget, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        get_db().commit()
        flash("Monthly budget updated successfully.", "success")
        return redirect(url_for("budget"))

    budget_summary = get_budget_summary(user_id)
    return render_template("budget.html", user=get_user_by_id(user_id), budget=budget_summary)


@app.route("/shopping-lists", methods=["GET", "POST"])
@login_required
def shopping_lists():
    user_id = session["user_id"]
    if request.method == "POST":
        list_name = request.form.get("list_name", "").strip()
        if not list_name:
            flash("List name cannot be empty.", "error")
            return redirect(url_for("shopping_lists"))
        get_db().execute(
            "INSERT INTO shopping_lists (user_id, name) VALUES (?, ?)",
            (user_id, list_name),
        )
        get_db().commit()
        flash("Shopping list created.", "success")
        return redirect(url_for("shopping_lists"))

    shopping_lists_data = get_db().execute(
        "SELECT * FROM shopping_lists WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    all_products = get_db().execute(
        "SELECT * FROM products WHERE is_active = 1 ORDER BY name ASC"
    ).fetchall()
    lists_with_items = []
    for shopping_list in shopping_lists_data:
        items = get_db().execute(
            """
            SELECT sli.*, p.name, p.price
            FROM shopping_list_items sli
            JOIN products p ON p.id = sli.product_id
            WHERE sli.list_id = ? AND p.is_active = 1
            ORDER BY sli.created_at DESC
            """,
            (shopping_list["id"],),
        ).fetchall()
        item_quantities = {item["product_id"]: item["quantity"] for item in items}
        items = with_product_pricing(items, quantities=item_quantities)
        total = sum(item["line_total"] for item in items)
        product_counts = {}
        for item in items:
            product_counts[item["product_id"]] = product_counts.get(item["product_id"], 0) + 1
        duplicate_count = sum(count - 1 for count in product_counts.values() if count > 1)
        lists_with_items.append({
            "list": shopping_list, "items": items, "total": round(total, 2),
            "duplicate_count": duplicate_count,
        })

    return render_template(
        "shopping_lists.html",
        user=get_user_by_id(user_id),
        lists=lists_with_items,
        products=with_product_pricing(all_products),
    )


@app.route("/shopping-list/<int:list_id>/add", methods=["POST"])
@login_required
def add_to_shopping_list(list_id):
    product_id = request.form.get("product_id", type=int)
    try:
        quantity = parse_quantity(request.form.get("quantity", "1"), maximum=99)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("shopping_lists"))
    assigned_to = request.form.get("assigned_to", "").strip()[:60]
    list_entry = get_db().execute(
        "SELECT * FROM shopping_lists WHERE id = ? AND user_id = ?",
        (list_id, session["user_id"]),
    ).fetchone()
    if not list_entry:
        flash("Shopping list not found.", "error")
        return redirect(url_for("shopping_lists"))
    product = get_product_by_id(product_id)
    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("shopping_lists"))
    get_db().execute(
        "INSERT INTO shopping_list_items (list_id, product_id, quantity, assigned_to) VALUES (?, ?, ?, ?)",
        (list_id, product_id, quantity, assigned_to),
    )
    get_db().commit()
    flash("Product added to shopping list.", "success")
    return redirect(url_for("shopping_lists"))


@app.route("/shopping-list/item/<int:item_id>/toggle", methods=["POST"])
@login_required
def toggle_shopping_list_item(item_id):
    item = get_db().execute(
        "SELECT sli.*, sl.user_id FROM shopping_list_items sli JOIN shopping_lists sl ON sl.id = sli.list_id WHERE sli.id = ?",
        (item_id,),
    ).fetchone()
    if not item or item["user_id"] != session["user_id"]:
        flash("You cannot modify this list item.", "error")
        return redirect(url_for("shopping_lists"))

    get_db().execute(
        "UPDATE shopping_list_items SET purchased = ? WHERE id = ?",
        (0 if item["purchased"] else 1, item_id),
    )
    get_db().commit()
    flash("Shopping list item updated.", "success")
    return redirect(url_for("shopping_lists"))


@app.route("/shopping-list/item/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_shopping_list_item(item_id):
    item = get_db().execute(
        "SELECT sli.*, sl.user_id FROM shopping_list_items sli JOIN shopping_lists sl ON sl.id = sli.list_id WHERE sli.id = ?",
        (item_id,),
    ).fetchone()
    if not item or item["user_id"] != session["user_id"]:
        flash("You cannot delete this item.", "error")
        return redirect(url_for("shopping_lists"))

    get_db().execute("DELETE FROM shopping_list_items WHERE id = ?", (item_id,))
    get_db().commit()
    flash("Item removed from the shopping list.", "success")
    return redirect(url_for("shopping_lists"))


@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    user_id = session["user_id"]
    cart_summary = calculate_cart(user_id)
    if not cart_summary["items"]:
        flash("Your cart is empty. Add products before checkout.", "error")
        return redirect(url_for("products"))

    if request.method == "POST":
        delivery_type = request.form.get("delivery_type", "pickup")
        delivery_address = request.form.get("delivery_address", "").strip()
        payment_method = request.form.get("payment_method", "cod")

        if delivery_type not in {"pickup", "delivery"}:
            flash("Please choose a valid delivery option.", "error")
            return render_template(
                "checkout.html", cart=cart_summary, user=get_user_by_id(user_id)
            )
        if delivery_type == "delivery" and not delivery_address:
            flash("Please provide a delivery address for home delivery.", "error")
            return render_template("checkout.html", cart=cart_summary, user=get_user_by_id(user_id))
        if len(delivery_address) > 500:
            flash("Delivery address must be 500 characters or fewer.", "error")
            return render_template(
                "checkout.html", cart=cart_summary, user=get_user_by_id(user_id)
            )

        if payment_method not in {"cod", "demo_wallet"}:
            flash("Please choose a valid payment method.", "error")
            return render_template("checkout.html", cart=cart_summary, user=get_user_by_id(user_id))

        get_db().execute("BEGIN IMMEDIATE")
        cart_summary = calculate_cart(user_id)
        if not cart_summary["items"]:
            get_db().rollback()
            flash("Your cart is empty. Add products before checkout.", "error")
            return redirect(url_for("products"))

        # Reprice the cart and validate stock while holding the write lock.
        order_queue = deque(cart_summary["items"])
        while order_queue:
            item = order_queue.popleft()
            product = get_product_by_id(item["product_id"])
            if product is None:
                get_db().rollback()
                flash("One or more products are unavailable.", "error")
                return redirect(url_for("cart"))
            if item["quantity"] > product["stock"]:
                get_db().rollback()
                flash(f"Not enough stock for {product['name']}. Please adjust your cart.", "error")
                return redirect(url_for("cart"))

        order_id = "CART-" + str(uuid.uuid4())[:8].upper()
        cursor = get_db().execute(
            """
            INSERT INTO orders (user_id, order_id, subtotal, discount_amount, total_amount, payment_method, delivery_type, delivery_address, order_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Confirmed')
            """,
            (
                user_id,
                order_id,
                cart_summary["subtotal"],
                cart_summary["discount_amount"],
                cart_summary["total"],
                payment_method,
                delivery_type,
                delivery_address if delivery_type == "delivery" else "Pickup at campus desk",
            ),
        )
        order_id_db = cursor.lastrowid

        order_queue = deque(cart_summary["items"])
        while order_queue:
            item = order_queue.popleft()
            get_db().execute(
                """
                INSERT INTO order_items (
                    order_id, product_id, product_name_at_purchase, quantity,
                    unit_price, subtotal, discount_applied
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id_db,
                    item["product_id"],
                    item["name"],
                    item["quantity"],
                    item["effective_price"],
                    item["line_total"],
                    item["discount_amount"],
                ),
            )
            stock_update = get_db().execute(
                """
                UPDATE products
                SET stock = stock - ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND stock >= ?
                """,
                (item["quantity"], item["product_id"], item["quantity"]),
            )
            if stock_update.rowcount != 1:
                get_db().rollback()
                flash(
                    f"Not enough stock for {item['name']}. Please adjust your cart.",
                    "error",
                )
                return redirect(url_for("cart"))
        get_db().execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
        get_db().commit()
        flash("Order placed successfully! Your order is confirmed.", "success")
        return redirect(url_for("order_success", order_number=order_id))

    return render_template("checkout.html", cart=cart_summary, user=get_user_by_id(user_id))


@app.route("/order-success/<order_number>")
@login_required
def order_success(order_number):
    order = get_db().execute(
        "SELECT * FROM orders WHERE user_id = ? AND order_id = ?",
        (session["user_id"], order_number),
    ).fetchone()
    if not order:
        flash("Order not found.", "error")
        return redirect(url_for("orders"))
    order_items = get_db().execute(
        """
        SELECT oi.*, COALESCE(NULLIF(oi.product_name_at_purchase, ''), p.name) AS name,
               p.image_url, p.category
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = ?
        """,
        (order["id"],),
    ).fetchall()
    return render_template("order_success.html", order=order, items=order_items, user=get_user_by_id(session["user_id"]))


@app.route("/orders")
@login_required
def orders():
    user_id = session["user_id"]
    orders_list = get_user_orders(user_id)
    return render_template("orders.html", orders=orders_list, user=get_user_by_id(user_id))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = get_user_by_id(session["user_id"])
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_profile":
            name = request.form.get("name", "").strip()
            college_name = request.form.get("college_name", "").strip()
            department = request.form.get("department", "").strip()
            if not 2 <= len(name) <= 100:
                flash("Name must be between 2 and 100 characters.", "error")
                return redirect(url_for("profile"))
            if not 2 <= len(college_name) <= 150:
                flash("College name is required.", "error")
                return redirect(url_for("profile"))
            if len(department) > 100:
                flash("Department must be 100 characters or fewer.", "error")
                return redirect(url_for("profile"))
            get_db().execute(
                "UPDATE users SET full_name = ?, college_name = ?, department = ? WHERE id = ?",
                (name, college_name, department, session["user_id"]),
            )
            get_db().commit()
            flash("Profile updated successfully.", "success")
        elif action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if not check_password_hash(user["password_hash"], current_password):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("profile"))
            if len(new_password) < 6:
                flash("New password must be at least 6 characters long.", "error")
                return redirect(url_for("profile"))
            if new_password != confirm_password:
                flash("New password and confirm password do not match.", "error")
                return redirect(url_for("profile"))
            get_db().execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new_password), session["user_id"]),
            )
            get_db().commit()
            flash("Password changed successfully.", "success")
        return redirect(url_for("profile"))

    return render_template("profile.html", user=get_user_by_id(session["user_id"]))


@app.route("/api/products")
def products_api():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "all")
    sort = request.args.get("sort", "featured")
    try:
        raw_min_price = request.args.get("min_price", "").strip()
        raw_max_price = request.args.get("max_price", "").strip()
        min_price = float(raw_min_price) if raw_min_price else None
        max_price = float(raw_max_price) if raw_max_price else None
    except ValueError:
        return jsonify(error="Price filters must be valid numbers."), 400
    if (
        (min_price is not None and (not math.isfinite(min_price) or min_price < 0))
        or (max_price is not None and (not math.isfinite(max_price) or max_price < 0))
        or (min_price is not None and max_price is not None and min_price > max_price)
    ):
        return jsonify(error="Choose a valid price range."), 400
    products_list = find_products(
        query=query,
        category=category,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        limit=100,
    )
    return jsonify([dict(product) for product in products_list])


@app.route("/api/products/<int:product_id>")
def product_api(product_id):
    product = get_product_by_id(product_id)
    if product is None:
        return jsonify(error="Product not found."), 404
    priced = with_review_summaries([product])[0]
    return jsonify(dict(priced))


@app.route("/api/cart")
def cart_api():
    user_id = session.get("user_id")
    if user_id is None or active_role() != "student":
        return jsonify(error="Please log in to view your cart."), 401
    summary = calculate_cart(user_id)
    return jsonify(
        {
            "items": [dict(item) for item in summary["items"]],
            "subtotal": summary["subtotal"],
            "discount_amount": summary["discount_amount"],
            "delivery_charge": summary["delivery_charge"],
            "total": summary["total"],
            "item_count": summary["item_count"],
        }
    )


@app.route("/api/health")
def health_api():
    connection = get_db()
    connection.execute("SELECT 1").fetchone()
    product_count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    return jsonify(
        status="ok",
        database="available",
        products=product_count,
    )


@app.route("/wishlist")
@login_required
def wishlist():
    products_list = get_db().execute(
        """
        SELECT p.* FROM wishlist_items wi
        JOIN products p ON p.id = wi.product_id
        WHERE wi.user_id = ? AND p.is_active = 1
        ORDER BY wi.created_at DESC
        """,
        (session["user_id"],),
    ).fetchall()
    return render_template(
        "wishlist.html",
        products=with_review_summaries(products_list),
        user=get_user_by_id(session["user_id"]),
    )


@app.route("/wishlist/toggle/<int:product_id>", methods=["POST"])
@login_required
def toggle_wishlist(product_id):
    product = get_product_by_id(product_id)
    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("products"))
    existing = get_db().execute(
        "SELECT 1 FROM wishlist_items WHERE user_id = ? AND product_id = ?",
        (session["user_id"], product_id),
    ).fetchone()
    if existing:
        get_db().execute(
            "DELETE FROM wishlist_items WHERE user_id = ? AND product_id = ?",
            (session["user_id"], product_id),
        )
        flash("Removed from your wishlist.", "success")
    else:
        get_db().execute(
            "INSERT INTO wishlist_items (user_id, product_id) VALUES (?, ?)",
            (session["user_id"], product_id),
        )
        flash("Added to your wishlist.", "success")
    get_db().commit()
    return redirect(request.referrer or url_for("wishlist"))


KIT_TYPES = {
    "First-Year Hostel Setup": "hostel bedsheet pillow laundry storage organizer",
    "Semester Study Kit": "notebook pen paper file folder ruler",
    "Exam Preparation Kit": "pen pencil eraser highlighter index cards notebook",
    "Practical Record Kit": "record notebook practical observation graph geometry",
    "International Stationery Kit": "korean japan japanese international stationery",
    "Custom Kit": "",
}


def parse_product_ids(raw_ids):
    product_ids = []
    for raw_id in raw_ids:
        try:
            product_id = int(raw_id)
        except (TypeError, ValueError) as error:
            raise ValueError("One of the selected products was invalid.") from error
        if product_id <= 0:
            raise ValueError("One of the selected products was invalid.")
        if product_id not in product_ids:
            product_ids.append(product_id)
    return product_ids


@app.route("/kit-planner", methods=["GET", "POST"])
@login_required
def kit_planner():
    user_id = session["user_id"]
    if request.method == "POST":
        department = request.form.get("department", "Other")
        semester = request.form.get("semester", type=int)
        needs = request.form.getlist("needs")
        try:
            kit_budget = float(request.form.get("kit_budget", "0"))
            if department not in DEPARTMENTS or semester is None or not 1 <= semester <= 12:
                raise ValueError("Choose a valid department and semester.")
            if not math.isfinite(kit_budget) or not 0 < kit_budget <= 10000000:
                raise ValueError("Kit budget must be between ₹0.01 and ₹1,00,00,000.")
            selected_ids = list(dict.fromkeys(
                int(raw_id) for raw_id in request.form.getlist("product_ids")
            ))
            if not selected_ids:
                raise ValueError("Select at least one item before adding a kit to your cart.")
            products = with_product_pricing(
                [product for product_id in selected_ids if (product := get_product_by_id(product_id))]
            )
            if len(products) != len(selected_ids):
                raise ValueError("A selected product is no longer available.")
            if sum(product["effective_price"] for product in products) > kit_budget:
                raise ValueError("Your selected kit exceeds its budget. Adjust the selection or budget.")
            add_products_to_cart(user_id, selected_ids)
        except (TypeError, ValueError) as error:
            flash(str(error), "error")
            return redirect(url_for(
                "kit_planner",
                department=department,
                semester=semester or 1,
                needs=needs,
                kit_budget=request.form.get("kit_budget", ""),
            ))
        flash("Your selected semester kit items were added to the cart.", "success")
        return redirect(url_for("cart"))

    department = request.args.get("department", "Other")
    if department not in DEPARTMENTS:
        department = "Other"
    try:
        semester = int(request.args.get("semester", "1"))
        if not 1 <= semester <= 12:
            raise ValueError
    except ValueError:
        semester = 1
    needs = [need for need in request.args.getlist("needs") if need in SEMESTER_NEEDS]
    if not needs:
        needs = ["notebooks", "writing"]
    try:
        kit_budget = float(request.args.get("kit_budget", get_budget_summary(user_id)["budget"]))
        if not math.isfinite(kit_budget) or not 0 < kit_budget <= 10000000:
            raise ValueError
    except ValueError:
        kit_budget = get_budget_summary(user_id)["budget"]

    products = with_review_summaries(
        get_db().execute(
            "SELECT * FROM products WHERE is_active = 1 AND stock > 0 ORDER BY name COLLATE NOCASE"
        ).fetchall()
    )
    recommendations = recommend_for_needs(products, needs, department, semester)
    recommended_ids = set()
    remaining_budget = kit_budget
    for product in recommendations:
        price = product["effective_price"]
        if price <= remaining_budget and len(recommended_ids) < 8:
            recommended_ids.add(product["id"])
            remaining_budget = round(remaining_budget - price, 2)
    recommended_id_order = [product["id"] for product in recommendations if product["id"] in recommended_ids]
    product_index = {product["id"]: product for product in products}
    ordered_products = [
        product_index[product_id]
        for product_id in [item["id"] for item in recommendations]
    ]
    recommended_set = {product["id"] for product in recommendations}
    ordered_products.extend(
        product for product in products if product["id"] not in recommended_set
    )
    return render_template(
        "kit_planner.html",
        user=get_user_by_id(user_id),
        products=ordered_products,
        recommendations=recommendations,
        recommended_ids=recommended_ids,
        recommended_id_order=recommended_id_order,
        budget=get_budget_summary(user_id),
        kit_budget=kit_budget,
        department=department,
        semester=semester,
        selected_needs=needs,
        departments=DEPARTMENTS,
        semester_needs=SEMESTER_NEEDS,
        kit_types=KIT_TYPES,
    )


@app.route("/hostel-move-in", methods=["GET", "POST"])
@login_required
def hostel_move_in():
    user_id = session["user_id"]
    if request.method == "POST":
        owned_items = [
            item for item in request.form.getlist("owned_items")
            if item in {key for key, *_ in HOSTEL_CHECKLIST}
        ]
        try:
            product_ids = parse_product_ids(request.form.getlist("product_ids"))
            add_products_to_cart(user_id, product_ids)
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("hostel_move_in", owned_items=owned_items))
        flash("Selected move-in essentials were added to your cart.", "success")
        return redirect(url_for("cart"))

    owned_items = set(
        item for item in request.args.getlist("owned_items")
        if item in {key for key, *_ in HOSTEL_CHECKLIST}
    )
    products = with_product_pricing(
        get_db().execute(
            "SELECT * FROM products WHERE is_active = 1 AND stock > 0"
        ).fetchall()
    )
    checklist = build_hostel_checklist(products)
    estimated_missing_total = 0.0
    for row in checklist:
        row["is_owned"] = row["key"] in owned_items
        row["estimated_price"] = (
            row["products"][0]["effective_price"]
            if row["products"] and not row["is_owned"]
            else 0.0
        )
        estimated_missing_total += row["estimated_price"]
    return render_template(
        "hostel_move_in.html",
        user=get_user_by_id(user_id),
        checklist=checklist,
        owned_items=owned_items,
        estimated_missing_total=round(estimated_missing_total, 2),
    )


@app.route("/budget-challenge", methods=["GET", "POST"])
@login_required
def budget_challenge():
    user_id = session["user_id"]
    if request.method == "POST":
        purpose = request.form.get("purpose", "everyday")
        try:
            budget_limit = float(request.form.get("budget", "0"))
            if purpose not in PURPOSE_TERMS:
                raise ValueError("Choose one of the listed shopping purposes.")
            if not math.isfinite(budget_limit) or not 0 < budget_limit <= 10000000:
                raise ValueError("Challenge budget must be between ₹0.01 and ₹1,00,00,000.")
            product_ids = parse_product_ids(request.form.getlist("product_ids"))
            if not product_ids:
                raise ValueError("Select at least one product for your challenge.")
            selected = with_product_pricing(
                [product for product_id in product_ids if (product := get_product_by_id(product_id))]
            )
            if len(selected) != len(product_ids):
                raise ValueError("A selected product is no longer available.")
            total = sum(product["effective_price"] for product in selected)
            if total > budget_limit:
                raise ValueError("Your selection exceeds the challenge budget.")
            add_products_to_cart(user_id, product_ids)
        except (TypeError, ValueError) as error:
            flash(str(error), "error")
            return redirect(url_for(
                "budget_challenge",
                purpose=purpose,
                budget=request.form.get("budget", ""),
            ))
        flash("Your budget challenge products were added to the cart.", "success")
        return redirect(url_for("cart"))

    purpose = request.args.get("purpose", "everyday")
    if purpose not in PURPOSE_TERMS:
        purpose = "everyday"
    try:
        budget_limit = float(request.args.get("budget", "500"))
        if not math.isfinite(budget_limit) or not 0 < budget_limit <= 10000000:
            raise ValueError
    except ValueError:
        budget_limit = 500.0
    products = with_product_pricing(
        get_db().execute(
            "SELECT * FROM products WHERE is_active = 1 AND stock > 0"
        ).fetchall()
    )
    recommendations, recommended_ids = build_budget_challenge(products, purpose, budget_limit)
    return render_template(
        "budget_challenge.html",
        user=get_user_by_id(user_id),
        products=recommendations,
        recommended_ids=set(recommended_ids),
        budget=budget_limit,
        purpose=purpose,
        purposes=PURPOSE_TERMS,
    )


@app.route("/compare", methods=["GET", "POST"])
@login_required
def compare_products():
    all_products = with_review_summaries(
        get_db().execute(
            "SELECT * FROM products WHERE is_active = 1 ORDER BY name COLLATE NOCASE"
        ).fetchall()
    )
    product_index = {product["id"]: product for product in all_products}
    selected_ids = []
    if request.method == "POST":
        try:
            selected_ids = parse_product_ids(request.form.getlist("product_ids"))
            if not 2 <= len(selected_ids) <= 3:
                raise ValueError("Choose two or three products to compare.")
            if any(product_id not in product_index for product_id in selected_ids):
                raise ValueError("One of the selected products could not be found.")
        except ValueError as error:
            flash(str(error), "error")
            selected_ids = []
    selected_products = [product_index[product_id] for product_id in selected_ids]
    return render_template(
        "compare.html",
        user=get_user_by_id(session["user_id"]),
        products=all_products,
        selected_products=selected_products,
        selected_ids=set(selected_ids),
    )


def current_admin():
    admin_id = session.get("admin_id")
    if admin_id is None:
        return None
    return get_db().execute(
        "SELECT * FROM admins WHERE id = ?",
        (admin_id,),
    ).fetchone()


def get_admin_categories():
    rows = get_db().execute(
        "SELECT name FROM categories ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [row["name"] for row in rows]


def valid_admin_email(email):
    return len(email) <= 254 and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)


def valid_admin_phone(phone):
    if not phone:
        return True
    return (
        re.fullmatch(r"[0-9+() -]{7,20}", phone)
        and sum(character.isdigit() for character in phone) >= 7
    )


def create_admin_account(name, email, phone, password, first_admin_only=False):
    name = name.strip()
    email = email.strip().lower()
    phone = phone.strip()
    if not 2 <= len(name) <= 100:
        raise ValueError("Admin name must be between 2 and 100 characters.")
    if not valid_admin_email(email):
        raise ValueError("Please enter a valid email address.")
    if not valid_admin_phone(phone):
        raise ValueError("Enter a valid phone number with at least 7 digits.")
    if len(password) < 8:
        raise ValueError("Admin passwords must be at least 8 characters long.")

    connection = get_db()
    connection.execute("BEGIN IMMEDIATE")
    try:
        admin_count = connection.execute(
            "SELECT COUNT(*) FROM admins"
        ).fetchone()[0]
        if first_admin_only and admin_count:
            raise ValueError(
                "An administrator already exists. Sign in as an admin to add another."
            )
        cursor = connection.execute(
            """
            INSERT INTO admins (full_name, email, phone_number, password_hash)
            VALUES (?, ?, ?, ?)
            """,
            (name, email, phone, generate_password_hash(password)),
        )
        connection.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        connection.rollback()
        if "admins.email" in str(error):
            raise ValueError("An administrator with this email already exists.") from error
        raise
    except Exception:
        connection.rollback()
        raise


@app.cli.command("create-admin")
def create_first_admin():
    """Create the first administrator from a trusted local terminal."""
    init_db()
    existing_admin = get_db().execute(
        "SELECT 1 FROM admins LIMIT 1"
    ).fetchone()
    if existing_admin:
        raise click.ClickException(
            "An administrator already exists. Sign in and create additional admins from Admin Accounts."
        )

    name = click.prompt("Admin name").strip()
    email = click.prompt("Admin email").strip().lower()
    phone = click.prompt("Admin phone number").strip()
    password = click.prompt(
        "Admin password", hide_input=True, confirmation_prompt=True
    )
    try:
        create_admin_account(
            name,
            email,
            phone,
            password,
            first_admin_only=True,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    click.echo("First administrator created. You can now sign in at /admin/login.")


@app.cli.command("reset-admin-password")
def reset_admin_password():
    """Reset an administrator password from a trusted local terminal."""
    init_db()
    email = click.prompt("Admin email").strip().lower()
    connection = get_db()
    admin = connection.execute(
        "SELECT id FROM admins WHERE email = ?",
        (email,),
    ).fetchone()
    if admin is None:
        raise click.ClickException("No administrator account was found with that email.")

    password = click.prompt(
        "New admin password", hide_input=True, confirmation_prompt=True
    )
    if len(password) < 8:
        raise click.ClickException("Admin passwords must be at least 8 characters long.")

    connection.execute("BEGIN IMMEDIATE")
    try:
        cursor = connection.execute(
            "UPDATE admins SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), admin["id"]),
        )
        if cursor.rowcount != 1:
            raise click.ClickException("Administrator account was not updated.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    click.echo("Administrator password updated. You can now sign in at /admin/login.")


def parse_product_form(allowed_categories):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "").strip()
    status = request.form.get("status", "active")
    errors = []
    if not 2 <= len(name) <= 120:
        errors.append("Product name must be between 2 and 120 characters.")
    if not 5 <= len(description) <= 2000:
        errors.append("Description must be between 5 and 2,000 characters.")
    if category not in allowed_categories:
        errors.append("Choose a valid product category.")
    if status not in {"active", "inactive"}:
        errors.append("Choose a valid product status.")

    try:
        original_price = Decimal(request.form.get("original_price", "").strip())
        discount_price = Decimal(request.form.get("discount_price", "").strip())
        if (
            not original_price.is_finite()
            or not discount_price.is_finite()
            or original_price <= 0
            or discount_price <= 0
            or original_price > Decimal("100000000")
            or discount_price > original_price
            or original_price != original_price.quantize(Decimal("0.01"))
            or discount_price != discount_price.quantize(Decimal("0.01"))
        ):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        errors.append(
            "Enter a valid discount price greater than zero and no higher than the original price."
        )
        original_price = Decimal("0")
        discount_price = Decimal("0")

    try:
        stock = int(request.form.get("stock", ""))
        if not 0 <= stock <= 1000000:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Stock must be a whole number between 0 and 1,000,000.")
        stock = 0

    return {
        "name": name,
        "description": description,
        "category": category,
        "original_price": float(original_price),
        "discount_price": float(discount_price),
        "stock": stock,
        "is_active": int(status == "active"),
    }, errors


def save_product_image(upload):
    if upload is None or not upload.filename:
        raise ValueError("Choose a product image.")

    safe_name = secure_filename(upload.filename)
    extension = os.path.splitext(safe_name)[1].lower()
    if extension not in PRODUCT_IMAGE_EXTENSIONS:
        raise ValueError("Upload a JPG, PNG, or WebP image.")

    content = upload.stream.read(MAX_PRODUCT_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_PRODUCT_IMAGE_BYTES:
        raise ValueError("Product images must be smaller than 3 MB.")
    signatures = {
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".jpeg": content.startswith(b"\xff\xd8\xff"),
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": (
            len(content) >= 12
            and content[:4] == b"RIFF"
            and content[8:12] == b"WEBP"
        ),
    }
    if not signatures[extension]:
        raise ValueError("The uploaded file does not match its image type.")

    filename = f"{uuid.uuid4().hex}{extension}"
    upload_directory = os.path.join(
        app.root_path, "static", "uploads", "products"
    )
    os.makedirs(upload_directory, exist_ok=True)
    with open(os.path.join(upload_directory, filename), "wb") as image_file:
        image_file.write(content)
    return filename


def remove_product_image(image_url):
    prefix = "/static/uploads/products/"
    if not image_url or not image_url.startswith(prefix):
        return
    filename = os.path.basename(image_url[len(prefix):])
    if not filename or filename != image_url[len(prefix):]:
        return
    image_path = os.path.join(
        app.root_path, "static", "uploads", "products", filename
    )
    if os.path.isfile(image_path):
        os.remove(image_path)


def render_admin_product_form(product=None, form_values=None):
    categories = get_admin_categories()
    if product and product["category"] not in categories:
        categories.append(product["category"])
    return render_template(
        "admin/product_form.html",
        admin=current_admin(),
        product=product,
        categories=categories,
        form_values=form_values or {},
    )


@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    stats = get_db().execute(
        """
        SELECT COUNT(*) AS total_products,
               COALESCE(SUM(is_active = 1), 0) AS active_products,
               COALESCE(SUM(is_active = 1 AND stock = 0), 0) AS out_of_stock_products
        FROM products
        """
    ).fetchone()
    order_stats = get_db().execute(
        """
        SELECT COUNT(*) AS total_orders,
               COALESCE(SUM(order_status = 'Pending'), 0) AS pending_orders,
               COALESCE(SUM(order_status = 'Completed'), 0) AS completed_orders
        FROM orders
        """
    ).fetchone()
    sales_summary = get_db().execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) AS sales_total,
               COALESCE(AVG(total_amount), 0) AS average_order
        FROM orders
        WHERE order_status != 'Cancelled'
        """
    ).fetchone()
    recent_products = get_db().execute(
        """
        SELECT id, name, category, price, original_price, stock, is_active, image_url, created_at
        FROM products ORDER BY created_at DESC, id DESC LIMIT 6
        """
    ).fetchall()
    recent_orders = get_db().execute(
        """
        SELECT o.id, o.order_id, o.order_status, o.total_amount, o.created_at,
               u.full_name AS student_name
        FROM orders o JOIN users u ON u.id = o.user_id
        ORDER BY o.created_at DESC, o.id DESC LIMIT 6
        """
    ).fetchall()
    return render_template(
        "admin/dashboard.html",
        admin=current_admin(),
        stats=stats,
        order_stats=order_stats,
        sales_summary=sales_summary,
        recent_products=recent_products,
        recent_orders=recent_orders,
    )


@app.route("/switch-view", methods=["POST"])
@app.route("/switch-to-student", methods=["POST"])
@app.route("/switch-to-admin", methods=["POST"])
def switch_view():
    target_role = request.form.get("target", "")
    if request.path == "/switch-to-student":
        target_role = "student"
    elif request.path == "/switch-to-admin":
        target_role = "admin"

    if target_role == "student":
        if "admin_id" not in session or current_admin() is None:
            session.pop("admin_id", None)
            if active_role() == "admin":
                session.pop("active_role", None)
            flash("Sign in with an administrator account before switching views.", "error")
            return redirect(url_for("admin_login"))
        session["active_role"] = "student"
        if "user_id" not in session or get_user_by_id(session["user_id"]) is None:
            session.pop("user_id", None)
            flash("You are viewing the student website. Log in to use your cart and account.", "info")
            return redirect(url_for("home"))
        flash("Switched to Student View.", "success")
        return redirect(url_for("dashboard"))

    if target_role == "admin":
        if "admin_id" not in session or current_admin() is None:
            session.pop("admin_id", None)
            flash("Verify an administrator account to switch to Admin View.", "error")
            return redirect(url_for("admin_login"))
        session["active_role"] = "admin"
        flash("Switched to Admin View.", "success")
        return redirect(url_for("admin_dashboard"))

    flash("Choose a valid view.", "error")
    if active_role() == "admin":
        return redirect(url_for("admin_dashboard"))
    if active_role() == "student":
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/admin/signup", methods=["GET", "POST"])
def admin_signup():
    admin = current_admin()
    is_admin = admin is not None and active_role() == "admin"
    admin_count = get_db().execute(
        "SELECT COUNT(*) FROM admins"
    ).fetchone()[0]
    first_admin_signup = admin_count == 0

    if "user_id" in session and not is_admin:
        flash("Student accounts cannot create administrator accounts.", "error")
        return redirect(url_for("admin_login"))
    if not first_admin_signup and not is_admin:
        return render_template(
            "admin/admin_signup.html",
            signup_available=False,
            admin=None,
        )

    if request.method == "POST":
        if not first_admin_signup and not is_admin:
            return render_template(
                "admin/admin_signup.html",
                signup_available=False,
                admin=None,
            ), 403

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = []
        if password != confirm_password:
            errors.append("Password and confirm password do not match.")
        if not errors:
            try:
                create_admin_account(
                    name,
                    email,
                    phone,
                    password,
                    first_admin_only=first_admin_signup and not is_admin,
                )
            except ValueError as error:
                errors.append(str(error))
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "admin/admin_signup.html",
                signup_available=first_admin_signup or is_admin,
                admin=admin,
            )
        if not is_admin:
            flash("Administrator account created. Please sign in.", "success")
            return redirect(url_for("admin_login"))
        flash("Additional administrator account created successfully.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template(
        "admin/admin_signup.html",
        signup_available=first_admin_signup or is_admin,
        admin=admin,
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if "admin_id" in session and current_admin() is not None:
        session["active_role"] = "admin"
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        admin = get_db().execute(
            "SELECT * FROM admins WHERE email = ?",
            (email,),
        ).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            establish_role_session("admin", "admin_id", admin["id"])
            flash("Logged in to the admin dashboard.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid administrator email or password.", "error")
    admin_count = get_db().execute(
        "SELECT COUNT(*) FROM admins"
    ).fetchone()[0]
    return render_template("admin/login.html", admin_count=admin_count)


@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    session.pop("admin_id", None)
    if session.get("user_id") is not None:
        session["active_role"] = "student"
    else:
        session.clear()
    flash("You have been logged out of the admin dashboard.", "success")
    return redirect(
        url_for("dashboard") if active_role() == "student" else url_for("admin_login")
    )


@app.route("/admin/products")
@app.route("/admin/manage-products")
@admin_required
def admin_products():
    products_list = get_db().execute(
        "SELECT * FROM products ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return render_template(
        "admin/products.html",
        admin=current_admin(),
        products=products_list,
    )


@app.route("/admin/categories", methods=["GET", "POST"])
@admin_required
def admin_categories():
    if request.method == "POST":
        action = request.form.get("action", "")
        category_name = request.form.get("category_name", "").strip()
        if action == "add":
            if not 2 <= len(category_name) <= 50:
                flash("Category name must be between 2 and 50 characters.", "error")
            else:
                try:
                    get_db().execute(
                        "INSERT INTO categories (name) VALUES (?)",
                        (category_name,),
                    )
                    get_db().commit()
                    flash("Category added.", "success")
                except sqlite3.IntegrityError as error:
                    get_db().rollback()
                    if "categories.name" not in str(error):
                        raise
                    flash("That category already exists.", "error")
        elif action == "delete":
            category_id = request.form.get("category_id", type=int)
            category = get_db().execute(
                "SELECT id, name FROM categories WHERE id = ?",
                (category_id,),
            ).fetchone()
            if category is None:
                flash("Category not found.", "error")
            else:
                product_count = get_db().execute(
                    "SELECT COUNT(*) FROM products WHERE category = ?",
                    (category["name"],),
                ).fetchone()[0]
                if product_count:
                    flash(
                        "This category is used by products. Move or delete those products first.",
                        "error",
                    )
                else:
                    get_db().execute(
                        "DELETE FROM categories WHERE id = ?",
                        (category_id,),
                    )
                    get_db().commit()
                    flash("Category deleted.", "success")
        else:
            flash("Choose a valid category action.", "error")
        return redirect(url_for("admin_categories"))

    categories = get_db().execute(
        """
        SELECT c.id, c.name, COUNT(p.id) AS product_count,
               COALESCE(SUM(p.is_active = 1), 0) AS active_product_count
        FROM categories c
        LEFT JOIN products p ON p.category = c.name
        GROUP BY c.id
        ORDER BY c.name COLLATE NOCASE
        """
    ).fetchall()
    return render_template(
        "admin/categories.html",
        admin=current_admin(),
        categories=categories,
    )


@app.route("/admin/products/<int:product_id>/preview")
@admin_required
def admin_product_preview(product_id):
    product = get_db().execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("admin_products"))
    return render_template(
        "admin/product_preview.html",
        admin=current_admin(),
        product=with_product_pricing([product])[0],
    )


@app.route("/admin/products/<int:product_id>/status", methods=["POST"])
@admin_required
def admin_toggle_product_status(product_id):
    product = get_db().execute(
        "SELECT id, is_active FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    if product is None:
        flash("Product not found.", "error")
    else:
        new_status = 0 if product["is_active"] else 1
        get_db().execute(
            """
            UPDATE products
            SET is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_status, product_id),
        )
        get_db().commit()
        flash(
            "Product activated." if new_status else "Product deactivated.",
            "success",
        )
    return redirect(url_for("admin_products"))


@app.route("/admin/products/new", methods=["GET", "POST"])
@app.route("/admin/add-product", methods=["GET", "POST"])
@admin_required
def admin_add_product():
    if request.method == "POST":
        product_data, errors = parse_product_form(set(get_admin_categories()))
        filename = None
        try:
            filename = save_product_image(request.files.get("product_image"))
        except ValueError as error:
            errors.append(str(error))
        if errors:
            if filename:
                remove_product_image(
                    url_for("static", filename=f"uploads/products/{filename}")
                )
            for message in errors:
                flash(message, "error")
            return render_admin_product_form(form_values=request.form)

        image_url = url_for("static", filename=f"uploads/products/{filename}")
        try:
            get_db().execute(
                """
                INSERT INTO products (
                    name, category, description, price, original_price, stock,
                    is_active, image_url, image_alt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_data["name"],
                    product_data["category"],
                    product_data["description"],
                    product_data["discount_price"],
                    product_data["original_price"],
                    product_data["stock"],
                    product_data["is_active"],
                    image_url,
                    product_data["name"],
                ),
            )
            get_db().commit()
        except sqlite3.Error:
            remove_product_image(image_url)
            raise
        flash("Product added. It is now available in the student catalogue.", "success")
        return redirect(url_for("admin_products"))
    return render_admin_product_form()


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@app.route("/admin/edit-product/<int:product_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id):
    product = get_db().execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("admin_products"))

    if request.method == "POST":
        allowed_categories = set(get_admin_categories())
        allowed_categories.add(product["category"])
        product_data, errors = parse_product_form(allowed_categories)
        upload = request.files.get("product_image")
        new_filename = None
        if upload and upload.filename:
            try:
                new_filename = save_product_image(upload)
            except ValueError as error:
                errors.append(str(error))
        if errors:
            if new_filename:
                remove_product_image(
                    url_for("static", filename=f"uploads/products/{new_filename}")
                )
            for message in errors:
                flash(message, "error")
            return render_admin_product_form(product, request.form)

        image_url = (
            url_for("static", filename=f"uploads/products/{new_filename}")
            if new_filename
            else product["image_url"]
        )
        try:
            get_db().execute(
                """
                UPDATE products SET
                    name = ?, category = ?, description = ?, price = ?,
                    original_price = ?, stock = ?, is_active = ?, image_url = ?,
                    image_alt = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    product_data["name"],
                    product_data["category"],
                    product_data["description"],
                    product_data["discount_price"],
                    product_data["original_price"],
                    product_data["stock"],
                    product_data["is_active"],
                    image_url,
                    product_data["name"],
                    product_id,
                ),
            )
            get_db().commit()
        except sqlite3.Error:
            if new_filename:
                remove_product_image(image_url)
            raise
        if new_filename:
            remove_product_image(product["image_url"])
        flash("Product details updated.", "success")
        return redirect(url_for("admin_products"))

    return render_admin_product_form(product)


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
@app.route("/admin/delete-product/<int:product_id>", methods=["POST"])
@admin_required
def admin_delete_product(product_id):
    connection = get_db()
    connection.execute("BEGIN IMMEDIATE")
    product = connection.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    if product is None:
        connection.rollback()
        flash("Product not found.", "error")
        return redirect(url_for("admin_products"))
    order_item = connection.execute(
        "SELECT 1 FROM order_items WHERE product_id = ? LIMIT 1",
        (product_id,),
    ).fetchone()
    if order_item:
        connection.rollback()
        flash(
            "This product is part of an order and cannot be deleted. Deactivate it instead.",
            "error",
        )
        return redirect(url_for("admin_products"))

    for table in (
        "cart_items",
        "wishlist_items",
        "shopping_list_items",
        "product_reviews",
        "product_offers",
    ):
        connection.execute(f"DELETE FROM {table} WHERE product_id = ?", (product_id,))
    connection.execute("DELETE FROM products WHERE id = ?", (product_id,))
    connection.commit()
    remove_product_image(product["image_url"])
    flash("Product deleted.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    orders_list = get_db().execute(
        """
        SELECT o.*, u.full_name AS student_name, u.email AS student_email,
               COUNT(oi.id) AS item_count,
               GROUP_CONCAT(
                   COALESCE(NULLIF(oi.product_name_at_purchase, ''), p.name)
                   || ' × ' || oi.quantity,
                   ', '
               ) AS items_summary
        FROM orders o
        JOIN users u ON u.id = o.user_id
        LEFT JOIN order_items oi ON oi.order_id = o.id
        LEFT JOIN products p ON p.id = oi.product_id
        GROUP BY o.id
        ORDER BY o.created_at DESC, o.id DESC
        """
    ).fetchall()
    return render_template(
        "admin/orders.html",
        admin=current_admin(),
        orders=orders_list,
    )


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def admin_update_order_status(order_id):
    new_status = request.form.get("status", "")
    allowed_statuses = {"Pending", "Confirmed", "Completed", "Cancelled"}
    if new_status not in allowed_statuses:
        flash("Choose a valid order status.", "error")
        return redirect(url_for("admin_orders"))

    connection = get_db()
    connection.execute("BEGIN IMMEDIATE")
    order = connection.execute(
        "SELECT id, order_status FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if order is None:
        connection.rollback()
        flash("Order not found.", "error")
        return redirect(url_for("admin_orders"))
    current_status = order["order_status"]
    if current_status == new_status:
        connection.rollback()
        flash("The order already has that status.", "error")
        return redirect(url_for("admin_orders"))
    if current_status in {"Cancelled", "Completed"}:
        connection.rollback()
        flash("Cancelled and completed orders cannot be changed.", "error")
        return redirect(url_for("admin_orders"))

    if new_status == "Cancelled":
        connection.execute(
            """
            UPDATE products
            SET stock = stock + (
                SELECT oi.quantity FROM order_items oi
                WHERE oi.order_id = ? AND oi.product_id = products.id
            ), updated_at = CURRENT_TIMESTAMP
            WHERE id IN (SELECT product_id FROM order_items WHERE order_id = ?)
            """,
            (order_id, order_id),
        )
    connection.execute(
        "UPDATE orders SET order_status = ? WHERE id = ?",
        (new_status, order_id),
    )
    connection.commit()
    flash(f"Order status changed to {new_status}.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/sales")
@admin_required
def admin_sales():
    totals = get_db().execute(
        """
        SELECT COUNT(*) AS order_count,
               COALESCE(SUM(total_amount), 0) AS sales_total,
               COALESCE(AVG(total_amount), 0) AS average_order
        FROM orders WHERE order_status != 'Cancelled'
        """
    ).fetchone()
    monthly_sales = get_db().execute(
        """
        SELECT strftime('%Y-%m', created_at) AS month,
               COUNT(*) AS order_count,
               SUM(total_amount) AS sales_total
        FROM orders
        WHERE order_status != 'Cancelled'
        GROUP BY strftime('%Y-%m', created_at)
        ORDER BY month DESC LIMIT 6
        """
    ).fetchall()
    popular_products = get_db().execute(
        """
        SELECT oi.product_name_at_purchase AS product_name,
               SUM(oi.quantity) AS units_sold,
               SUM(oi.subtotal) AS sales_total
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.order_status != 'Cancelled'
        GROUP BY oi.product_id, oi.product_name_at_purchase
        ORDER BY units_sold DESC, sales_total DESC
        LIMIT 8
        """
    ).fetchall()
    return render_template(
        "admin/sales.html",
        admin=current_admin(),
        totals=totals,
        monthly_sales=monthly_sales,
        popular_products=popular_products,
    )


@app.route("/admin/profile", methods=["GET", "POST"])
@admin_required
def admin_profile():
    admin = current_admin()
    if admin is None:
        session.clear()
        flash("Administrator account not found. Please sign in again.", "error")
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        errors = []
        if not 2 <= len(name) <= 100:
            errors.append("Admin name must be between 2 and 100 characters.")
        if not valid_admin_email(email):
            errors.append("Please enter a valid email address.")
        if not valid_admin_phone(phone):
            errors.append("Enter a valid phone number with at least 7 digits.")
        if new_password or confirm_password:
            if not check_password_hash(admin["password_hash"], current_password):
                errors.append("Enter your current password to change it.")
            if len(new_password) < 8:
                errors.append("New admin passwords must be at least 8 characters long.")
            if new_password != confirm_password:
                errors.append("New password and confirmation do not match.")
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("admin/profile.html", admin=admin)

        duplicate = get_db().execute(
            "SELECT 1 FROM admins WHERE email = ? AND id != ?",
            (email, admin["id"]),
        ).fetchone()
        if duplicate:
            flash("An administrator with this email already exists.", "error")
            return render_template("admin/profile.html", admin=admin)
        if new_password:
            get_db().execute(
                """
                UPDATE admins SET full_name = ?, email = ?, phone_number = ?,
                                  password_hash = ? WHERE id = ?
                """,
                (
                    name,
                    email,
                    phone,
                    generate_password_hash(new_password),
                    admin["id"],
                ),
            )
        else:
            get_db().execute(
                """
                UPDATE admins SET full_name = ?, email = ?, phone_number = ?
                WHERE id = ?
                """,
                (name, email, phone, admin["id"]),
            )
        get_db().commit()
        flash("Admin profile updated.", "success")
        return redirect(url_for("admin_profile"))
    return render_template("admin/profile.html", admin=admin)


if __name__ == "__main__":
    print("Student Cart backend starting.")
    print(f"SQLite database path: {DB_PATH}")
    try:
        product_count = init_db()
    except (OSError, sqlite3.Error) as error:
        app.logger.exception("Student Cart database initialization failed.")
        print(f"Database initialization failed: {error}")
        raise
    integrity_connection = get_db_connection()
    try:
        integrity_issues = integrity_connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
    finally:
        integrity_connection.close()
    app.config["STUDENT_CART_DATABASE_INITIALIZED"] = True
    print("Database initialization completed.")
    print("Required tables verified.")
    print(f"Products available: {product_count}")
    if integrity_issues:
        affected_tables = ", ".join(
            sorted({issue["table"] for issue in integrity_issues})
        )
        print(
            f"Warning: preserved legacy data has {len(integrity_issues)} "
            f"foreign-key issue(s) in {affected_tables}; no records were deleted."
        )
    port = int(os.environ.get("PORT", "5000"))
    print(f"Local development server: http://127.0.0.1:{port}")
    app.run(
        host="127.0.0.1",
        port=port,
        debug=environment == "development",
        use_reloader=False,
    )
