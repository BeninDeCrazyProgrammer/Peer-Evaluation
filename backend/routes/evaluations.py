import base64
import io
import os
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from flask_login import login_required
import qrcode

from models import Evaluation, Submission, Class
from routes.courses import _assert_owns_course

evaluations_bp = Blueprint("evaluations", __name__, url_prefix="/courses/<int:course_id>/evaluations")


def _validate_deadline(deadline):
    """None if not set, a parsed aware datetime if valid, or an error tuple."""
    if not deadline:
        return None, None
    try:
        parsed = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    except ValueError:
        return None, (jsonify({"error": "Deadline isn't a valid date/time"}), 400)
    if parsed.tzinfo is None:
        return None, (jsonify({"error": "Deadline must include a timezone"}), 400)
    return parsed, None


def _validate_payload(data):
    title = (data.get("title") or "").strip()
    criteria = data.get("criteria") or []
    scale = data.get("scale") or []
    deadline = (data.get("deadline") or "").strip() or None
    if not title:
        return None, (jsonify({"error": "Title is required"}), 400)
    if len(criteria) < 1:
        return None, (jsonify({"error": "At least one criterion is required"}), 400)
    if len(scale) < 2:
        return None, (jsonify({"error": "The scale needs at least 2 points (e.g. 0 and 1)"}), 400)
    _, error = _validate_deadline(deadline)
    if error:
        return None, error
    return (title, criteria, scale, deadline), None


def _deadline_fields_with_reopen(evaluation, deadline):
    """
    Fields to persist for a deadline change, including reopening the
    evaluation if a deadline that had auto-closed it just got pushed into the
    future — otherwise it'd stay "closed" forever even with a new deadline,
    since check_and_close() only ever flips open -> closed, never back.
    """
    fields = {"deadline": deadline}
    if deadline and evaluation.status == "closed":
        parsed, _ = _validate_deadline(deadline)
        if parsed and parsed > datetime.now(timezone.utc):
            fields["status"] = "open"
    return fields


@evaluations_bp.route("", methods=["POST"])
@login_required
def create_evaluation(course_id):
    """
    Body: {"class_id": 3, "title": "...", "criteria": ["Participation", ...], "scale": [{"value": 0, "label": "Unacceptable"}, ...]}
    Both criteria and scale are fully lecturer-defined — nothing is hardcoded.
    class_id picks which class's roster this evaluation runs against; a
    course can now have more than one class (year group/section), so this
    is required and fixed at creation — see Class in models.py.
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    data = request.get_json(force=True)
    class_id = data.get("class_id")
    if not class_id:
        return jsonify({"error": "Select a class for this evaluation"}), 400
    if not Class.exists(id=class_id, course_id=course_id):
        return jsonify({"error": "Class not found in this course"}), 404

    parsed, error = _validate_payload(data)
    if error:
        return error
    title, criteria, scale, deadline = parsed

    evaluation = Evaluation.create(course_id=course_id, class_id=class_id, title=title, deadline=deadline)
    evaluation.set_criteria_and_scale(criteria, scale)
    return jsonify(evaluation.to_dict()), 201


@evaluations_bp.route("", methods=["GET"])
@login_required
def list_evaluations(course_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    evals = Evaluation.where(order_by="created_at DESC", course_id=course_id)
    classes_by_id = {c.id: c.name for c in Class.where(course_id=course_id)}
    result = []
    for e in evals:
        d = e.to_dict()
        d["class_name"] = classes_by_id.get(e.class_id)
        result.append(d)
    return jsonify(result)


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
    title, criteria, scale, deadline = parsed

    evaluation.update(title=title, **_deadline_fields_with_reopen(evaluation, deadline))
    evaluation.set_criteria_and_scale(criteria, scale)
    return jsonify({"message": "Evaluation updated"})


@evaluations_bp.route("/<int:evaluation_id>/deadline", methods=["PATCH"])
@login_required
def update_deadline(course_id, evaluation_id):
    """
    Deadline can be changed any time — including after submissions exist —
    since unlike criteria/scale it doesn't invalidate anything already
    answered. Kept separate from the full-form PATCH above for that reason:
    the lecturer shouldn't have to touch a locked criteria/scale just to
    push a deadline back.
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    evaluation = Evaluation.first(id=evaluation_id, course_id=course_id)
    if not evaluation:
        return jsonify({"error": "Evaluation not found"}), 404

    deadline = (request.get_json(force=True).get("deadline") or "").strip() or None
    _, error = _validate_deadline(deadline)
    if error:
        return error

    evaluation.update(**_deadline_fields_with_reopen(evaluation, deadline))
    return jsonify(evaluation.to_dict())


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
