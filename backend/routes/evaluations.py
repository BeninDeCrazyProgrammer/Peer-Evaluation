import base64
import io
import os

from flask import Blueprint, request, jsonify
from flask_login import login_required
import qrcode

from models import Evaluation, Submission
from routes.courses import _assert_owns_course

evaluations_bp = Blueprint("evaluations", __name__, url_prefix="/courses/<int:course_id>/evaluations")


def _validate_payload(data):
    title = (data.get("title") or "").strip()
    criteria = data.get("criteria") or []
    scale = data.get("scale") or []
    if not title:
        return None, (jsonify({"error": "Title is required"}), 400)
    if len(criteria) < 1:
        return None, (jsonify({"error": "At least one criterion is required"}), 400)
    if len(scale) < 2:
        return None, (jsonify({"error": "The scale needs at least 2 points (e.g. 0 and 1)"}), 400)
    return (title, criteria, scale), None


@evaluations_bp.route("", methods=["POST"])
@login_required
def create_evaluation(course_id):
    """
    Body: {"title": "...", "criteria": ["Participation", ...], "scale": [{"value": 0, "label": "Unacceptable"}, ...]}
    Both criteria and scale are fully lecturer-defined — nothing is hardcoded.
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    parsed, error = _validate_payload(request.get_json(force=True))
    if error:
        return error
    title, criteria, scale = parsed

    evaluation = Evaluation.create(course_id=course_id, title=title)
    evaluation.set_criteria_and_scale(criteria, scale)
    return jsonify(evaluation.to_dict()), 201


@evaluations_bp.route("", methods=["GET"])
@login_required
def list_evaluations(course_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    evals = Evaluation.where(order_by="created_at DESC", course_id=course_id)
    return jsonify([e.to_dict() for e in evals])


@evaluations_bp.route("/<int:evaluation_id>", methods=["GET"])
def get_evaluation(course_id, evaluation_id):
    """Public — the student-facing evaluate page needs this without being logged in."""
    evaluation = Evaluation.first(id=evaluation_id, course_id=course_id)
    if not evaluation:
        return jsonify({"error": "Evaluation not found"}), 404
    return jsonify(evaluation.to_full_dict())


@evaluations_bp.route("/<int:evaluation_id>", methods=["PATCH"])
@login_required
def update_evaluation(course_id, evaluation_id):
    """
    Replaces title/criteria/scale wholesale — only allowed while the evaluation
    has zero submissions, since changing criteria or scale values afterward
    would silently invalidate students' answers.
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    evaluation = Evaluation.first(id=evaluation_id, course_id=course_id)
    if not evaluation:
        return jsonify({"error": "Evaluation not found"}), 404

    if Submission.exists(evaluation_id=evaluation_id):
        return jsonify({
            "error": "This evaluation already has submissions, so its criteria and scale can't be changed. "
                     "Close it and create a new evaluation instead."
        }), 409

    parsed, error = _validate_payload(request.get_json(force=True))
    if error:
        return error
    title, criteria, scale = parsed

    evaluation.update(title=title)
    evaluation.set_criteria_and_scale(criteria, scale)
    return jsonify({"message": "Evaluation updated"})


@evaluations_bp.route("/<int:evaluation_id>/close", methods=["POST"])
@login_required
def close_evaluation(course_id, evaluation_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    evaluation = Evaluation.first(id=evaluation_id, course_id=course_id)
    if not evaluation:
        return jsonify({"error": "Evaluation not found"}), 404
    evaluation.update(status="closed")
    return jsonify({"message": "Evaluation closed"})


@evaluations_bp.route("/<int:evaluation_id>/link", methods=["GET"])
@login_required
def get_link(course_id, evaluation_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    frontend_url = os.environ.get("FRONTEND_URL", "")
    link = f"{frontend_url}/student/evaluate.html?course={course_id}&evaluation={evaluation_id}"

    img = qrcode.make(link)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return jsonify({"link": link, "qr_code_png_base64": qr_base64})
