"""
Data layer for the peer evaluation system.

This is a small active-record style layer, not full SQLAlchemy. Reason:
Turso's SQLAlchemy dialect (`sqlalchemy-libsql`) only supports Linux/macOS,
so it would break on a Windows dev machine. This module gets the same
practical win people want from an ORM -- one place per table that owns its
columns and queries, no raw SQL scattered across route files -- while
sitting directly on db.execute()/db.batch(), which already works
identically on every platform against local SQLite (dev) and Turso (prod).

Every route file should go through a Model class below, not `db.execute`
directly. Simple lookups use the generic Model helpers (find/where/create/
update/delete). Anything that needs a JOIN or an aggregate lives as a named
classmethod near the model it's most about (e.g. Group.with_students,
Evaluation.results) so it stays a one-line call from the route.
"""
from werkzeug.security import generate_password_hash, check_password_hash
from db import execute, batch


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

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
        pin_hash    TEXT,                  -- NULL until the student claims a PIN on first access
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


def _migrate_student_pins():
    """
    One-time migration for databases created before self-serve PINs existed.
    CREATE TABLE IF NOT EXISTS doesn't add columns to an existing table, so
    older DBs need this ALTER TABLE run explicitly. Safe to call every boot —
    it's a no-op once the column exists.

    Anyone migrating off the earlier lecturer-distributed-PIN design lands
    here too: those PINs were never actually handed to students, so there's
    nothing to preserve — everyone just claims fresh on their next visit.
    """
    cols = [row[1] for row in execute("PRAGMA table_info(students)").rows]
    if "pin_hash" not in cols:
        execute("ALTER TABLE students ADD COLUMN pin_hash TEXT")
    if "pin" in cols:
        # Leftover from the old pre-shared-PIN column; no longer read anywhere.
        # SQLite/libsql's ALTER TABLE DROP COLUMN support is inconsistent
        # across versions, so it's left in place rather than risk breaking
        # the migration — harmless, just an unused column.
        pass


def init_db():
    batch(SCHEMA)
    _migrate_student_pins()
    print("Database schema ready.")


# --------------------------------------------------------------------------
# Base model
# --------------------------------------------------------------------------

class Model:
    """Generic active-record helpers shared by every table below."""

    table = None
    columns = ()

    def __init__(self, **data):
        for col in self.columns:
            setattr(self, col, data.get(col))

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.to_dict()}>"

    @classmethod
    def _from_row(cls, row, cols):
        return cls(**dict(zip(cols, row)))

    @classmethod
    def _from_rows(cls, rs):
        return [cls._from_row(row, rs.columns) for row in rs.rows]

    @classmethod
    def find(cls, id):
        """Fetch one row by primary key, or None."""
        rs = execute(f"SELECT * FROM {cls.table} WHERE id = ?", [id])
        return cls._from_row(rs.rows[0], rs.columns) if rs.rows else None

    @classmethod
    def where(cls, order_by=None, **filters):
        """Fetch every row matching column=value filters (AND'ed together)."""
        sql = f"SELECT * FROM {cls.table}"
        if filters:
            sql += " WHERE " + " AND ".join(f"{k} = ?" for k in filters)
        if order_by:
            sql += f" ORDER BY {order_by}"
        rs = execute(sql, list(filters.values()))
        return cls._from_rows(rs)

    @classmethod
    def first(cls, order_by=None, **filters):
        rows = cls.where(order_by=order_by, **filters)
        return rows[0] if rows else None

    @classmethod
    def exists(cls, **filters):
        return cls.first(**filters) is not None

    @classmethod
    def create(cls, **fields):
        cols = list(fields.keys())
        placeholders = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO {cls.table} ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *"
        rs = execute(sql, list(fields.values()))
        return cls._from_row(rs.rows[0], rs.columns)

    def update(self, **fields):
        clause = ", ".join(f"{k} = ?" for k in fields)
        execute(f"UPDATE {self.table} SET {clause} WHERE id = ?", list(fields.values()) + [self.id])
        for k, v in fields.items():
            setattr(self, k, v)
        return self

    @classmethod
    def delete_where(cls, **filters):
        clause = " AND ".join(f"{k} = ?" for k in filters)
        execute(f"DELETE FROM {cls.table} WHERE {clause}", list(filters.values()))

    def delete(self):
        execute(f"DELETE FROM {self.table} WHERE id = ?", [self.id])

    def to_dict(self):
        return {c: getattr(self, c) for c in self.columns}


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

class Lecturer(Model):
    table = "lecturers"
    columns = ("id", "name", "email", "password_hash", "google_id", "created_at")


