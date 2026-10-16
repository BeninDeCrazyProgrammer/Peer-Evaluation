from flask import Blueprint, request, jsonify
from flask_login import login_required

from models import Class
from routes.courses import _assert_owns_course

classes_bp = Blueprint("classes", __name__, url_prefix="/courses/<int:course_id>/classes")


@classes_bp.route("", methods=["POST"])
@login_required
def create_class(course_id):
    """
    Body: {"name": "2026 Level 300"}
    A class is a separate student roster (and separate set of evaluations)
    under one course — for a course taught to more than one year group,
    section, or cohort at once, each gets its own class with its own groups
    upload, so evaluating one never touches another's roster or results.
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Class name is required"}), 400

    if Class.name_taken(course_id, name):
        return jsonify({"error": f"This course already has a class named \"{name}\"."}), 409

    cls = Class.create(course_id=course_id, name=name)
    return jsonify(cls.to_dict()), 201


@classes_bp.route("", methods=["GET"])
@login_required
def list_classes(course_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    classes = Class.where(order_by="created_at DESC", course_id=course_id)
    return jsonify([c.to_dict() for c in classes])


@classes_bp.route("/<int:class_id>", methods=["GET"])
@login_required
def get_class(course_id, class_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    cls = Class.first(id=class_id, course_id=course_id)
    if not cls:
        return jsonify({"error": "Class not found"}), 404
    return jsonify(cls.to_dict())


@classes_bp.route("/<int:class_id>", methods=["DELETE"])
@login_required
def delete_class(course_id, class_id):
    """
    Deletes a class and everything under it — its groups, students, and
    every evaluation (with criteria/scale/submissions/scores) created for
    it. Irreversible; the frontend is expected to confirm before calling
    this.
    """
    cls = Class.first(id=class_id, course_id=course_id)
    if not cls:
        return jsonify({"error": "Class not found"}), 404
    cls.delete_cascade()
    return jsonify({"message": "Class deleted"}), 200
