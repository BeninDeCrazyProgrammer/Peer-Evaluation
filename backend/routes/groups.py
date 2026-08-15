from flask import Blueprint, request, jsonify
from flask_login import login_required

from models import Group
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
        parsed_groups, warnings = parse_groups_excel(request.files["file"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Re-uploading replaces the current group list for this course — simplest
    # correct behaviour for "lecturer re-uploads a corrected sheet".
    created_groups = Group.replace_all(course_id, parsed_groups)

    return jsonify({"groups": created_groups, "warnings": warnings}), 201


@groups_bp.route("", methods=["GET"])
@login_required
def list_groups(course_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    return jsonify(Group.with_students(course_id))