class Course(Model):
    table = "courses"
    columns = ("id", "lecturer_id", "name", "created_at")

    def owned_by(self, lecturer_id):
        return self.lecturer_id == lecturer_id

    @classmethod
    def owned_by_id(cls, course_id, lecturer_id):
        """True if this course exists and belongs to this lecturer."""
        return cls.exists(id=course_id, lecturer_id=lecturer_id)


class Group(Model):
    table = "groups"
    columns = ("id", "course_id", "group_label")

    @classmethod
    def with_students(cls, course_id):
        """
        All groups for a course, each with its students nested in, ordered.
        Includes whether each student has claimed their PIN yet — never the
        PIN itself, since it's self-set and nobody but the student should
        know it. This is what lets the lecturer see who might be locked out.
        """
        rs = execute(
            "SELECT g.id AS group_id, g.group_label, s.id AS student_pk, s.name, s.student_id, s.pin_hash "
            "FROM groups g LEFT JOIN students s ON s.group_id = g.id "
            "WHERE g.course_id = ? ORDER BY g.id, s.name",
            [course_id],
        )
        groups_by_id = {}
        for row in rs.rows:
            r = dict(zip(rs.columns, row))
            g = groups_by_id.setdefault(
                r["group_id"], {"id": r["group_id"], "group_label": r["group_label"], "students": []}
            )
            if r["student_pk"] is not None:
                g["students"].append({
                    "id": r["student_pk"], "name": r["name"], "student_id": r["student_id"],
                    "pin_set": r["pin_hash"] is not None,
                })
        return list(groups_by_id.values())

    @classmethod
    def replace_all(cls, course_id, parsed_groups):
        """Wipe this course's groups/students and re-create them from parsed_groups."""
        for g in cls.where(course_id=course_id):
            Student.delete_where(group_id=g.id)
        cls.delete_where(course_id=course_id)

        created = []
        for g in parsed_groups:
            group = cls.create(course_id=course_id, group_label=g["group_label"])
            students = [
                Student.create(group_id=group.id, name=s["name"], student_id=s["student_id"]).to_dict()
                for s in g["students"]
            ]
            created.append({"id": group.id, "group_label": group.group_label, "students": students})
        return created


class Student(Model):
    table = "students"
    columns = ("id", "group_id", "name", "student_id", "pin_hash")

    def has_pin(self):
        return self.pin_hash is not None

    def claim_pin(self, pin):
        """Set this student's PIN for the first time. Caller must already
        have checked has_pin() is False — this doesn't re-check, so it can
        also be used by the lecturer's reset flow to leave a fresh claim open."""
        self.update(pin_hash=generate_password_hash(pin))

    def check_pin(self, submitted_pin):
        if not self.pin_hash:
            return False
        return check_password_hash(self.pin_hash, (submitted_pin or "").strip())

    def reset_pin(self):
        """Lecturer-triggered: clear the PIN so the student can claim a new one."""
        self.update(pin_hash=None)

    @classmethod
    def find_in_course(cls, course_id, identifier):
        """Match by student_id first (exact), then by name (case-insensitive)."""
        rs = execute(
            "SELECT s.id, s.name, s.student_id, s.group_id, s.pin_hash "
            "FROM students s JOIN groups g ON g.id = s.group_id "
            "WHERE g.course_id = ? AND s.student_id = ?",
            [course_id, identifier],
        )
        if not rs.rows:
            rs = execute(
                "SELECT s.id, s.name, s.student_id, s.group_id, s.pin_hash "
                "FROM students s JOIN groups g ON g.id = s.group_id "
                "WHERE g.course_id = ? AND LOWER(s.name) = LOWER(?)",
                [course_id, identifier],
            )
        return cls._from_row(rs.rows[0], rs.columns) if rs.rows else None

    @classmethod
    def groupmates(cls, group_id, excluding_id):
        return [s for s in cls.where(order_by="name", group_id=group_id) if s.id != excluding_id]


