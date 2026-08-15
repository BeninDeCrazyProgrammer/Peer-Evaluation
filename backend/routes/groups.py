from flask import Blueprint, request, jsonify
from flask_login import login_required

from models import Group, Student
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

    upload = request.files["file"]
    filename = (upload.filename or "").lower()
    if not filename.endswith((".xlsx", ".xls")):
        return jsonify({"error": "Please upload an Excel file (.xlsx or .xls)"}), 400

    try:
        parsed_groups, warnings = parse_groups_excel(upload)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        # Anything else here is almost always a corrupt/mislabeled file
        # (e.g. a .csv renamed to .xlsx) rather than a real server bug —
        # worth a clean 400 instead of falling through to a generic 500.
        return jsonify({"error": "Couldn't read that file. Make sure it's a valid, unmodified .xlsx/.xls export."}), 400

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


@groups_bp.route("/students/<int:student_id>/reset-pin", methods=["POST"])
@login_required
def reset_student_pin(course_id, student_id):
    """
    Clears a student's self-claimed PIN so they can set a new one on their
    next visit — the only recovery path for a forgotten PIN, and also the
    fix if the wrong person claimed a name/ID by mistake.
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    student = Student.find(student_id)
    if not student or not Group.first(id=student.group_id, course_id=course_id):
        return jsonify({"error": "Student not found in this course"}), 404

    student.reset_pin()
    return jsonify({"message": f"PIN cleared for {student.name} — they can set a new one next time they open the evaluation link."})
