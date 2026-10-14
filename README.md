# Student Cart – Smart Shopping for Students

Student Cart is a full-stack Flask application for college students to browse products, manage a personal cart, track their budget, create shopping lists, and complete checkout workflows.

## Features
- Student registration and login with password hashing
- Product listing and category/product filtering
- Product detail pages with stock-aware quantity selection
- Persistent cart with subtotal, discounts, and totals
- Monthly budget tracking and category spending breakdown
- Private shopping lists for semester/project planning
- Checkout flow with demo payment and order history
- Profile management with password update
- SQLite database with seeded sample products
- 75 sample catalogue items across Stationery, Books, and Hostel Essentials
- International stationery styles and a dedicated hostel essentials collection
- Global search suggestions, price/stock filters, and sorting
- Persistent wishlists, editable cart-budget tracking, and a kit planner
- Shopping lists with optional roommate assignment (private, not synchronized)
- Product-specific detail pages, lower-price alternatives, and recently viewed items
- Authenticated customer reviews with validated 1–5 star ratings and persisted averages
- Live low-stock warnings and a dedicated packaged-snacks category
- Python list/dictionary/set search, filtering, sorting, and FIFO checkout processing
- Responsive product cards with lazy-loaded local photos, accessible fallbacks, and photo category tiles
- Individually specified sample catalogue prices, clearly identified as estimates rather than live retailer prices
- Persisted date-limited Student Cart demo offers with percentage, fixed-amount, and minimum-quantity eligibility
- Backend-calculated, non-stacking offer discounts shared by product listings, details, cart, and checkout
- Discounts and customer ratings are shown only when a valid offer or saved review exists
- Smart Semester Kit recommendations adapt to department, semester, selected needs, and budget
- Hostel Move-In Planner marks owned items, estimates missing essentials, and adds selections to the cart
- Student Budget Challenge builds purpose-based catalogue baskets that remain within a chosen limit
- Product comparison displays two or three real catalogue listings side by side

## Project structure
- app.py – Flask routes and business logic
- pricing.py – validated, reusable product-offer and cart price calculations
- student_tools.py – department/need recommendations, hostel checklist matching, budget baskets, and relevant alternatives
- catalog.py – Python catalogue search, filtering, sorting, indexing, and de-duplication
- database.py – database connection and initialization helper
- schema.sql – SQLite schema
- seed.py – seed product dataset
- templates/ – Jinja templates for all pages
- static/css/style.css – app styling
- static/js/app.js – UI enhancements and toast handling

## Setup
1. Open a terminal in the project folder.
2. Create and activate a virtual environment if needed.
3. Install dependencies:
   python -m pip install -r requirements.txt
4. Run the app:
   python app.py
5. Open the browser at http://127.0.0.1:5000

For persistent login sessions across server restarts, set `STUDENT_CART_SECRET_KEY` to a stable random value before running the app. Without it, local development generates a temporary secret at startup.

## Default login
Use the registration page to create a new student account. The app creates a monthly budget automatically on first sign-up.

## Database initialization
The app initializes SQLite automatically on first launch. Sample products are inserted safely without duplicating data on subsequent runs. The active database is `data/student_cart.db`. If an existing root-level `campuscart.db` is present and the new file does not yet exist, SQLite's backup API copies it to the new location before applying additive schema migrations; the original file is left untouched.

Existing databases are migrated additively when the app starts. Verified catalogue photos and book covers are stored locally under `static/images/catalog/`; a small number of corrected product-specific photos use Unsplash CDN images and include a source link. Image failures fall back to a local stationery, book, or hostel-essentials illustration, and the alt text marks that fallback clearly. Product prices are demonstration listings, not live market prices. Country labels identify an inspired style only unless product origin is explicitly verified.

The existing schema is reused rather than duplicated: `cart_items` is the user's cart, `product_reviews` stores reviews, and `product_offers` stores current dated demo offers. The existing `name` user column is migrated to `full_name`; `order_items.unit_price` records the purchased unit price, and new purchase-name/subtotal snapshots are stored at checkout. Every application SQLite connection enables foreign-key enforcement. Database files are local runtime data and must not be committed.

