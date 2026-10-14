"""In-memory catalog operations over products loaded from the persistent database."""


SEARCH_FIELDS = (
    "name",
    "category",
    "description",
    "brand",
    "subcategory",
    "tags",
    "intended_use",
    "specifications",
    "image_alt",
    "style_label",
    "country_label",
    "search_tags",
)


def index_products(products):
    """Build a hash-based product lookup keyed by the database product ID."""
    return {product["id"]: product for product in products}


def find_products(products, query="", category="all", max_price=None, in_stock=False, sort="featured", limit=None, min_price=None):
    """Search and filter a database-backed product list, then sort the results."""
    search_term = query.casefold().strip()
    category_term = (category or "all").casefold()
    matches = []

    for product in products:
        if category_term not in {"", "all"}:
            if category_term == "hostel":
                if not product["is_hostel"]:
                    continue
            elif category_term == "international":
                if not product["is_international"]:
                    continue
            elif category_term == "snacks":
                if product["subcategory"].casefold() != "food and snacks":
                    continue
            elif product["category"].casefold() != category_term:
                continue

        if search_term and not any(
            search_term in str(product[field] or "").casefold()
            for field in SEARCH_FIELDS
        ):
            continue
        if max_price is not None and product.get("effective_price", product["price"]) > max_price:
            continue
        if min_price is not None and product.get("effective_price", product["price"]) < min_price:
            continue
        if in_stock and product["stock"] <= 0:
            continue
        matches.append(product)

    sort_keys = {
        "low_high": lambda product: (product.get("effective_price", product["price"]), product["name"].casefold()),
        "high_low": lambda product: (-product.get("effective_price", product["price"]), product["name"].casefold()),
        "name": lambda product: product["name"].casefold(),
        "popular": lambda product: (
            -(product["customer_rating"] or 0),
            -product["featured"],
            product["name"].casefold(),
        ),
    }
    if sort in sort_keys:
        matches.sort(key=sort_keys[sort])
    else:
        matches.sort(
            key=lambda product: (
                -product["featured"],
                -(product["customer_rating"] or 0),
                -product["id"],
            )
        )
    return matches[:limit] if limit is not None else matches


def unique_products(products):
    """Remove duplicate product IDs while preserving the first occurrence."""
    seen_ids = set()
    unique = []
    for product in products:
        if product["id"] not in seen_ids:
            seen_ids.add(product["id"])
            unique.append(product)
    return unique