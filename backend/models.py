"""
Schema for the peer evaluation system.

Plain SQL, run through db.batch() — works identically against local SQLite
and Turso since both speak the same dialect (libSQL).
"""
from db import batch

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS lecturers (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        email         TEXT NOT NULL UNIQUE,
        password_hash TEXT,              -- NULL if the account only ever used Google login
        google_id     TEXT UNIQUE,       -- NULL if the account only ever used a password
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS courses (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        lecturer_id  INTEGER NOT NULL REFERENCES lecturers(id),
        name         TEXT NOT NULL,
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS groups (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id   INTEGER NOT NULL REFERENCES courses(id),
        group_label TEXT NOT NULL          -- e.g. "Group 1"
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS students (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id    INTEGER NOT NULL REFERENCES groups(id),
        name        TEXT NOT NULL,
        student_id  TEXT NOT NULL,         -- school ID, as text (some IDs have leading zeros)
        UNIQUE(group_id, student_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id   INTEGER NOT NULL REFERENCES courses(id),
        title       TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'closed'
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluation_criteria (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        evaluation_id  INTEGER NOT NULL REFERENCES evaluations(id),
        name           TEXT NOT NULL,
        sort_order     INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluation_scale (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        evaluation_id  INTEGER NOT NULL REFERENCES evaluations(id),
        value          INTEGER NOT NULL,     -- e.g. 0..4, or 1..5, lecturer's choice
        label          TEXT NOT NULL,        -- e.g. "Unacceptable", "Excellent/Outstanding"
        UNIQUE(evaluation_id, value)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS submissions (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        evaluation_id         INTEGER NOT NULL REFERENCES evaluations(id),
        evaluator_student_id  INTEGER NOT NULL REFERENCES students(id),
        submitted_at          TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(evaluation_id, evaluator_student_id)   -- enforces one submission per student, no re-submit
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS submission_scores (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id    INTEGER NOT NULL REFERENCES submissions(id),
        ratee_student_id INTEGER NOT NULL REFERENCES students(id),
        criterion_id     INTEGER NOT NULL REFERENCES evaluation_criteria(id),
        score            INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_groups_course ON groups(course_id)",
    "CREATE INDEX IF NOT EXISTS idx_students_group ON students(group_id)",
    "CREATE INDEX IF NOT EXISTS idx_evaluations_course ON evaluations(course_id)",
    "CREATE INDEX IF NOT EXISTS idx_submissions_eval ON submissions(evaluation_id)",
    "CREATE INDEX IF NOT EXISTS idx_scores_submission ON submission_scores(submission_id)",
    "CREATE INDEX IF NOT EXISTS idx_scores_ratee ON submission_scores(ratee_student_id)",
]


def init_db():
    batch(SCHEMA)
    print("Database schema ready.")


if __name__ == "__main__":
    from db import close
    init_db()
    close()  # otherwise the libsql background thread keeps a one-off script alive
