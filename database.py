import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "student_cart.db")
LEGACY_DB_PATH = os.path.join(BASE_DIR, "campuscart.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

REQUIRED_TABLES = {
    "users",
    "products",
    "cart_items",
    "orders",
    "order_items",
    "product_reviews",
    "product_offers",
}


def _prepare_database_path(database_path):
    parent = os.path.dirname(os.path.abspath(database_path))
    os.makedirs(parent, exist_ok=True)
    if database_path != DB_PATH or os.path.exists(database_path):
        return

    if os.path.exists(LEGACY_DB_PATH):
        source = sqlite3.connect(LEGACY_DB_PATH)
        destination = sqlite3.connect(database_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()


def get_db_connection(database_path=DB_PATH):
    _prepare_database_path(database_path)
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _migrate_existing_schema(connection):
    migrations = {
        "users": {
            "department": "TEXT NOT NULL DEFAULT ''",
        },
        "products": {
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        },
        "cart_items": {
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        },
        "order_items": {
            "product_name_at_purchase": "TEXT NOT NULL DEFAULT ''",
            "subtotal": "REAL NOT NULL DEFAULT 0",
        },
    }

    user_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(users)")
    }
    if "full_name" not in user_columns and "name" in user_columns:
        connection.execute("ALTER TABLE users RENAME COLUMN name TO full_name")

    for table, additions in migrations.items():
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        for column, definition in additions.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )

    connection.execute(
        """
        UPDATE products
        SET updated_at = COALESCE(NULLIF(updated_at, ''), created_at, CURRENT_TIMESTAMP)
        """
    )
    connection.execute(
        """
        UPDATE cart_items
        SET updated_at = COALESCE(NULLIF(updated_at, ''), created_at, CURRENT_TIMESTAMP)
        """
    )
    connection.execute(
        """
        UPDATE order_items
        SET product_name_at_purchase = COALESCE(
                NULLIF(product_name_at_purchase, ''),
                (SELECT name FROM products WHERE products.id = order_items.product_id),
                ''
            ),
            subtotal = CASE
                WHEN subtotal = 0 THEN quantity * unit_price
                ELSE subtotal
            END
        """
    )

    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_products_name ON products(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_cart_user_product ON cart_items(user_id, product_id);
        CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_user_product ON product_reviews(user_id, product_id);

        CREATE TRIGGER IF NOT EXISTS validate_cart_quantity_insert
        BEFORE INSERT ON cart_items
        WHEN NEW.quantity < 1
        BEGIN
            SELECT RAISE(ABORT, 'Cart quantity must be positive');
        END;

        CREATE TRIGGER IF NOT EXISTS validate_cart_quantity_update
        BEFORE UPDATE OF quantity ON cart_items
        WHEN NEW.quantity < 1
        BEGIN
            SELECT RAISE(ABORT, 'Cart quantity must be positive');
        END;

        CREATE TRIGGER IF NOT EXISTS validate_product_values_insert
        BEFORE INSERT ON products
        WHEN NEW.price <= 0 OR NEW.stock < 0
        BEGIN
            SELECT RAISE(ABORT, 'Product price and stock are invalid');
        END;

        CREATE TRIGGER IF NOT EXISTS validate_product_values_update
        BEFORE UPDATE OF price, stock ON products
        WHEN NEW.price <= 0 OR NEW.stock < 0
        BEGIN
            SELECT RAISE(ABORT, 'Product price and stock are invalid');
        END;
        """
    )


def init_db(database_path=DB_PATH):
    connection = get_db_connection(database_path)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
            connection.executescript(schema_file.read())

        _migrate_existing_schema(connection)

        from seed import seed_products

        seed_products(connection)
        connection.commit()

        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing_tables = REQUIRED_TABLES - tables
        if missing_tables:
            raise sqlite3.DatabaseError(
                "Required tables were not initialized: "
                + ", ".join(sorted(missing_tables))
            )
        return connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