class Evaluation(Model):
    table = "evaluations"
    columns = ("id", "course_id", "title", "status", "created_at")

    def to_full_dict(self):
        d = self.to_dict()
        d["criteria"] = [c.to_dict() for c in EvaluationCriterion.where(order_by="sort_order", evaluation_id=self.id)]
        d["scale"] = [s.to_dict() for s in EvaluationScale.where(order_by="value", evaluation_id=self.id)]
        return d

    def set_criteria_and_scale(self, criteria, scale):
        """Wholesale replace. Caller is responsible for checking there are no submissions yet."""
        EvaluationCriterion.delete_where(evaluation_id=self.id)
        EvaluationScale.delete_where(evaluation_id=self.id)
        for i, name in enumerate(criteria):
            EvaluationCriterion.create(evaluation_id=self.id, name=name.strip(), sort_order=i)
        for point in scale:
            EvaluationScale.create(evaluation_id=self.id, value=point["value"], label=point["label"].strip())

    def completion(self):
        """Every student in the course, grouped, with whether they've submitted."""
        rs = execute(
            "SELECT g.id AS group_id, g.group_label, s.id AS student_pk, s.name, s.student_id, "
            "       CASE WHEN sub.id IS NULL THEN 0 ELSE 1 END AS has_submitted "
            "FROM groups g "
            "JOIN students s ON s.group_id = g.id "
            "LEFT JOIN submissions sub ON sub.evaluator_student_id = s.id AND sub.evaluation_id = ? "
            "WHERE g.course_id = ? ORDER BY g.id, s.name",
            [self.id, self.course_id],
        )
        groups_by_id = {}
        for row in rs.rows:
            r = dict(zip(rs.columns, row))
            g = groups_by_id.setdefault(
                r["group_id"], {"id": r["group_id"], "group_label": r["group_label"], "students": []}
            )
            g["students"].append({
                "id": r["student_pk"], "name": r["name"], "student_id": r["student_id"],
                "has_submitted": bool(r["has_submitted"]),
            })
        return list(groups_by_id.values())

    def results(self):
        """Per-student averages (overall + per criterion) plus the full individual breakdown."""
        criteria = [c.to_dict() for c in EvaluationCriterion.where(order_by="sort_order", evaluation_id=self.id)]

        detail_rs = execute(
            "SELECT ev_s.name AS evaluator_name, ev_s.student_id AS evaluator_student_id, "
            "       rt_s.id AS ratee_id, rt_s.name AS ratee_name, "
            "       ec.name AS criterion, sc.score "
            "FROM submission_scores sc "
            "JOIN submissions sub ON sub.id = sc.submission_id "
            "JOIN students ev_s ON ev_s.id = sub.evaluator_student_id "
            "JOIN students rt_s ON rt_s.id = sc.ratee_student_id "
            "JOIN evaluation_criteria ec ON ec.id = sc.criterion_id "
            "WHERE sub.evaluation_id = ? "
            "ORDER BY rt_s.name, ev_s.name, ec.sort_order",
            [self.id],
        )
        individual_scores = [dict(zip(detail_rs.columns, row)) for row in detail_rs.rows]

        agg_rs = execute(
            "SELECT rt_s.id AS ratee_id, rt_s.name AS ratee_name, ec.id AS criterion_id, "
            "       ec.name AS criterion, AVG(sc.score) AS avg_score, COUNT(sc.score) AS num_ratings "
            "FROM submission_scores sc "
            "JOIN submissions sub ON sub.id = sc.submission_id "
            "JOIN students rt_s ON rt_s.id = sc.ratee_student_id "
            "JOIN evaluation_criteria ec ON ec.id = sc.criterion_id "
            "WHERE sub.evaluation_id = ? "
            "GROUP BY rt_s.id, ec.id "
            "ORDER BY rt_s.name, ec.sort_order",
            [self.id],
        )
        students_agg = {}
        for row in agg_rs.rows:
            r = dict(zip(agg_rs.columns, row))
            student = students_agg.setdefault(
                r["ratee_id"],
                {"student_id": r["ratee_id"], "name": r["ratee_name"], "by_criterion": [], "total": None},
            )
            student["by_criterion"].append({
                "criterion": r["criterion"], "average": round(r["avg_score"], 2), "num_ratings": r["num_ratings"],
            })
        for student in students_agg.values():
            # Total (not average): sum of this student's per-criterion averages,
            # matching the paper form's "TOTAL" row (sum of scores across criteria),
            # not a mean across criteria.
            vals = [c["average"] for c in student["by_criterion"]]
            student["total"] = round(sum(vals), 2) if vals else None

        return {"criteria": criteria, "aggregates": list(students_agg.values()), "individual_scores": individual_scores}


class EvaluationCriterion(Model):
    table = "evaluation_criteria"
    columns = ("id", "evaluation_id", "name", "sort_order")


class EvaluationScale(Model):
    table = "evaluation_scale"
    columns = ("id", "evaluation_id", "value", "label")


class Submission(Model):
    table = "submissions"
    columns = ("id", "evaluation_id", "evaluator_student_id", "submitted_at")


class SubmissionScore(Model):
    table = "submission_scores"
    columns = ("id", "submission_id", "ratee_student_id", "criterion_id", "score")


if __name__ == "__main__":
    from db import close
    init_db()
    close()  # otherwise the libsql background thread keeps a one-off script alive
