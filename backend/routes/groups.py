from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from db import execute
from routes.courses import _assert_owns_course
from utils.excel_parser import parse_groups_excel

groups_bp = Blueprint("groups", __name__, url_prefix="/courses/<int:course_id>/groups")


@groups_bp.route("/upload", methods=["POST"])
@login_required
def upload_groups(course_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded — send it as multipart/form-data under 'file'"}), 400

    try:
        groups, warnings = parse_groups_excel(request.files["file"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Wipe any existing groups/students for this course before re-importing.
    # (Simplest correct behaviour for "lecturer re-uploads a corrected sheet".)
    existing = execute("SELECT id FROM groups WHERE course_id = ?", [course_id])
    for row in existing.rows:
        group_id = row[0]
        execute("DELETE FROM students WHERE group_id = ?", [group_id])
    execute("DELETE FROM groups WHERE course_id = ?", [course_id])

    created_groups = []
    for g in groups:
        rs = execute(
            "INSERT INTO groups (course_id, group_label) VALUES (?, ?) RETURNING id",
            [course_id, g["group_label"]],
        )
        group_id = rs.rows[0][0]
        for s in g["students"]:
            execute(
                "INSERT INTO students (group_id, name, student_id) VALUES (?, ?, ?)",
                [group_id, s["name"], s["student_id"]],
            )
        created_groups.append({"id": group_id, "group_label": g["group_label"], "students": g["students"]})

    return jsonify({"groups": created_groups, "warnings": warnings}), 201


@groups_bp.route("", methods=["GET"])
@login_required
def list_groups(course_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    rs = execute(
        "SELECT g.id AS group_id, g.group_label, s.id AS student_pk, s.name, s.student_id "
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
            g["students"].append({"id": r["student_pk"], "name": r["name"], "student_id": r["student_id"]})

    return jsonify(list(groups_by_id.values()))
