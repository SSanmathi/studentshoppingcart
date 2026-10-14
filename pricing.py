"""Validated product-offer and cart pricing calculations."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


CENT = Decimal("0.01")


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Price and offer amounts must be valid numbers.") from error
    if not amount.is_finite():
        raise ValueError("Price and offer amounts must be finite.")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _offer_datetime(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError("Offer dates must use ISO date or datetime format.") from error


def validate_offer(offer, list_price):
    """Raise ValueError unless an offer is well-formed and bounded by list price."""
    price = _money(list_price)
    offer_type = offer.get("offer_type")
    value = _money(offer.get("value"))
    min_quantity = offer.get("min_quantity", 1)
    starts_at = _offer_datetime(offer.get("starts_at"))
    ends_at = _offer_datetime(offer.get("ends_at"))

    if starts_at.tzinfo is not None or ends_at.tzinfo is not None:
        raise ValueError("Offer dates must use timezone-free local timestamps.")
    if price <= 0:
        raise ValueError("Product list price must be greater than zero.")
    if offer_type not in {"percentage", "fixed"}:
        raise ValueError("Offer type must be percentage or fixed.")
    if type(min_quantity) is not int or min_quantity < 1:
        raise ValueError("Offer minimum quantity must be a positive integer.")
    if starts_at > ends_at:
        raise ValueError("Offer start date must not be after its end date.")
    if offer_type == "percentage" and not Decimal("0") < value < Decimal("100"):
        raise ValueError("Percentage offers must be greater than 0% and less than 100%.")
    if offer_type == "fixed" and not Decimal("0") < value <= price:
        raise ValueError("Fixed discounts must be positive and no greater than list price.")
    return value, starts_at, ends_at


def calculate_product_price(list_price, offers=(), quantity=1, now=None):
    """Calculate a single best offer; offers never stack."""
    price = _money(list_price)
    if price <= 0:
        raise ValueError("Product list price must be greater than zero.")
    if type(quantity) is not int or quantity < 1:
        raise ValueError("Quantity must be a positive integer.")

    current_time = now or datetime.now()
    available_offers = []
    eligible = []
    for raw_offer in offers:
        offer = dict(raw_offer)
        value, starts_at, ends_at = validate_offer(offer, price)
        if not offer.get("is_active", 1):
            continue
        if not starts_at <= current_time <= ends_at:
            continue

        offer["value"] = float(value)
        offer["min_quantity"] = int(offer.get("min_quantity", 1))
        available_offers.append(offer)
        if quantity < offer["min_quantity"]:
            continue

        if offer["offer_type"] == "percentage":
            per_unit_discount = (price * value / Decimal("100")).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
        else:
            per_unit_discount = value
        per_unit_discount = min(per_unit_discount, price)
        if per_unit_discount > 0:
            eligible.append((per_unit_discount, offer))

    best_offer = max(eligible, key=lambda candidate: candidate[0], default=None)
    unit_discount = best_offer[0] if best_offer else Decimal("0.00")
    unit_price = price - unit_discount
    subtotal = (price * quantity).quantize(CENT, rounding=ROUND_HALF_UP)
    discount_amount = (unit_discount * quantity).quantize(CENT, rounding=ROUND_HALF_UP)
    total = (subtotal - discount_amount).quantize(CENT, rounding=ROUND_HALF_UP)
    discount_percentage = (
        (discount_amount / subtotal * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if subtotal
        else Decimal("0.00")
    )

    return {
        "list_price": float(price),
        "effective_price": float(unit_price),
        "quantity": quantity,
        "subtotal": float(subtotal),
        "discount_amount": float(discount_amount),
        "total": float(total),
        "discount_percentage": float(discount_percentage),
        "applied_offer": best_offer[1] if best_offer else None,
        "available_offers": available_offers,
    }
