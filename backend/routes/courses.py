from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from db import execute

courses_bp = Blueprint("courses", __name__, url_prefix="/courses")


@courses_bp.route("", methods=["POST"])
@login_required
def create_course():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Course name is required"}), 400

    rs = execute(
        "INSERT INTO courses (lecturer_id, name) VALUES (?, ?) RETURNING id",
        [current_user.id, name],
    )
    course_id = rs.rows[0][0]
    return jsonify({"id": course_id, "name": name}), 201


@courses_bp.route("", methods=["GET"])
@login_required
def list_courses():
    rs = execute(
        "SELECT id, name, created_at FROM courses WHERE lecturer_id = ? ORDER BY created_at DESC",
        [current_user.id],
    )
    courses = [dict(zip(rs.columns, row)) for row in rs.rows]
    return jsonify(courses)


def _assert_owns_course(course_id):
    """Raises a 404-worthy None if this course doesn't belong to the logged-in lecturer."""
    rs = execute(
        "SELECT id FROM courses WHERE id = ? AND lecturer_id = ?",
        [course_id, current_user.id],
    )
    return bool(rs.rows)


@courses_bp.route("/<int:course_id>", methods=["GET"])
@login_required
def get_course(course_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    rs = execute("SELECT id, name, created_at FROM courses WHERE id = ?", [course_id])
    return jsonify(dict(zip(rs.columns, rs.rows[0])))
