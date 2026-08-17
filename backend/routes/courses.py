from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from models import Course

courses_bp = Blueprint("courses", __name__, url_prefix="/courses")


@courses_bp.route("", methods=["POST"])
@login_required
def create_course():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Course name is required"}), 400

    # Catches both an accidental double-click on Create (nothing previously
    # stopped the button from firing twice while the first request was still
    # in flight) and a genuine retry — either way, the lecturer almost never
    # wants two identically-named courses of their own sitting side by side.
    if Course.name_taken(current_user.id, name):
        return jsonify({"error": f"You already have a course named \"{name}\". "
                                  f"Open the existing one, or use a different name for a new one."}), 409

    course = Course.create(lecturer_id=current_user.id, name=name)
    return jsonify(course.to_dict()), 201


@courses_bp.route("", methods=["GET"])
@login_required
def list_courses():
    courses = Course.where(order_by="created_at DESC", lecturer_id=current_user.id)
    return jsonify([c.to_dict() for c in courses])


def _assert_owns_course(course_id):
    """True if this course belongs to the logged-in lecturer."""
    return Course.owned_by_id(course_id, current_user.id)


@courses_bp.route("/<int:course_id>", methods=["GET"])
@login_required
def get_course(course_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    return jsonify(Course.find(course_id).to_dict())


@courses_bp.route("/<int:course_id>", methods=["DELETE"])
@login_required
def delete_course(course_id):
    """
    Deletes a course and everything under it (groups, students, evaluations,
    and every submission/score ever recorded for them) — irreversible. The
    frontend is expected to get explicit confirmation before calling this;
    there's no undo or soft-delete here.
    """
    course = Course.find(course_id)
    if not course or not course.owned_by(current_user.id):
        return jsonify({"error": "Course not found"}), 404

    course.delete_cascade()
    return jsonify({"message": "Course deleted"}), 200
