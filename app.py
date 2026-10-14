import sqlite3
import uuid
import re
import math
import os
import secrets
from collections import deque
from datetime import datetime

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import DB_PATH, get_db_connection, init_db

from catalog import find_products as search_catalog, index_products
from pricing import calculate_product_price
from seed import CATEGORY_IMAGES
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
)


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


def login_required(view):
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
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
    return get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()


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
        f"SELECT * FROM products WHERE id IN ({placeholders})",
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
            COALESCE((SELECT SUM(quantity) FROM cart_items WHERE user_id = ?), 0) AS cart_count,
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
        WHERE ci.user_id = ?
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
        "SELECT * FROM products ORDER BY created_at DESC LIMIT 8"
    ).fetchall()
    featured = get_db().execute(
        "SELECT * FROM products WHERE category = 'Stationery' AND featured = 1 ORDER BY price ASC LIMIT 6"
    ).fetchall()
    essential = get_db().execute(
        "SELECT * FROM products WHERE is_essential = 1 ORDER BY price ASC LIMIT 6"
    ).fetchall()
    cart_summary = calculate_cart(user_id)
    budget_summary = get_budget_summary(user_id)
    context = {
        "products": products,
        "catalog_count": get_db().execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "recently_viewed_products": get_recently_viewed_products(),
        "featured": featured,
        "essential": essential,
        "international_products": get_db().execute(
            "SELECT * FROM products WHERE is_international = 1 AND stock > 0 ORDER BY price ASC LIMIT 8"
        ).fetchall(),
        "hostel_products": get_db().execute(
            "SELECT * FROM products WHERE category = 'Hostel Essentials' AND stock > 0 ORDER BY featured DESC, price ASC LIMIT 8"
        ).fetchall(),
        "snack_products": get_db().execute(
            "SELECT * FROM products WHERE category = 'Hostel Essentials' AND subcategory = 'Food and Snacks' AND stock > 0 ORDER BY featured DESC, price ASC LIMIT 6"
        ).fetchall(),
        "books": get_db().execute(
            """
            SELECT p.* FROM products p
            WHERE p.category = 'Books' AND p.stock > 0
            ORDER BY p.featured DESC,
                COALESCE((SELECT AVG(pr.rating) FROM product_reviews pr WHERE pr.product_id = p.id), 0) DESC,
                p.price ASC
            LIMIT 6
            """
        ).fetchall(),
        "low_stock_products": get_db().execute(
            "SELECT * FROM products WHERE stock BETWEEN 1 AND 5 ORDER BY stock ASC, name ASC LIMIT 6"
        ).fetchall(),
        "budget_recommendations": get_db().execute(
            """
            SELECT p.* FROM products p
            WHERE p.stock > 0 AND p.price <= ?
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
        WHERE ci.user_id = ?
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
        WHERE ({category_filter})
        OR is_essential = 1
        OR featured = 1
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
    if "user_id" in session:
        return redirect(url_for("dashboard"))
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

        session.clear()
        session["user_id"] = user_id
        session.permanent = True
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
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")
        return render_template("login.html")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
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
        "SELECT DISTINCT category FROM products ORDER BY category"
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
        WHERE p.stock > 0
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
def add_to_cart():
    if "user_id" not in session:
        flash("Please log in before adding items to your cart.", "error")
        return redirect(url_for("login"))

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
        "SELECT * FROM products ORDER BY name ASC"
    ).fetchall()
    lists_with_items = []
    for shopping_list in shopping_lists_data:
        items = get_db().execute(
            """
            SELECT sli.*, p.name, p.price
            FROM shopping_list_items sli
            JOIN products p ON p.id = sli.product_id
            WHERE sli.list_id = ?
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
    if user_id is None:
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
        WHERE wi.user_id = ?
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
        get_db().execute("SELECT * FROM products WHERE stock > 0 ORDER BY name COLLATE NOCASE").fetchall()
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
        get_db().execute("SELECT * FROM products WHERE stock > 0").fetchall()
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
        get_db().execute("SELECT * FROM products WHERE stock > 0").fetchall()
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
        get_db().execute("SELECT * FROM products ORDER BY name COLLATE NOCASE").fetchall()
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
