import sqlite3
import json
from datetime import datetime
from config import DATABASE_PATH
import os
from werkzeug.security import generate_password_hash, check_password_hash


def get_db():
    """Get a database connection."""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id TEXT UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            price INTEGER NOT NULL,
            bedrooms INTEGER,
            surface_area REAL,
            address TEXT,
            latitude REAL,
            longitude REAL,
            url TEXT,
            source TEXT DEFAULT 'immoweb',
            image_url TEXT,
            date_posted TEXT,
            date_discovered TEXT DEFAULT (datetime('now')),
            distance_to_station REAL,
            is_rented BOOLEAN DEFAULT 0,
            is_viewed BOOLEAN DEFAULT 0,
            is_unavailable BOOLEAN DEFAULT 0,
            walking_distance INTEGER,
            walking_route TEXT,
            notes TEXT,
            available_date TEXT,
            excluded BOOLEAN DEFAULT 0,
            exclusion_reason TEXT,
            features TEXT,
            last_checked TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_listings_external_id ON listings(external_id);
        CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price);
        CREATE INDEX IF NOT EXISTS idx_listings_bedrooms ON listings(bedrooms);

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    conn.commit()
    conn.close()


def register_user(email, password, name=''):
    """Register a new user."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), name)
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


def authenticate_user(email, password):
    """Authenticate a user. Returns user dict or None."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password_hash(user['password_hash'], password):
        return dict(user)
    return None


def get_user(user_id):
    """Get a user by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, created_at FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None


def add_listing(listing_data):
    """Add or update a listing in the database."""
    conn = get_db()
    cursor = conn.cursor()

    existing = None
    if listing_data.get("external_id"):
        cursor.execute(
            "SELECT id FROM listings WHERE external_id = ?",
            (listing_data["external_id"],)
        )
        existing = cursor.fetchone()

    if existing:
        fields = [
            "title", "description", "price", "bedrooms", "surface_area",
            "address", "latitude", "longitude", "url", "source",
            "image_url", "date_posted", "distance_to_station", "last_checked"
        ]
        updates = []
        values = []
        for field in fields:
            if field in listing_data and listing_data[field] is not None:
                updates.append(f"{field} = ?")
                values.append(listing_data[field])

        if updates:
            values.append(listing_data["external_id"])
            cursor.execute(
                f"UPDATE listings SET {', '.join(updates)} WHERE external_id = ?",
                values
            )
        conn.commit()
        conn.close()
        return existing["id"]

    fields = [
        "external_id", "title", "description", "price", "bedrooms",
        "surface_area", "address", "latitude", "longitude", "url",
        "source", "image_url", "date_posted", "distance_to_station",
        "date_discovered"
    ]
    placeholders = ", ".join(["?" for _ in fields])
    column_names = ", ".join(fields)

    values = []
    for field in fields:
        if field == "date_discovered":
            values.append(datetime.now().isoformat())
        else:
            values.append(listing_data.get(field))

    cursor.execute(
        f"INSERT INTO listings ({column_names}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    listing_id = cursor.lastrowid
    conn.close()
    return listing_id


def get_all_listings(filters=None):
    """Get all listings with optional filters."""
    conn = get_db()
    cursor = conn.cursor()

    query = "SELECT * FROM listings WHERE 1=1"
    params = []

    if filters:
        if "max_price" in filters:
            query += " AND price <= ?"
            params.append(filters["max_price"])
        if "min_bedrooms" in filters:
            query += " AND bedrooms >= ?"
            params.append(filters["min_bedrooms"])
        if "max_distance" in filters:
            query += " AND (distance_to_station IS NULL OR distance_to_station <= ?)"
            params.append(filters["max_distance"])
        if "show_rented" in filters and not filters["show_rented"]:
            query += " AND is_rented = 0"
        if "show_unavailable" in filters and not filters["show_unavailable"]:
            query += " AND is_unavailable = 0"
        if "show_excluded" in filters and not filters["show_excluded"]:
            query += " AND (excluded IS NULL OR excluded = 0)"
        if "show_viewed" in filters and filters["show_viewed"]:
            pass
        elif "show_viewed" in filters and not filters["show_viewed"]:
            query += " AND is_viewed = 0"
        if "source" in filters:
            query += " AND source = ?"
            params.append(filters["source"])

    query += " ORDER BY date_discovered DESC, price ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_listing(listing_id):
    """Get a single listing by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM listings WHERE id = ?", (listing_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_listing_status(listing_id, field, value):
    """Update a status field on a listing."""
    allowed_fields = ["is_viewed", "is_unavailable", "is_rented", "excluded"]
    if field not in allowed_fields:
        raise ValueError(f"Field must be one of {allowed_fields}")

    conn = get_db()
    cursor = conn.cursor()
    if field == "excluded":
        if isinstance(value, dict):
            cursor.execute(
                "UPDATE listings SET excluded = ?, exclusion_reason = ?, last_checked = datetime('now') WHERE id = ?",
                (1 if value.get('excluded') else 0, value.get('reason', ''), listing_id)
            )
        else:
            cursor.execute(
                "UPDATE listings SET excluded = ?, last_checked = datetime('now') WHERE id = ?",
                (1 if value else 0, listing_id)
            )
    else:
        cursor.execute(
            f"UPDATE listings SET {field} = ?, last_checked = datetime('now') WHERE id = ?",
            (1 if value else 0, listing_id)
        )
    conn.commit()
    conn.close()


def delete_listing(listing_id):
    """Delete a listing from the database."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()


def get_stats():
    """Get database statistics."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM listings")
    total = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) as viewed FROM listings WHERE is_viewed = 1")
    viewed = cursor.fetchone()["viewed"]
    cursor.execute("SELECT COUNT(*) as unavailable FROM listings WHERE is_unavailable = 1")
    unavailable = cursor.fetchone()["unavailable"]
    cursor.execute("SELECT COUNT(*) as excluded FROM listings WHERE excluded = 1")
    excluded = cursor.fetchone()["excluded"]
    cursor.execute(
        "SELECT COUNT(*) as available FROM listings WHERE is_unavailable = 0 AND is_rented = 0 AND (excluded IS NULL OR excluded = 0)"
    )
    available = cursor.fetchone()["available"]
    conn.close()
    return {
        "total": total,
        "viewed": viewed,
        "unavailable": unavailable,
        "excluded": excluded,
        "available": available,
    }
