# Deploy Liège House Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the Flask app on Render free tier with Turso cloud SQLite for persistent data.

**Architecture:** Flask + Waitress on Render, libsql-client connecting to Turso remote DB. Dev mode uses local SQLite file. Consistent DB API via a wrapper in `db.py`.

**Tech Stack:** Flask, Waitress, libsql-client (Turso), Werkzeug, SQLite3

---

### Task 1: Clean up project files

**Files:**
- Delete: `debug_scraper.py`, `debug_scraper2.py`, `debug_scraper3.py`
- Delete: `test_scraper.py`, `test_extract.py`
- Delete: `debug_article.py`, `extract_listings.py`

- [ ] **Step 1: Remove unused debug/test scripts**

Run:
```bash
git rm debug_scraper.py debug_scraper2.py debug_scraper3.py test_scraper.py test_extract.py debug_article.py extract_listings.py
git status
```
Expected: 7 files deleted, shown in staged changes.

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: remove unused debug and test scripts"
```

---

### Task 2: Create `db.py` — database abstraction layer

**Files:**
- Create: `/home/giovanni/Documents/LiegeHouseSearch/db.py`

**Purpose:** Provide a `get_db()` function that returns a connection compatible with both sqlite3 (local dev) and libsql (Turso production). The Turso connection is wrapped to provide sqlite3.Row-compatible results so `models.py` requires minimal changes.

- [ ] **Step 1: Write `db.py`**

```python
import os
import sqlite3
from config import DATABASE_PATH

_conn = None

def get_db():
    global _conn
    if _conn is not None:
        return _conn

    turso_url = os.environ.get('TURSO_URL')
    turso_token = os.environ.get('TURSO_AUTH_TOKEN')

    if turso_url and turso_token:
        import libsql
        raw = libsql.connect(turso_url, auth_token=turso_token)
        _conn = _TursoConnection(raw)
    else:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _conn = conn

    return _conn


def close_db():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None


