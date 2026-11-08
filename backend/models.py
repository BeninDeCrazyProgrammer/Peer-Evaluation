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
import hashlib
import secrets
from collections import defaultdict
from statistics import mean, median
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from db import execute, batch, batch_execute


# --------------------------------------------------------------------------
# Anomaly-detection thresholds (all relative to the evaluation's own scale, so
# they work for a 0-3 scale and a 1-10 scale alike). "span" below means the
# largest possible total one evaluator can give one person:
#     (highest scale value - lowest scale value) x number of criteria
# --------------------------------------------------------------------------
MIN_SCORES_FOR_UNIFORM = 4     # fewer ratings than this can match by pure chance
OUTLIER_GAP = 0.35             # a rating this far (x span) from the others' median is an outlier...
CONSENSUS_SPREAD = 0.25        # ...but only if the others roughly agree (their own spread <= this x span)
SINGLED_OUT_GAP = 0.25         # ...and the evaluator rated everyone else this much differently (x span)


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
    CREATE TABLE IF NOT EXISTS classes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id   INTEGER NOT NULL REFERENCES courses(id),
        name        TEXT NOT NULL,          -- e.g. "2026 Level 300", "Evening Section"
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS groups (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id   INTEGER NOT NULL REFERENCES courses(id),
        class_id    INTEGER REFERENCES classes(id),  -- NULL only on rows a pre-classes DB migrated into a "Default Class" — see _migrate_classes
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
        class_id    INTEGER REFERENCES classes(id),  -- NULL only on rows a pre-classes DB migrated into a "Default Class" — see _migrate_classes
        title       TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'closed'
        deadline    TEXT,                            -- ISO 8601 UTC; NULL = no auto-close
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
    """
    CREATE TABLE IF NOT EXISTS course_members (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id   INTEGER NOT NULL REFERENCES courses(id),
        lecturer_id INTEGER NOT NULL REFERENCES lecturers(id),
        role        TEXT NOT NULL DEFAULT 'ta',      -- the course's owner is courses.lecturer_id, not a row here
        added_at    TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(course_id, lecturer_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS course_invites (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id   INTEGER NOT NULL REFERENCES courses(id),
        email       TEXT NOT NULL,                   -- stored lower-cased; the invite only works for this address
        token_hash  TEXT NOT NULL UNIQUE,            -- SHA-256 of the secret token; the token itself is never stored
        invited_by  INTEGER NOT NULL REFERENCES lecturers(id),
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at  TEXT NOT NULL,
        accepted_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_members_course ON course_members(course_id)",
    "CREATE INDEX IF NOT EXISTS idx_members_lecturer ON course_members(lecturer_id)",
    "CREATE INDEX IF NOT EXISTS idx_invites_course ON course_invites(course_id)",
    "CREATE INDEX IF NOT EXISTS idx_classes_course ON classes(course_id)",
    "CREATE INDEX IF NOT EXISTS idx_groups_course ON groups(course_id)",
    "CREATE INDEX IF NOT EXISTS idx_students_group ON students(group_id)",
    "CREATE INDEX IF NOT EXISTS idx_evaluations_course ON evaluations(course_id)",
    "CREATE INDEX IF NOT EXISTS idx_submissions_eval ON submissions(evaluation_id)",
    "CREATE INDEX IF NOT EXISTS idx_scores_submission ON submission_scores(submission_id)",
    "CREATE INDEX IF NOT EXISTS idx_scores_ratee ON submission_scores(ratee_student_id)",
    """
    CREATE TABLE IF NOT EXISTS rate_limits (
        bucket       TEXT PRIMARY KEY,
        window_start INTEGER NOT NULL,
        count        INTEGER NOT NULL
    )
    """,
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


def _migrate_evaluation_deadline():
    """One-time migration for databases created before deadlines existed."""
    cols = [row[1] for row in execute("PRAGMA table_info(evaluations)").rows]
    if "deadline" not in cols:
        execute("ALTER TABLE evaluations ADD COLUMN deadline TEXT")


def _migrate_classes():
    """
    One-time migration for databases created before classes existed.

    Adds class_id to groups and evaluations (nullable at the DB level —
    SQLite's ALTER TABLE ADD COLUMN can't add a NOT NULL column without a
    default that would be wrong for every future row; the not-null
    invariant for *new* rows is enforced at the application layer instead,
    same as elsewhere in this file).

    Then backfills: any course whose groups or evaluations predate this
    migration (class_id IS NULL) gets one auto-created "Default Class"
    holding everything that already existed for that course, so existing
    rosters, evaluations, and all their submissions keep working exactly as
    before — nobody's data silently vanishes behind a class they don't know
    exists. New courses get no such default; the lecturer picks or creates
    a class explicitly from here on.
    """
    group_cols = [row[1] for row in execute("PRAGMA table_info(groups)").rows]
    if "class_id" not in group_cols:
        execute("ALTER TABLE groups ADD COLUMN class_id INTEGER REFERENCES classes(id)")

    eval_cols = [row[1] for row in execute("PRAGMA table_info(evaluations)").rows]
    if "class_id" not in eval_cols:
        execute("ALTER TABLE evaluations ADD COLUMN class_id INTEGER REFERENCES classes(id)")

    # These reference class_id, so they can only run after the ALTERs above
    # (on a fresh DB, class_id is already in the CREATE TABLE, so these are
    # just as valid there too) — that's why they live here rather than in
    # the static SCHEMA list, which runs before this migration on old DBs.
    execute("CREATE INDEX IF NOT EXISTS idx_groups_class ON groups(class_id)")
    execute("CREATE INDEX IF NOT EXISTS idx_evaluations_class ON evaluations(class_id)")

    orphan_course_ids = {row[0] for row in execute("SELECT DISTINCT course_id FROM groups WHERE class_id IS NULL").rows}
    orphan_course_ids |= {row[0] for row in execute("SELECT DISTINCT course_id FROM evaluations WHERE class_id IS NULL").rows}

    for course_id in orphan_course_ids:
        default_class = Class.create(course_id=course_id, name="Default Class")
        execute("UPDATE groups SET class_id = ? WHERE course_id = ? AND class_id IS NULL", [default_class.id, course_id])
        execute("UPDATE evaluations SET class_id = ? WHERE course_id = ? AND class_id IS NULL", [default_class.id, course_id])


def init_db():
    batch(SCHEMA)
    _migrate_student_pins()
    _migrate_evaluation_deadline()
    _migrate_classes()
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

    @classmethod
    def find_by_email(cls, email):
        """Case-insensitive email lookup (plain first(email=...) is case-sensitive in SQLite)."""
        rs = execute("SELECT * FROM lecturers WHERE LOWER(email) = LOWER(?) LIMIT 1", [(email or "").strip()])
        return cls._from_row(rs.rows[0], rs.columns) if rs.rows else None


class CourseMember(Model):
    """A TA (or other non-owner) who can work in someone else's course."""
    table = "course_members"
    columns = ("id", "course_id", "lecturer_id", "role", "added_at")

    @classmethod
    def with_lecturers(cls, course_id):
        rs = execute(
            "SELECT m.lecturer_id, m.role, m.added_at, l.name, l.email "
            "FROM course_members m JOIN lecturers l ON l.id = m.lecturer_id "
            "WHERE m.course_id = ? ORDER BY l.name",
            [course_id],
        )
        return [dict(zip(rs.columns, row)) for row in rs.rows]


INVITE_TTL_DAYS = 7


def _hash_token(token):
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


class CourseInvite(Model):
    """
    A pending invitation for someone who doesn't have an account yet. The app
    has no email-sending infrastructure, so the owner copies the generated link
    and shares it themselves. Only a hash of the token is stored, the link is
    shown once, and it only works for the invited email address, so a leaked
    link is useless to anyone signed in as somebody else.
    """
    table = "course_invites"
    columns = ("id", "course_id", "email", "token_hash", "invited_by", "created_at", "expires_at", "accepted_at")

    @classmethod
    def issue(cls, course_id, email, invited_by):
        """Create (replacing any earlier pending invite for that email) and return (invite, raw_token)."""
        email = email.strip().lower()
        execute("DELETE FROM course_invites WHERE course_id = ? AND email = ? AND accepted_at IS NULL", [course_id, email])
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        invite = cls.create(course_id=course_id, email=email, token_hash=_hash_token(token),
                            invited_by=invited_by, expires_at=expires)
        return invite, token

    @classmethod
    def find_valid(cls, token, email=None):
        """The pending, unexpired invite for this token (and email, if given), or None."""
        if not token:
            return None
        invite = cls.first(token_hash=_hash_token(token))
        if not invite or invite.accepted_at:
            return None
        try:
            expires = datetime.fromisoformat(invite.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if datetime.now(timezone.utc) >= expires:
            return None
        if email is not None and invite.email != (email or "").strip().lower():
            return None
        return invite

    @classmethod
    def pending_for_course(cls, course_id):
        rs = execute(
            "SELECT id, email, created_at, expires_at FROM course_invites "
            "WHERE course_id = ? AND accepted_at IS NULL AND expires_at > ? ORDER BY created_at DESC",
            [course_id, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")],
        )
        return [dict(zip(rs.columns, row)) for row in rs.rows]


class Course(Model):
    table = "courses"
    columns = ("id", "lecturer_id", "name", "created_at")

    def owned_by(self, lecturer_id):
        return self.lecturer_id == lecturer_id

    @classmethod
    def owned_by_id(cls, course_id, lecturer_id):
        """True if this course exists and belongs to this lecturer."""
        return cls.exists(id=course_id, lecturer_id=lecturer_id)

    @classmethod
    def role_for(cls, course_id, lecturer_id):
        """'owner', 'ta', or None if this lecturer has no access to the course."""
        if cls.owned_by_id(course_id, lecturer_id):
            return "owner"
        member = CourseMember.first(course_id=course_id, lecturer_id=lecturer_id)
        return member.role if member else None

    @classmethod
    def for_lecturer(cls, lecturer_id):
        """Every course this lecturer owns OR has been added to as a TA, newest first, with their role."""
        rs = execute(
            "SELECT * FROM ("
            "  SELECT c.id AS id, c.lecturer_id AS lecturer_id, c.name AS name, c.created_at AS created_at, "
            "         'owner' AS role, l.name AS owner_name "
            "  FROM courses c JOIN lecturers l ON l.id = c.lecturer_id WHERE c.lecturer_id = ? "
            "  UNION ALL "
            "  SELECT c.id, c.lecturer_id, c.name, c.created_at, m.role, l.name "
            "  FROM course_members m JOIN courses c ON c.id = m.course_id "
            "  JOIN lecturers l ON l.id = c.lecturer_id WHERE m.lecturer_id = ?"
            ") ORDER BY created_at DESC",
            [lecturer_id, lecturer_id],
        )
        return [dict(zip(rs.columns, row)) for row in rs.rows]

    @classmethod
    def name_taken(cls, lecturer_id, name):
        """
        Case/whitespace-insensitive duplicate check within one lecturer's own
        courses. Doesn't block the same name across different lecturers —
        two people teaching different sections of "BME 208" is normal; the
        same lecturer creating "BME 208" six times over (e.g. from a
        double-clicked create button before this had a duplicate check) isn't.
        """
        rs = execute(
            "SELECT 1 FROM courses WHERE lecturer_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) LIMIT 1",
            [lecturer_id, name],
        )
        return len(rs.rows) > 0

    def delete_cascade(self):
        """
        Deletes this course and everything under it: classes, groups,
        students, evaluations, criteria, scale, submissions, and submission
        scores. There's no ON DELETE CASCADE on these foreign keys (see the
        CREATE TABLE statements above), so this deletes bottom-up by hand —
        deepest dependents first — as one atomic batch. Irreversible; the
        caller (the route) is responsible for getting explicit confirmation
        before calling this.
        """
        cid = self.id
        statements = [
            (
                "DELETE FROM submission_scores WHERE submission_id IN ("
                "  SELECT sub.id FROM submissions sub"
                "  JOIN evaluations e ON e.id = sub.evaluation_id"
                "  WHERE e.course_id = ?"
                ")",
                [cid],
            ),
            (
                "DELETE FROM submissions WHERE evaluation_id IN ("
                "  SELECT id FROM evaluations WHERE course_id = ?"
                ")",
                [cid],
            ),
            (
                "DELETE FROM evaluation_scale WHERE evaluation_id IN ("
                "  SELECT id FROM evaluations WHERE course_id = ?"
                ")",
                [cid],
            ),
            (
                "DELETE FROM evaluation_criteria WHERE evaluation_id IN ("
                "  SELECT id FROM evaluations WHERE course_id = ?"
                ")",
                [cid],
            ),
            ("DELETE FROM evaluations WHERE course_id = ?", [cid]),
            (
                "DELETE FROM students WHERE group_id IN ("
                "  SELECT id FROM groups WHERE course_id = ?"
                ")",
                [cid],
            ),
            ("DELETE FROM groups WHERE course_id = ?", [cid]),
            ("DELETE FROM classes WHERE course_id = ?", [cid]),
            ("DELETE FROM course_members WHERE course_id = ?", [cid]),
            ("DELETE FROM course_invites WHERE course_id = ?", [cid]),
            ("DELETE FROM courses WHERE id = ?", [cid]),
        ]
        batch_execute(statements)


class Class(Model):
    """
    A class is one student roster (and one set of evaluations) under a
    course — the layer this app was missing when a course was assumed to
    have exactly one cohort. A course taught to more than one year
    group/section/semester at once gets one Class per cohort, each with its
    own groups upload and its own evaluations; nothing about one class's
    roster or results touches another's.
    """
    table = "classes"
    columns = ("id", "course_id", "name", "created_at")

    @classmethod
    def name_taken(cls, course_id, name):
        """Case/whitespace-insensitive duplicate check within one course's own classes."""
        rs = execute(
            "SELECT 1 FROM classes WHERE course_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) LIMIT 1",
            [course_id, name],
        )
        return len(rs.rows) > 0

    def has_submissions(self):
        """
        True if any evaluation under this class has at least one submission.
        Used to block operations — specifically re-uploading the roster —
        that would otherwise silently corrupt real student data: see
        Group.replace_all's docstring for exactly what goes wrong if a
        roster with existing submissions gets wiped and recreated.
        """
        rs = execute(
            "SELECT 1 FROM submissions sub "
            "JOIN evaluations e ON e.id = sub.evaluation_id "
            "WHERE e.class_id = ? LIMIT 1",
            [self.id],
        )
        return len(rs.rows) > 0

    def delete_cascade(self):
        """
        Deletes this class and everything under it: groups, students, and
        every evaluation (with its criteria/scale/submissions/scores)
        created for it. Same bottom-up atomic-batch approach as
        Course.delete_cascade, just scoped to one class instead of the
        whole course.
        """
        clsid = self.id
        statements = [
            (
                "DELETE FROM submission_scores WHERE submission_id IN ("
                "  SELECT sub.id FROM submissions sub"
                "  JOIN evaluations e ON e.id = sub.evaluation_id"
                "  WHERE e.class_id = ?"
                ")",
                [clsid],
            ),
            (
                "DELETE FROM submissions WHERE evaluation_id IN ("
                "  SELECT id FROM evaluations WHERE class_id = ?"
                ")",
                [clsid],
            ),
            (
                "DELETE FROM evaluation_scale WHERE evaluation_id IN ("
                "  SELECT id FROM evaluations WHERE class_id = ?"
                ")",
                [clsid],
            ),
            (
                "DELETE FROM evaluation_criteria WHERE evaluation_id IN ("
                "  SELECT id FROM evaluations WHERE class_id = ?"
                ")",
                [clsid],
            ),
            ("DELETE FROM evaluations WHERE class_id = ?", [clsid]),
            (
                "DELETE FROM students WHERE group_id IN ("
                "  SELECT id FROM groups WHERE class_id = ?"
                ")",
                [clsid],
            ),
            ("DELETE FROM groups WHERE class_id = ?", [clsid]),
            ("DELETE FROM classes WHERE id = ?", [clsid]),
        ]
        batch_execute(statements)


class Group(Model):
    table = "groups"
    columns = ("id", "course_id", "class_id", "group_label")

    @classmethod
    def with_students(cls, class_id):
        """
        All groups for a class, each with its students nested in, ordered.
        Includes whether each student has claimed their PIN yet — never the
        PIN itself, since it's self-set and nobody but the student should
        know it. This is what lets the lecturer see who might be locked out.
        """
        rs = execute(
            "SELECT g.id AS group_id, g.group_label, s.id AS student_pk, s.name, s.student_id, s.pin_hash "
            "FROM groups g LEFT JOIN students s ON s.group_id = g.id "
            "WHERE g.class_id = ? ORDER BY g.id, s.name",
            [class_id],
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
    def replace_all(cls, class_id, course_id, parsed_groups):
        """
        Atomically wipe THIS CLASS's groups/students and re-create them from
        parsed_groups, as a single batch — either the whole roster replaces
        cleanly or nothing changes.

        Callers MUST check Class.has_submissions() first and refuse to call
        this if it's True. This function deletes every existing student row
        in the class and creates brand-new rows with brand-new ids — it has
        no way to know "this new row is really the same person as that old
        row", so if any submission already references an old student id (as
        evaluator or ratee), that submission silently orphans: it vanishes
        from completion()/results()/exports (which all JOIN through
        students), and the real person now looks like they've never
        submitted, free to submit again under their new id. This is a full
        replace, not a merge, by design — merging safely (matching by
        student_id, preserving history) is a larger feature this doesn't
        attempt.

        Scoped to class_id, not course_id — a course can have several
        classes (year groups/sections) now, each with its own independent
        roster, so re-uploading a sheet for one class must never touch
        another class's groups even though they share a course. course_id
        is still stored on each new group (denormalized) purely so existing
        course-wide queries don't need a join through classes.

        Student rows are linked to their group via a correlated subquery
        ("the most recently created group in this class") rather than
        last_insert_rowid() — last_insert_rowid() tracks the single most
        recent insert of ANY kind on the connection, so it drifts to the
        wrong value after the first student of a group (it would end up
        pointing at the previous student's row, not the group's). The
        subquery stays correct across a whole group's students because
        inserting a student never creates a new row in groups.
        """
        statements = [
            ("DELETE FROM students WHERE group_id IN (SELECT id FROM groups WHERE class_id = ?)", [class_id]),
            ("DELETE FROM groups WHERE class_id = ?", [class_id]),
        ]
        for g in parsed_groups:
            statements.append((
                "INSERT INTO groups (course_id, class_id, group_label) VALUES (?, ?, ?)",
                [course_id, class_id, g["group_label"]],
            ))
            for s in g["students"]:
                statements.append((
                    "INSERT INTO students (group_id, name, student_id) "
                    "VALUES ((SELECT id FROM groups WHERE class_id = ? ORDER BY id DESC LIMIT 1), ?, ?)",
                    [class_id, s["name"], s["student_id"]],
                ))
        batch_execute(statements)
        return cls.with_students(class_id)


class AmbiguousStudentError(Exception):
    """
    Raised by Student.find_in_class when an identifier matches more than one
    student in the class, instead of silently picking whichever row came
    back first. Two different causes need two different responses:
      - A student_id collision means the roster itself has a data error
        (student IDs are only enforced unique per group, not per class —
        see the UNIQUE(group_id, student_id) constraint above), and picking
        a match silently could let one student log in as another.
      - A name collision is an expected, harmless case (two students happen
        to share a name); the fix is just telling that student to use their
        ID instead of their name.
    self.identifier is preserved so callers can tell the two apart if needed.
    """
    def __init__(self, identifier):
        self.identifier = identifier
        super().__init__(f"'{identifier}' matches more than one student in this class")


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
    def find_in_class(cls, class_id, identifier):
        """
        Match by student_id first (exact), then by name (case-insensitive) as
        a fallback for students who don't have their ID handy. Scoped to one
        class's roster, not the whole course — a course can have several
        classes (year groups/sections) now, each with its own independent
        roster, so a name or ID collision in a *different* class of the same
        course isn't this lookup's problem and shouldn't be reported as
        ambiguous. Raises AmbiguousStudentError rather than returning an
        arbitrary match if more than one student in *this* class matches
        either lookup — see that class's docstring for why silently picking
        one is unsafe.
        """
        rs = execute(
            "SELECT s.id, s.name, s.student_id, s.group_id, s.pin_hash "
            "FROM students s JOIN groups g ON g.id = s.group_id "
            "WHERE g.class_id = ? AND s.student_id = ?",
            [class_id, identifier],
        )
        if not rs.rows:
            rs = execute(
                "SELECT s.id, s.name, s.student_id, s.group_id, s.pin_hash "
                "FROM students s JOIN groups g ON g.id = s.group_id "
                "WHERE g.class_id = ? AND LOWER(s.name) = LOWER(?)",
                [class_id, identifier],
            )
        if len(rs.rows) > 1:
            raise AmbiguousStudentError(identifier)
        return cls._from_row(rs.rows[0], rs.columns) if rs.rows else None

    @classmethod
    def groupmates(cls, group_id, excluding_id):
        return [s for s in cls.where(order_by="name", group_id=group_id) if s.id != excluding_id]


class Evaluation(Model):
    table = "evaluations"
    columns = ("id", "course_id", "class_id", "title", "status", "deadline", "created_at")

    def delete_cascade(self):
        """
        Deletes this evaluation and everything hanging off it: submission
        scores, submissions, scale and criteria. No ON DELETE CASCADE exists
        on these foreign keys, so this goes bottom-up as one atomic batch.
        Roster (groups/students) is untouched. Irreversible — the route
        decides whether the caller is allowed to do this.
        """
        eid = self.id
        batch_execute([
            (
                "DELETE FROM submission_scores WHERE submission_id IN ("
                "  SELECT id FROM submissions WHERE evaluation_id = ?"
                ")",
                [eid],
            ),
            ("DELETE FROM submissions WHERE evaluation_id = ?", [eid]),
            ("DELETE FROM evaluation_scale WHERE evaluation_id = ?", [eid]),
            ("DELETE FROM evaluation_criteria WHERE evaluation_id = ?", [eid]),
            ("DELETE FROM evaluations WHERE id = ?", [eid]),
        ])

    def check_and_close(self):
        """
        If a deadline is set and has passed while status is still 'open',
        persist the close right now. Called from to_dict()/to_full_dict(), so
        every read path (lecturer's list, the public student-facing fetch)
        auto-flips a stale "open" status without needing a background job —
        the next person to look at it is what triggers the update.
        """
        if self.status == "open" and self.deadline:
            try:
                deadline_dt = datetime.fromisoformat(self.deadline.replace("Z", "+00:00"))
            except ValueError:
                return  # malformed deadline shouldn't crash a read — just skip auto-close
            if datetime.now(timezone.utc) >= deadline_dt:
                self.update(status="closed")

    def to_dict(self):
        self.check_and_close()
        return super().to_dict()

    def to_full_dict(self):
        d = self.to_dict()  # already calls check_and_close() — no need to call it again here
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
        """
        Every student in this evaluation's CLASS, grouped, with whether
        they've submitted. Scoped to class_id, not course_id — a course can
        have several classes (year groups/sections) now sharing it, so
        scoping by course here would pull in every student from every other
        class too, not just the roster this evaluation was actually created
        for.
        """
        rs = execute(
            "SELECT g.id AS group_id, g.group_label, s.id AS student_pk, s.name, s.student_id, "
            "       CASE WHEN sub.id IS NULL THEN 0 ELSE 1 END AS has_submitted "
            "FROM groups g "
            "JOIN students s ON s.group_id = g.id "
            "LEFT JOIN submissions sub ON sub.evaluator_student_id = s.id AND sub.evaluation_id = ? "
            "WHERE g.class_id = ? ORDER BY g.id, s.name",
            [self.id, self.class_id],
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

    def participation(self, completion=None, criteria_count=None):
        """
        Automatic participation grade for every student on the roster, keyed
        by student id: how much of the peer evaluation they actually attempted.

            full     -> 100%  rated every teammate on every criterion
            partial  -> the share of the required ratings they completed
            none     ->   0%  nothing submitted
            n/a      ->  (sole member of a group: nobody to rate)

        Today the student form only accepts a complete submission, so in
        practice a student lands on full or none; the partial branch is what
        makes this correct if that rule is ever relaxed (or data is imported).
        """
        completion = completion if completion is not None else self.completion()
        if criteria_count is None:
            criteria_count = len(EvaluationCriterion.where(evaluation_id=self.id))
        rs = execute(
            "SELECT sub.evaluator_student_id AS evaluator_id, COUNT(*) AS n "
            "FROM submission_scores sc JOIN submissions sub ON sub.id = sc.submission_id "
            "WHERE sub.evaluation_id = ? GROUP BY sub.evaluator_student_id",
            [self.id],
        )
        given_by = {row[0]: row[1] for row in rs.rows}

        out = {}
        for g in completion:
            expected = (len(g["students"]) - 1) * criteria_count
            for st in g["students"]:
                given = given_by.get(st["id"], 0)
                if expected <= 0:
                    out[st["id"]] = {"given": given, "expected": 0, "percent": None, "status": "n/a"}
                    continue
                fraction = min(given / expected, 1.0)
                status = "full" if fraction >= 1 else ("partial" if fraction > 0 else "none")
                out[st["id"]] = {
                    "given": given, "expected": expected,
                    "percent": round(fraction * 100), "status": status,
                }
        return out

    def anomalies(self, individual_scores, completion, scale_values, criteria_count):
        """
        Flags scoring patterns a lecturer should look at. These are prompts to
        review, never verdicts: a flag changes nobody's score.

          same_score_everyone  one evaluator gave literally every rating the same value
          uniform_totals       (milder) criteria differ, but every teammate got the same total
          low_outlier          one evaluator scored a person far below what the rest of the
                               group agreed on, while rating everyone else normally
          high_outlier         the mirror image: far above a consensus (possible favouritism)

        Outlier checks need at least two OTHER evaluators of the same person
        to establish a consensus, so groups smaller than 4 can only receive the
        two "same score" flags.
        """
        span = (max(scale_values) - min(scale_values)) * criteria_count if scale_values else 0
        top = max(scale_values) * criteria_count if scale_values else 0
        info = {st["id"]: (st["name"], g["group_label"]) for g in completion for st in g["students"]}

        raw_by_ev = defaultdict(list)           # evaluator -> every individual rating
        totals = defaultdict(lambda: defaultdict(float))   # evaluator -> ratee -> total across criteria
        for row in individual_scores:
            raw_by_ev[row["evaluator_id"]].append(row["score"])
            totals[row["evaluator_id"]][row["ratee_id"]] += row["score"]

        def fmt(x):
            return f"{x:g}"

        flags = []

        for ev, scores in raw_by_ev.items():
            peers = totals[ev]
            name, group = info.get(ev, ("?", None))
            if len(peers) >= 2 and len(scores) >= MIN_SCORES_FOR_UNIFORM and len(set(scores)) == 1:
                flags.append({
                    "type": "same_score_everyone", "severity": "medium", "group_label": group,
                    "evaluator_id": ev, "evaluator_name": name, "ratee_id": None, "ratee_name": None,
                    "message": f"{name} gave every rating the same value ({fmt(scores[0])}) — "
                               f"{len(scores)} ratings across {len(peers)} teammates, no differentiation at all.",
                })
            elif len(peers) >= 3 and len(set(peers.values())) == 1:
                flags.append({
                    "type": "uniform_totals", "severity": "low", "group_label": group,
                    "evaluator_id": ev, "evaluator_name": name, "ratee_id": None, "ratee_name": None,
                    "message": f"{name} gave all {len(peers)} teammates the same total ({fmt(next(iter(peers.values())))}), "
                               f"even though individual criteria varied.",
                })

        by_ratee = defaultdict(dict)            # ratee -> evaluator -> total
        for ev, per_ratee in totals.items():
            for rt, tot in per_ratee.items():
                by_ratee[rt][ev] = tot

        if span > 0:
            for rt, d in by_ratee.items():
                if len(d) < 3:
                    continue
                for ev, tot in d.items():
                    others = [t for e, t in d.items() if e != ev]
                    if max(others) - min(others) > CONSENSUS_SPREAD * span:
                        continue            # the group itself disagrees; no consensus to deviate from
                    med = median(others)
                    rest = [t for r, t in totals[ev].items() if r != rt]
                    if not rest:
                        continue
                    ev_mean = mean(rest)
                    ev_name, group = info.get(ev, ("?", None))
                    rt_name = info.get(rt, ("?", None))[0]
                    common = {
                        "group_label": group, "evaluator_id": ev, "evaluator_name": ev_name,
                        "ratee_id": rt, "ratee_name": rt_name,
                        "given_total": tot, "others_median": med,
                    }
                    range_txt = fmt(min(others)) if min(others) == max(others) else f"{fmt(min(others))}–{fmt(max(others))}"
                    others_txt = f"the other {len(others)} teammates gave {range_txt} (median {fmt(med)})"
                    if med - tot >= OUTLIER_GAP * span and ev_mean - tot >= SINGLED_OUT_GAP * span:
                        flags.append({**common, "type": "low_outlier", "severity": "high",
                            "message": f"{ev_name} gave {rt_name} {fmt(tot)} out of {fmt(top)}, but {others_txt}. "
                                       f"{ev_name} rated the rest of the group {fmt(round(ev_mean, 1))} on average, so {rt_name} was singled out."})
                    elif tot - med >= OUTLIER_GAP * span and tot - ev_mean >= SINGLED_OUT_GAP * span:
                        flags.append({**common, "type": "high_outlier", "severity": "medium",
                            "message": f"{ev_name} gave {rt_name} {fmt(tot)} out of {fmt(top)}, but {others_txt}. "
                                       f"{ev_name} rated the rest of the group {fmt(round(ev_mean, 1))} on average, so {rt_name} was singled out."})

        order = {"high": 0, "medium": 1, "low": 2}
        flags.sort(key=lambda f: (order[f["severity"]], f["group_label"] or "", f["evaluator_name"]))
        return flags

    def results(self):
        """Per-student averages (overall + per criterion) plus the full individual breakdown."""
        criteria = [c.to_dict() for c in EvaluationCriterion.where(order_by="sort_order", evaluation_id=self.id)]

        detail_rs = execute(
            "SELECT ev_s.id AS evaluator_id, ev_s.name AS evaluator_name, ev_s.student_id AS evaluator_student_id, "
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
            "SELECT rt_s.id AS ratee_id, rt_s.name AS ratee_name, g.group_label AS group_label, "
            "       ec.id AS criterion_id, ec.name AS criterion, AVG(sc.score) AS avg_score, COUNT(sc.score) AS num_ratings "
            "FROM submission_scores sc "
            "JOIN submissions sub ON sub.id = sc.submission_id "
            "JOIN students rt_s ON rt_s.id = sc.ratee_student_id "
            "JOIN groups g ON g.id = rt_s.group_id "
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
                {
                    "student_id": r["ratee_id"], "name": r["ratee_name"], "group_label": r["group_label"],
                    "by_criterion": [], "total": None,
                },
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

        completion = self.completion()
        scale_values = [sc.value for sc in EvaluationScale.where(evaluation_id=self.id)]
        return {
            "criteria": criteria,
            "aggregates": list(students_agg.values()),
            "individual_scores": individual_scores,
            "participation": self.participation(completion, len(criteria)),
            "anomalies": self.anomalies(individual_scores, completion, scale_values, len(criteria)),
        }


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