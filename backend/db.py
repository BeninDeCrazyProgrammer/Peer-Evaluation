import os
import libsql
import logging

_conn = None

class ResultSet:
    def __init__(self, cursor):
        self.rows = cursor.fetchall()
        self.columns = tuple(d[0] for d in cursor.description) if cursor.description else ()

def get_connection():
    global _conn
    if _conn is None:
        url = os.environ.get("DB_URL", "file:db/local.db")
        auth_token = os.environ.get("DB_AUTH_TOKEN")
        
        # Normalize Turso URL for the Python Driver
        if url.startswith("libsql://"):
            url = url.replace("libsql://", "https://")
        
        try:
            print(f"DEBUG: Attempting to connect to DB at {url}")
            if url.startswith("file:") or "/" in url and not url.startswith("http"):
                # Local SQLite
                path = url.replace("file:", "")
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                _conn = libsql.connect(path)
            else:
                # Turso Production
                _conn = libsql.connect(database=url, auth_token=auth_token)
            print("DEBUG: DB Connection successful")
        except Exception as e:
            print(f"DATABASE CONNECTION ERROR: {e}")
            raise e
    return _conn

def execute(sql, args=None):
    try:
        conn = get_connection()
        cursor = conn.execute(sql, args or [])
        result = ResultSet(cursor)
        conn.commit()
        return result
    except Exception as e:
        print(f"SQL EXECUTION ERROR: {e}")
        raise e

def batch(statements):
    conn = get_connection()
    for stmt in statements:
        conn.execute(stmt)
    conn.commit()