The legacy database already contained two orphan references (one order and one budget pointing to a deleted user). The migration preserves these records rather than inventing accounts or deleting history, and startup reports the issue. New application writes use foreign-key enforcement.

Product details show only specifications present in the catalogue (including ISBNs for listed books). Customer ratings are calculated from saved reviews; listings without submitted reviews show “No reviews yet.” Signed-in students can add or update one review per product. Recently viewed product IDs are maintained as a short stack in the signed browser session. Checkout validates stock from SQLite and processes order lines FIFO.

Catalogue prices are sample estimates for this project, not supplier quotes or current market prices. Offers are stored per product in `product_offers`, have explicit validity dates and quantity terms, and are not represented as brand-sponsored. Only one eligible offer is applied to a line. Checkout recalculates cart prices and validates stock while holding a database write lock before confirming the demo order.

Run focused offer-calculation tests with:

```powershell
python -m unittest discover -s tests -v
```

## Backend demonstration in VS Code (Windows)

Open the project folder in VS Code and run these commands in its PowerShell terminal:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

The terminal prints the active SQLite path, confirms database initialization and required tables, reports the product count, and starts the local-only development server. Open **http://127.0.0.1:5000**. The real database check is **http://127.0.0.1:5000/api/health**; it runs `SELECT 1` and reports the database status and product count. Product JSON is available from `/api/products` and `/api/products/<id>`. The authenticated cart JSON is `/api/cart` and returns HTTP 401 when signed out.

`STUDENT_CART_ENV` defaults to `development` for this local run, where Flask debug mode is enabled and the server binds only to `127.0.0.1`. Production mode disables debug and requires a stable secret key. For example, set `STUDENT_CART_ENV=production` and `STUDENT_CART_SECRET_KEY` in the deployment environment; do not put the key in source control. Session cookies are HttpOnly and SameSite=Lax, and state-changing forms require a CSRF token.

The schema contains:

| Table | Purpose |
| --- | --- |
| `users` | Student name, unique email, password hash, college, department |
| `products` | Product catalogue, prices, stock, images, and specifications |
| `cart_items` | One quantity row per user/product |
| `orders` | User-owned order totals, payment method, delivery, and status |
| `order_items` | Purchased product and price snapshots |
| `product_reviews` | User-owned product ratings and review text |
| `product_offers` | Validated, date-bounded sample offers |
| `budgets`, `shopping_lists`, `wishlist_items` | Existing student planning features |

For a faculty demonstration, register a test student, sign in, search or filter for a catalogue product, add it to the cart, refresh to show persistence, change/remove its quantity, then place the existing demo checkout order. The Orders page shows that student's order history. No real payment is collected. To inspect the actual data, install the VS Code **SQLite** extension and open `data/student_cart.db`, or open the same file with DB Browser for SQLite. Select `users` to show a password hash (never the password), then inspect `products`, `cart_items`, `orders`, and `order_items`.

The browser sends HTTP requests to Flask routes; Flask validates the session and inputs, reads/writes SQLite using parameterized SQL and transactions, then returns rendered HTML or JSON. Prices and offers are recalculated from database records on the backend; submitted browser prices are never used.

## Additional student tools
- Search the complete catalogue by name, category, use, or stationery style; queries such as `washi tape` and `under 100` work across the catalogue.
- Update the shopping budget from the Budget page. Remaining balance is calculated from the active cart total.
- Use the Kit Planner to select items before confirming an add-to-cart action.
- Use Smart Semester Kit, Hostel Move-In Planner, and Budget Challenge from the Student tools menu or dashboard.
- Compare any two or three catalogue products at `/compare`.
- Wishlists and shopping lists are tied to the signed-in account. Shopping lists are not shared or synchronized with roommates; roommate names are optional assignments only.

## Notes
- The app uses demo payment methods only; no real card data is collected.
- Stock is reduced only after a successful order.
- Each student sees their own cart, orders, budget, and lists.
- Default budget is ₹2,000 and can be changed or reset at any time.
