"""
Single connection point for the database.

Dev:  DB_URL=file:db/local.db          (plain local SQLite file, no auth token needed)
Prod: DB_URL=libsql://<your-db>.turso.io   (or https://... — both are normalized to https://)
      DB_AUTH_TOKEN=<token from `turso db tokens create`>

Uses the 'libsql' package (Turso's current, actively maintained Python SDK —
not the older 'libsql-client', which is archived and has response-parsing
bugs against Turso's current HTTP protocol). Because Turso *is* SQLite
(libSQL) under the hood, the same connect-and-execute code works unchanged
against a local file or a remote Turso database — swapping envs is the
whole migration.
"""
import os
import libsql

_conn = None


class ResultSet:
    """Thin shim so callers can keep using rs.rows / rs.columns, matching
    the interface the rest of this codebase was written against."""
    def __init__(self, cursor):
        self.rows = cursor.fetchall()
        self.columns = tuple(d[0] for d in cursor.description) if cursor.description else ()


def get_connection():
    """Returns a shared libsql connection, created lazily."""
    global _conn
    if _conn is None:
        url = os.environ.get("DB_URL", "file:db/local.db")
        auth_token = os.environ.get("DB_AUTH_TOKEN") or None

        if url.startswith("file:"):
            # local SQLite file — make sure the containing folder exists
            path = url.split("file:", 1)[1]
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            _conn = libsql.connect(path)
        else:
            # Turso's dashboard shows libsql://..., which is a websocket
            # transport that has proven unreliable in practice. The HTTP
            # transport (https://) is what this package expects — normalize
            # rather than relying on everyone remembering to do so.
            if url.startswith("libsql://"):
                url = "https://" + url[len("libsql://"):]
            _conn = libsql.connect(database=url, auth_token=auth_token)
    return _conn


def execute(sql, args=None):
    """Run one statement, return a ResultSet (.rows, .columns)."""
    conn = get_connection()
    cursor = conn.execute(sql, args or [])
    result = ResultSet(cursor)
    conn.commit()
    return result


def batch(statements):
    """Run several statements (used for schema setup), one commit at the end."""
    conn = get_connection()
    for stmt in statements:
        conn.execute(stmt)
    conn.commit()


def close():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
