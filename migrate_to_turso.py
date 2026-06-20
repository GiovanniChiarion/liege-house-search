#!/usr/bin/env python3
import os
import sys
import sqlite3

from config import DATABASE_PATH


def main():
    turso_url = os.environ.get('TURSO_URL')
    turso_token = os.environ.get('TURSO_AUTH_TOKEN')

    if not turso_url or not turso_token:
        print("TURSO_URL and TURSO_AUTH_TOKEN environment variables required")
        sys.exit(1)

    if not os.path.exists(DATABASE_PATH):
        print(f"Local database not found: {DATABASE_PATH}")
        sys.exit(1)

    import libsql

    print(f"Connecting to Turso: {turso_url}")
    turso = libsql.connect(turso_url, auth_token=turso_token)
    local = sqlite3.connect(DATABASE_PATH)
    local.row_factory = sqlite3.Row

    print("Creating schema...")
    turso.executescript("""
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

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    print("Migrating listings...")
    local_rows = local.execute("SELECT * FROM listings").fetchall()
    columns = [d[0] for d in local.execute("SELECT * FROM listings LIMIT 0").description]
    cols_str = ", ".join(columns)
    placeholders = ", ".join(["?" for _ in columns])

    inserted = 0
    for row in local_rows:
        values = [row[c] for c in columns]
        try:
            turso.execute(
                f"INSERT OR IGNORE INTO listings ({cols_str}) VALUES ({placeholders})",
                values
            )
            inserted += 1
        except Exception as e:
            print(f"  Error inserting listing {row['id']}: {e}")
    turso.commit()
    print(f"  {inserted} listings migrated")

    print("Migrating users...")
    local_users = local.execute("SELECT * FROM users").fetchall()
    user_columns = [d[0] for d in local.execute("SELECT * FROM users LIMIT 0").description]
    user_cols_str = ", ".join(user_columns)
    user_placeholders = ", ".join(["?" for _ in user_columns])

    inserted_users = 0
    for row in local_users:
        values = [row[c] for c in user_columns]
        try:
            turso.execute(
                f"INSERT OR IGNORE INTO users ({user_cols_str}) VALUES ({user_placeholders})",
                values
            )
            inserted_users += 1
        except Exception as e:
            print(f"  Error inserting user {row['email']}: {e}")
    turso.commit()
    print(f"  {inserted_users} users migrated")

    local.close()
    turso.close()
    print("Migration complete!")


if __name__ == '__main__':
    main()
