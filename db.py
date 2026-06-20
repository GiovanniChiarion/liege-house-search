import os
import sqlite3
from config import DATABASE_PATH

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

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def close_db():
    global _turso_conn
    if _turso_conn is not None:
        try:
            _turso_conn.close()
        except Exception:
            pass
        _turso_conn = None


class _TursoConnection:
    """Wraps libsql connection to provide sqlite3-compatible interface."""

    def __init__(self, conn):
        self._conn = conn
        self._last_cursor = None

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        result = self._conn.execute(sql, params or ())
        columns = [d[0] for d in result.description] if result.description else []
        self._last_cursor = _TursoCursor(result, columns)
        return self._last_cursor

    def executescript(self, script):
        self._conn.executescript(script)

    def commit(self):
        self._conn.commit()

    def close(self):
        pass

    @property
    def rowcount(self):
        return self._last_cursor.rowcount if self._last_cursor else -1

    @property
    def lastrowid(self):
        return self._last_cursor.lastrowid if self._last_cursor else None

    def fetchone(self):
        return self._last_cursor.fetchone() if self._last_cursor else None

    def fetchall(self):
        return self._last_cursor.fetchall() if self._last_cursor else None


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