class _TursoConnection:
    """Wraps a libsql connection to provide sqlite3-compatible interface."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        result = self._conn.execute(sql, params or ())
        columns = [d[0] for d in result.description] if result.description else []
        return _TursoCursor(result, columns)

    def executescript(self, script):
        self._conn.executescript(script)

    def commit(self):
        self._conn.commit()

    def close(self):
        pass


class _TursoCursor:
    def __init__(self, result, columns):
        self._result = result
        self._columns = columns
        self.rowcount = getattr(result, 'rowcount', -1)
        self.lastrowid = getattr(result, 'lastrowid', None)
        self.description = result.description

    def fetchone(self):
        row = self._result.fetchone()
        return _TursoRow(row, self._columns) if row else None

    def fetchall(self):
        return [_TursoRow(r, self._columns) for r in self._result.fetchall()]


class _TursoRow:
    """Behaves like sqlite3.Row — supports dict() and [key] access."""

    def __init__(self, values, columns):
        self._values = values
        self._columns = columns
        self._dict = dict(zip(columns, values))

    def keys(self):
        return self._columns

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._dict[key]

    def __iter__(self):
        return iter(self._columns)

    def __len__(self):
        return len(self._values)
```

- [ ] **Step 2: Commit**

```bash
git add db.py && git commit -m "feat: add database abstraction layer with Turso support"
```

---

### Task 3: Update `models.py` to use `db.py`

**Files:**
- Modify: `/home/giovanni/Documents/LiegeHouseSearch/models.py`

**Changes:**
- Replace `get_db()` definition with `from db import get_db`
- Remove unused imports (`import os`, `import sqlite3` replaced by `from db import get_db, close_db`)
- Replace `except sqlite3.IntegrityError` with broad `except Exception` in `register_user()`

- [ ] **Step 1: Modify the top of models.py**

Replace:
```python
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
```

With:
```python
import json
from datetime import datetime
from db import get_db, close_db
from werkzeug.security import generate_password_hash, check_password_hash
```

- [ ] **Step 2: Update `init_db()`**

Replace:
```python
def init_db():
    """Initialize the database schema."""
    conn = get_db()
    cursor = conn.cursor()
    ...
    conn.close()
```

With:
```python
def init_db():
    """Initialize the database schema."""
    conn = get_db()
    cursor = conn.cursor()
    ...
    # Don't close connection for Turso (reused singleton)
    if not os.environ.get('TURSO_URL'):
        conn.close()
```

Wait, that still needs `import os`. Let me check if `config.py` imports are enough...

Actually, looking at this more carefully, `close_db()` handles the singleton pattern properly. For sqlite3 mode, we can still close after init (since get_db will reconnect on next call).

But actually, `_conn` in `db.py` is a module-level singleton. After `conn.close()`, the singleton is still set to the closed connection. Next call to `get_db()` returns the closed connection.

I need to either:
1. Not close in `init_db()` (connections will stay open)
2. Call `close_db()` instead and let `get_db()` reconnect next time

Option 1 is simpler. For a small app with few users, open connections are fine.

Actually, for the local SQLite case, the pattern was always open/close per request. Let me keep that pattern but handle the singleton properly:

For `db.py`:
- For SQLite: each `get_db()` opens a new connection (no singleton)
- For Turso: singleton connection (only one)

```python
_turso_conn = None

def get_db():
    global _turso_conn
    
    turso_url = os.environ.get('TURSO_URL')
    turso_token = os.environ.get('TURSO_AUTH_TOKEN')

    if turso_url and turso_token:
        if _turso_conn is None:
            import libsql
            raw = libsql.connect(turso_url, auth_token=turso_token)
            _turso_conn = _TursoConnection(raw)
        return _turso_conn
    else:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
```

This way, `init_db()` can call `.close()` on the connection freely for SQLite mode (each call gets a fresh connection), and for Turso mode, the singleton's close is a no-op.

Let me adjust `init_db()`:
```python
def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript("""...""")
    conn.commit()
    conn.close()
```

For SQLite: `conn.close()` closes this connection. Next `get_db()` opens a new one. ✓
For Turso: `conn.close()` is a no-op (TursoConnection.close() does nothing). ✓



Now for `register_user()`:
Replace:
```python
    except sqlite3.IntegrityError:
        conn.close()
        return None
```
With:
```python
    except Exception:
        conn.close()
        return None
```

And for `get_db()` in `models.py`, we're removing the old definition and importing from `db.py`. So `import os` from the top of models.py is no longer needed (it was only used in `get_db()` for `os.makedirs`).

Wait, `models.py` also uses `from config import DATABASE_PATH` but that's only used in the old `get_db()`. After switching to `from db import get_db`, that import is no longer needed.

Actually, let me check if `models.py` uses `DATABASE_PATH` anywhere else... No, it doesn't. And `import os` was only for `os.makedirs` in `get_db()`. So both can be removed.

Let me also check `import json` - used in `models.py` for the features field? Let me look... No, `json` isn't used in models.py currently. Wait, I see `import json` at line 2 of the current models.py. Let me search for its usage... It's imported but I don't see it being used. It might have been used in an earlier version. Let me keep it for safety or remove it.

Actually, let me just keep the models.py clean and only modify what's needed. I'll remove `import sqlite3`, `import os`, and `from config import DATABASE_PATH`, replace `get_db()` definition with the import, and fix the exception handler.

- [ ] **Step 2: Write the modified `models.py`**

Top of file changes:
- Remove: `import sqlite3`, `import os`, `from config import DATABASE_PATH`
- Add: `from db import get_db`
- Keep: `import json`, `from datetime import datetime`, `from werkzeug.security import ...`

In `register_user()`:
- Change `except sqlite3.IntegrityError:` to `except Exception:`

Remove entire old `get_db()` function (lines 9-16).

- [ ] **Step 3: Test that app starts**

Run: `python app.py`
Expected: Server starts on port 5000, no import errors.

- [ ] **Step 4: Commit**

```bash
git add models.py && git commit -m "refactor: use db.py for database connections"
```

---

### Task 4: Update `config.py` and `app.py` for production

**Files:**
- Modify: `/home/giovanni/Documents/LiegeHouseSearch/config.py`
- Modify: `/home/giovanni/Documents/LiegeHouseSearch/app.py`

- [ ] **Step 1: Add `create_app()` factory to `app.py` and env var secret key**

In `app.py`, add at the end (before `if __name__` block):

```python
def create_app():
    """Application factory for production (waitress/gunicorn)."""
    return app
```

At line 29, change:
```python
app.secret_key = 'liege-house-search-secret-key-change-in-production'
```
to:
```python
app.secret_key = os.environ.get('SECRET_KEY', 'liege-house-search-secret-key-change-in-production')
```

- [ ] **Step 2: Test locally**

Run: `python app.py`
Expected: Server starts on port 5000 with the same behavior.

- [ ] **Step 3: Commit**

```bash
git add app.py && git commit -m "feat: add create_app factory and env var secret key"
```

---

### Task 5: Create `requirements.txt`

**Files:**
- Create: `/home/giovanni/Documents/LiegeHouseSearch/requirements.txt`

- [ ] **Step 1: Write requirements.txt**

```
flask>=3.0
flask-cors>=4.0
werkzeug>=3.0
requests>=2.31
beautifulsoup4>=4.12
lxml>=5.0
waitress>=3.0
libsql-client>=0.1
playwright>=1.40
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt && git commit -m "chore: add requirements.txt"
```

---

### Task 6: Create migration script `migrate_to_turso.py`

**Files:**
- Create: `/home/giovanni/Documents/LiegeHouseSearch/migrate_to_turso.py`

- [ ] **Step 1: Write the migration script**

```python
#!/usr/bin/env python3
"""
Migrate local SQLite data to Turso cloud database.

