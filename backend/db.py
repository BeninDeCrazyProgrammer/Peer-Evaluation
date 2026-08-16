import base64
import os
import libsql
import requests

_conn = None


class ResultSet:
    def __init__(self, cursor):
        self.rows = cursor.fetchall()
        self.columns = tuple(d[0] for d in cursor.description) if cursor.description else ()


class _FakeCursor:
    """Matches the cursor interface ResultSet expects (.fetchall(), .description),
    so TursoHTTPConnection.execute() is a drop-in for libsql's local cursor."""
    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = rows

    def fetchall(self):
        return self._rows

    @property
    def description(self):
        return [(c,) for c in self._columns] if self._columns else None


def _encode_value(v):
    """Python value -> Hrana typed Value, per Turso's HTTP API spec."""
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(v).decode("ascii")}
    return {"type": "text", "value": str(v)}


def _decode_value(cell):
    """Hrana typed Value (a row cell in the HTTP response) -> plain Python value."""
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "text":
        return cell["value"]
    if t == "blob":
        return base64.b64decode(cell["base64"])
    return cell.get("value")


class TursoHTTPConnection:
    """
    Minimal direct client for Turso's /v2/pipeline HTTP API
    (https://docs.turso.tech/sdk/http/reference).

    Exists because:
    - The official 'libsql' package's Rust TLS stack fails with
      'invalid peer certificate: UnknownIssuer' on some Windows setups —
      a known, open upstream bug (see tursodatabase/libsql issues,
      beekeeper-studio#2260), not specific to this project or network.
    - The older 'libsql-client' package targets the deprecated v1 HTTP
      endpoint, which returns response shapes it can't parse on current
      Turso servers (KeyError: 'result' on writes).

    This talks to the current, documented v2 API directly with `requests`,
    whose TLS stack (via certifi's CA bundle) is a different code path from
    libsql's bundled Rust TLS and isn't affected by that bug. A single
    execute() call is stateless (execute immediately followed by close).
    Multi-statement writes that need atomicity (e.g. a submission plus all
    its scores) go through execute_batch() instead, which runs BEGIN,
    every statement, and COMMIT inside one HTTP round-trip on one Hrana
    stream — see execute_batch() docstring.
    """

    def __init__(self, base_url, auth_token):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        })

    def execute(self, sql, args=None):
        stmt = {"sql": sql}
        if args:
            stmt["args"] = [_encode_value(a) for a in args]
        cursors = self._run([{"type": "execute", "stmt": stmt}, {"type": "close"}])
        return cursors[0] if cursors else _FakeCursor([], [])

    def _run(self, request_list):
        resp = self.session.post(
            f"{self.base_url}/v2/pipeline",
            json={"requests": request_list},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        cursors = []
        for result in data.get("results", []):
            if result.get("type") == "error":
                err = result.get("error", {})
                raise ValueError(f"Turso error: {err.get('message', err)}")
            response = result.get("response", {})
            if response.get("type") != "execute":
                continue
            stmt_result = response.get("result", {})
            cols = [c["name"] for c in stmt_result.get("cols", [])]
            rows = [tuple(_decode_value(cell) for cell in row) for row in stmt_result.get("rows", [])]
            cursors.append(_FakeCursor(cols, rows))
        return cursors

    def execute_batch(self, statements):
        """
        Run several (sql, args) statements as one atomic unit: BEGIN, each
        statement, COMMIT — all sent as a single pipeline request, so they
        share one Hrana stream/session instead of each getting its own
        stateless execute+close. That matters for two things:
          - Atomicity: if any statement errors, COMMIT is never reached, and
            closing the stream without a COMMIT rolls back everything that
            ran before the error — no partial writes.
          - `last_insert_rowid()` can be used in a later statement's args-free
            SQL to refer to the id an earlier INSERT in the same batch just
            created (see submissions.py submit()), since it's session-scoped.
        """
        requests_list = [{"type": "execute", "stmt": {"sql": "BEGIN"}}]
        for sql, args in statements:
            stmt = {"sql": sql}
            if args:
                stmt["args"] = [_encode_value(a) for a in args]
            requests_list.append({"type": "execute", "stmt": stmt})
        requests_list.append({"type": "execute", "stmt": {"sql": "COMMIT"}})
        requests_list.append({"type": "close"})
        self._run(requests_list)  # raises on any error result; COMMIT then never lands, close() rolls back

    def commit(self):
        pass  # each execute() already runs autocommit-style (execute + close)

    def close(self):
        self.session.close()


def get_connection():
    global _conn
    if _conn is None:
        url = os.environ.get("DB_URL", "file:db/local.db")
        auth_token = os.environ.get("DB_AUTH_TOKEN")

        if url.startswith("libsql://"):
            url = url.replace("libsql://", "https://")

        try:
            print(f"DEBUG: Attempting to connect to DB at {url}")
            if url.startswith("file:") or ("/" in url and not url.startswith("http")):
                # Local SQLite — unaffected by the remote TLS bug, keep using libsql.
                path = url.replace("file:", "")
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                _conn = libsql.connect(path)
            else:
                # Turso production — direct HTTP client (see TursoHTTPConnection docstring).
                _conn = TursoHTTPConnection(url, auth_token)
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


def batch_execute(statements):
    """
    Run several (sql, args) statements as a single atomic unit — all commit
    together or none do. Use this for any multi-row write where a partial
    result would corrupt data (e.g. one submission + all its scores); plain
    execute() calls in a loop each commit independently and can't be undone
    if a later one in the sequence fails.

    statements: list of (sql, args) tuples, in order. A later statement can
    reference last_insert_rowid() to pick up the id an earlier INSERT in the
    same batch just generated, without a round-trip back to Python.
    """
    conn = get_connection()
    if hasattr(conn, "execute_batch"):
        # TursoHTTPConnection: one pipeline request, real atomicity (see there).
        try:
            conn.execute_batch(statements)
        except Exception as e:
            print(f"SQL BATCH EXECUTION ERROR (Turso): {e}")
            raise
        return
    # Local libsql connection: explicit transaction, rolled back on any error.
    try:
        conn.execute("BEGIN")
        for sql, args in statements:
            conn.execute(sql, args or [])
        conn.commit()
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        print(f"SQL BATCH EXECUTION ERROR: {e}")
        raise


def close():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None