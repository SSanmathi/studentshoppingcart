"""Catalogue-backed recommendation helpers for student planning tools."""

from catalog import SEARCH_FIELDS


SEMESTER_NEEDS = {
    "notebooks": ("notebook", "record book", "drawing book"),
    "writing": ("pen", "pencil", "eraser", "sharpener"),
    "revision": ("highlighter", "index card", "sticky note"),
    "maths": ("calculator", "ruler", "geometry", "mathematical instrument"),
    "art": ("sketch", "watercolour", "paintbrush", "crayon", "drawing sheet"),
    "hostel": ("bedsheet", "pillow", "laundry", "storage", "mug", "bottle"),
    "computing": ("programming", "algorithm", "computer science", "python"),
}

DEPARTMENTS = (
    "Arts",
    "Commerce",
    "Computer Science",
    "Engineering",
    "Science",
    "Other",
)

PURPOSE_TERMS = {
    "exam": ("pen", "pencil", "eraser", "highlighter", "index card", "notebook"),
    "everyday": ("pen", "notebook", "folder", "sticky note", "ruler"),
    "hostel": ("bedsheet", "pillow", "soap", "toothpaste", "laundry", "bottle", "mug", "snack"),
}

HOSTEL_CHECKLIST = (
    ("bedding", "Bedding and room essentials", "Bedsheet", ("bedsheet",)),
    ("pillow", "Bedding and room essentials", "Pillow", ("pillow",)),
    ("storage", "Bedding and room essentials", "Room storage", ("storage box", "organizer", "shoe organizer")),
    ("toiletries", "Toiletries and personal care", "Personal care", ("soap", "shampoo", "toothpaste", "toothbrush", "tissue")),
    ("laundry", "Laundry supplies", "Laundry", ("laundry bag", "detergent")),
    ("study", "Stationery and study materials", "Study supplies", ("notebook", "pen", "desk organizer", "lamp", "ruler")),
    ("utensils", "Reusable utensils and bottles", "Kitchen and hydration", ("mug", "bottle", "container", "plate", "spoon")),
    ("snacks", "Snacks and food storage", "Food", ("snack", "biscuit", "noodles", "chocolate", "food storage")),
)


def product_text(product):
    return " ".join(
        str(product.get(field) or "")
        for field in SEARCH_FIELDS
    ).casefold()


def affordable_alternatives(product, products):
    """Return cheaper in-stock products with meaningful purpose/name overlap."""
    stop_words = {
        "this", "that", "with", "from", "your", "student", "study", "daily",
        "pack", "set", "for", "and", "the", "use", "item", "essentials",
    }
    source_terms = {
        word
        for word in product_text(product).split()
        if len(word) >= 3 and word not in stop_words
    }
    current_price = product.get("effective_price", product["price"])
    matches = []
    for candidate in products:
        if candidate["id"] == product["id"] or candidate["category"] != product["category"]:
            continue
        if candidate.get("stock", 0) <= 0:
            continue
        price = candidate.get("effective_price", candidate["price"])
        if price >= current_price:
            continue
        candidate_terms = {
            word
            for word in product_text(candidate).split()
            if len(word) >= 3 and word not in stop_words
        }
        overlap = source_terms & candidate_terms
        if not overlap:
            continue
        result = dict(candidate)
        result["price_difference"] = round(current_price - price, 2)
        result["similarity_terms"] = sorted(overlap)
        matches.append((len(overlap), price, candidate["name"].casefold(), result))
    matches.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [row[3] for row in matches]


def recommend_for_needs(products, needs, department="", semester=1):
    """Rank stocked catalogue products against selected study needs."""
    selected_terms = [
        term
        for need in needs
        for term in SEMESTER_NEEDS.get(need, ())
    ]
    if not selected_terms:
        selected_terms = list(SEMESTER_NEEDS["notebooks"] + SEMESTER_NEEDS["writing"])

    ranked = []
    for product in products:
        if product.get("stock", 0) <= 0:
            continue
        text = product_text(product)
        matched_terms = [term for term in selected_terms if term in text]
        if not matched_terms:
            continue
        score = len(matched_terms) * 10 + (5 if product.get("category") == "Books" else 0)
        if department == "Computer Science" and any(
            term in text for term in ("programming", "computer science", "algorithm", "python")
        ):
            score += 12
        if department == "Engineering" and any(
            term in text for term in ("geometry", "mathematical", "ruler", "drawing")
        ):
            score += 8
        if semester <= 2 and product.get("is_essential"):
            score += 2
        ranked.append((score, product.get("effective_price", product["price"]), product["name"].casefold(), product, matched_terms))

    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    recommendations = []
    for score, _, _, product, matched_terms in ranked:
        result = dict(product)
        result["recommendation_reason"] = "Matches: " + ", ".join(dict.fromkeys(matched_terms[:3]))
        result["recommendation_score"] = score
        recommendations.append(result)
    return recommendations


def build_hostel_checklist(products):
    """Associate each unique move-in checklist item with relevant products."""
    checklist = []
    for key, category, label, terms in HOSTEL_CHECKLIST:
        rows = []
        used_ids = set()
        for product in products:
            if product.get("stock", 0) <= 0:
                continue
            if not any(term in product_text(product) for term in terms):
                continue
            product_id = product.get("id")
            if product_id in used_ids:
                continue
            used_ids.add(product_id)
            rows.append(product)
        rows.sort(key=lambda product: (
            product.get("effective_price", product["price"]),
            product["name"].casefold(),
        ))
        checklist.append({"key": key, "category": category, "label": label, "products": rows})
    return checklist


def build_budget_challenge(products, purpose, budget):
    """Rank purpose-matched products and choose an affordable default basket."""
    terms = PURPOSE_TERMS.get(purpose, PURPOSE_TERMS["everyday"])
    candidates = []
    for product in products:
        if product.get("stock", 0) <= 0:
            continue
        text = product_text(product)
        score = sum(1 for term in terms if term in text)
        if score:
            candidates.append((
                -score,
                product.get("effective_price", product["price"]),
                product["name"].casefold(),
                product,
                score,
            ))
    candidates.sort()

    selected = []
    remaining = budget
    selected_categories = set()
    output = []
    for _, price, _, product, score in candidates:
        group = product.get("subcategory") or product.get("category")
        recommendation = dict(product)
        recommendation["recommendation_reason"] = (
            f"Matches {score} {purpose} shopping need{'s' if score != 1 else ''}."
        )
        is_selected = group not in selected_categories and price <= remaining and len(selected) < 8
        recommendation["recommended_selected"] = is_selected
        output.append(recommendation)
        if is_selected:
            selected.append(product["id"])
            selected_categories.add(group)
            remaining = round(remaining - price, 2)
    return output, selected