Usage:
    TURSO_URL=libsql://... TURSO_AUTH_TOKEN=... python migrate_to_turso.py

Requires TURSO_URL and TURSO_AUTH_TOKEN environment variables.
"""
import os
import sys
import sqlite3

from config import DATABASE_PATH


def main():
    turso_url = os.environ.get('TURSO_URL')
    turso_token = os.environ.get('TURSO_AUTH_TOKEN')

    if not turso_url or not turso_token:
        print("❌ TURSO_URL and TURSO_AUTH_TOKEN environment variables required")
        sys.exit(1)

    if not os.path.exists(DATABASE_PATH):
        print(f"❌ Local database not found: {DATABASE_PATH}")
        sys.exit(1)

    import libsql

    print(f"📦 Connecting to Turso: {turso_url}")
    turso = libsql.connect(turso_url, auth_token=turso_token)
    local = sqlite3.connect(DATABASE_PATH)
    local.row_factory = sqlite3.Row

    # Create schema on Turso
    print("🏗️  Creating schema...")
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

    # Migrate listings
    print("📋 Migrating listings...")
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
            print(f"  ⚠️  Error inserting listing {row['id']}: {e}")
    turso.commit()
    print(f"  ✅ {inserted} listings migrated")

    # Migrate users
    print("👤 Migrating users...")
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
            print(f"  ⚠️  Error inserting user {row['email']}: {e}")
    turso.commit()
    print(f"  ✅ {inserted_users} users migrated")

    local.close()
    turso.close()
    print("🎉 Migration complete!")


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Commit**

```bash
git add migrate_to_turso.py && git commit -m "feat: add Turso migration script"
```

---

### Task 7: Update `.gitignore`

- [ ] **Step 1: Remove `data/*.db` from .gitignore so the local DB can be tracked (or keep for dev)**

The current `.gitignore` ignores `data/*.db`. Since the deployed app uses Turso, the local DB is only for dev. We can leave it ignored.

Add an entry for the `__pycache__` directory if not already present (it is).

Actually, no changes needed to `.gitignore` — the current settings are fine. The local DB stays local; Turso handles production data.

- [ ] **Step 1: Skip — .gitignore is fine as-is**

---

### Task 8: Install `libsql-client` and test locally

- [ ] **Step 1: Install libsql-client in venv**

```bash
source venv/bin/activate && pip install libsql-client
```

Expected: Package installed successfully.

- [ ] **Step 2: Start the app and verify it works in dev mode (SQLite local)**

```bash
source venv/bin/activate && python app.py &
sleep 2
curl -s http://localhost:5000/login | head -5
```

Expected: Login page HTML returned, no errors.

- [ ] **Step 3: Kill the test server**

```bash
kill %1 2>/dev/null; wait 2>/dev/null
```

---

### Task 9: Add two real users

**Note:** Passwords must be provided by the user via a secure channel (not in plain text in this conversation).

- [ ] **Step 1: Create users with `add_user.py`**

Once user provides passwords:
```bash
source venv/bin/activate
python add_user.py add "chiarion.giovanni@gmail.com" "<password>" "Giovanni"
python add_user.py add "maria.luisa.ratto@gmail.com" "<password>" "Maria Luisa"
python add_user.py list
```

Expected: Both users created, listed in output.

- [ ] **Step 2: Remove old test users (optional)**

If the old test users (giovanni@test.com, ragazza@test.com) should be removed:
```bash
python add_user.py delete "giovanni@test.com"
python add_user.py delete "ragazza@test.com"
```

- [ ] **Step 3: Commit**

```bash
git commit -am "feat: add real user accounts"
```

---

### Task 10: Deploy on Render

**Note:** Requires user to:
1. Sign up at render.com
2. Create a Turso account and database (or we guide them)
3. Provide TURSO_URL and TURSO_AUTH_TOKEN

- [ ] **Step 1: Guide user to create Turso database**

User needs to:
```bash
# Install Turso CLI
curl -sSfL https://get.turso.tech | sh

# Login and create DB
turso auth login
turso db create liege-house-search

# Get connection URL
turso db show liege-house-search --url

# Create auth token
turso db tokens create liege-house-search
```

Save the URL and token — they will be used as env vars on Render.

- [ ] **Step 2: Run migration to seed Turso with existing data**

```bash
TURSO_URL="libsql://liege-house-search-<user>.turso.io" \
TURSO_AUTH_TOKEN="<token>" \
source venv/bin/activate && python migrate_to_turso.py
```

- [ ] **Step 3: Deploy on Render**

User needs to:
1. Go to https://dashboard.render.com
2. Click "New +" → "Web Service"
3. Connect GitHub repo (or use "Public Git Repository" with this repo's URL)
4. Configure:
   - **Name**: `liege-house-search`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `waitress-serve --port=$PORT --call 'app:create_app'`
   - **Plan**: Free
5. Add Environment Variables:
   - `TURSO_URL`: `<from step 1>`
   - `TURSO_AUTH_TOKEN`: `<from step 1>`
   - `SECRET_KEY`: `<generate a random string>`
6. Click "Deploy Web Service"

- [ ] **Step 4: Verify deployment**

After deploy completes, visit the Render URL. Expected:
- Login page loads via HTTPS
- Can login with created credentials
- Listings are loaded from Turso
- Map, walking routes, filters all work

---

### Task 11: Final testing

- [ ] **Step 1: Test all API endpoints locally**

```bash
source venv/bin/activate && python -c "
import sys; sys.path.insert(0, '.')
from app import app
with app.test_client() as c:
    # No auth - should redirect
    r = c.get('/api/listings')
    print(f'GET /api/listings (no auth): {r.status_code}')
    
    # Login
    r = c.post('/login', data={'email': 'chiarion.giovanni@gmail.com', 'password': '<password>'}, follow_redirects=True)
    print(f'POST /login: {r.status_code}')
    
    # Auth test
    with c.session_transaction() as s:
        s['user_id'] = 1
    r = c.get('/api/listings')
    print(f'GET /api/listings (auth): {r.status_code}')
    r = c.get('/api/stats')
    print(f'GET /api/stats: {r.status_code}')
"
```

Expected: All endpoints return 200.

- [ ] **Step 2: Test on Render**

Visit the Render URL and:
1. Login with credentials
2. See listing cards on the page
3. Click a listing → modal opens
4. Toggle "Visto" status
5. Check the walking route loads
6. Apply filters
7. Logout, login again

- [ ] **Step 3: Final commit of any remaining changes**

```bash
git status
git add -A
git commit -m "chore: finalize deployment setup"
```
