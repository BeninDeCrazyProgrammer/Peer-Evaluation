import base64
import io
import os

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import qrcode

from db import execute
from routes.courses import _assert_owns_course

evaluations_bp = Blueprint("evaluations", __name__, url_prefix="/courses/<int:course_id>/evaluations")


@evaluations_bp.route("", methods=["POST"])
@login_required
def create_evaluation(course_id):
    """
    Body:
    {
      "title": "Peer Evaluation 1",
      "criteria": ["Participation", "Punctuality", ...],
      "scale": [{"value": 0, "label": "Unacceptable"}, {"value": 1, "label": "Poor"}, ...]
    }
    Both criteria and scale are fully lecturer-defined — nothing is hardcoded.
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    criteria = data.get("criteria") or []
    scale = data.get("scale") or []

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(criteria) < 1:
        return jsonify({"error": "At least one criterion is required"}), 400
    if len(scale) < 2:
        return jsonify({"error": "The scale needs at least 2 points (e.g. 0 and 1)"}), 400

    rs = execute(
        "INSERT INTO evaluations (course_id, title) VALUES (?, ?) RETURNING id",
        [course_id, title],
    )
    evaluation_id = rs.rows[0][0]

    for i, name in enumerate(criteria):
        execute(
            "INSERT INTO evaluation_criteria (evaluation_id, name, sort_order) VALUES (?, ?, ?)",
            [evaluation_id, name.strip(), i],
        )
    for point in scale:
        execute(
            "INSERT INTO evaluation_scale (evaluation_id, value, label) VALUES (?, ?, ?)",
            [evaluation_id, point["value"], point["label"].strip()],
        )

    return jsonify({"id": evaluation_id, "title": title}), 201


@evaluations_bp.route("", methods=["GET"])
@login_required
def list_evaluations(course_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    rs = execute(
        "SELECT id, title, status, created_at FROM evaluations WHERE course_id = ? ORDER BY created_at DESC",
        [course_id],
    )
    return jsonify([dict(zip(rs.columns, row)) for row in rs.rows])


@evaluations_bp.route("/<int:evaluation_id>", methods=["GET"])
def get_evaluation(course_id, evaluation_id):
    """Public — the student-facing evaluate page needs this without being logged in."""
    rs = execute(
        "SELECT id, title, status FROM evaluations WHERE id = ? AND course_id = ?",
        [evaluation_id, course_id],
    )
    if not rs.rows:
        return jsonify({"error": "Evaluation not found"}), 404
    evaluation = dict(zip(rs.columns, rs.rows[0]))

    crs = execute(
        "SELECT id, name FROM evaluation_criteria WHERE evaluation_id = ? ORDER BY sort_order",
        [evaluation_id],
    )
    evaluation["criteria"] = [dict(zip(crs.columns, row)) for row in crs.rows]

    srs = execute(
        "SELECT value, label FROM evaluation_scale WHERE evaluation_id = ? ORDER BY value",
        [evaluation_id],
    )
    evaluation["scale"] = [dict(zip(srs.columns, row)) for row in srs.rows]

    return jsonify(evaluation)


@evaluations_bp.route("/<int:evaluation_id>", methods=["PATCH"])
@login_required
def update_evaluation(course_id, evaluation_id):
    """
    Replaces title/criteria/scale wholesale — only allowed while the
    evaluation has zero submissions, since changing criteria or scale
    values after students have started would silently invalidate their
    answers (a criterion_id or score value could stop lining up).
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    existing = execute(
        "SELECT id FROM evaluations WHERE id = ? AND course_id = ?", [evaluation_id, course_id]
    )
    if not existing.rows:
        return jsonify({"error": "Evaluation not found"}), 404

    submitted = execute(
        "SELECT id FROM submissions WHERE evaluation_id = ? LIMIT 1", [evaluation_id]
    )
    if submitted.rows:
        return jsonify({
            "error": "This evaluation already has submissions, so its criteria and scale can't be changed. "
                     "Close it and create a new evaluation instead."
        }), 409

    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    criteria = data.get("criteria") or []
    scale = data.get("scale") or []

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(criteria) < 1:
        return jsonify({"error": "At least one criterion is required"}), 400
    if len(scale) < 2:
        return jsonify({"error": "The scale needs at least 2 points (e.g. 0 and 1)"}), 400

    execute("UPDATE evaluations SET title = ? WHERE id = ?", [title, evaluation_id])
    execute("DELETE FROM evaluation_criteria WHERE evaluation_id = ?", [evaluation_id])
    execute("DELETE FROM evaluation_scale WHERE evaluation_id = ?", [evaluation_id])

    for i, name in enumerate(criteria):
        execute(
            "INSERT INTO evaluation_criteria (evaluation_id, name, sort_order) VALUES (?, ?, ?)",
            [evaluation_id, name.strip(), i],
        )
    for point in scale:
        execute(
            "INSERT INTO evaluation_scale (evaluation_id, value, label) VALUES (?, ?, ?)",
            [evaluation_id, point["value"], point["label"].strip()],
        )

    return jsonify({"message": "Evaluation updated"})


@evaluations_bp.route("/<int:evaluation_id>/close", methods=["POST"])
@login_required
def close_evaluation(course_id, evaluation_id):
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404
    execute("UPDATE evaluations SET status = 'closed' WHERE id = ? AND course_id = ?", [evaluation_id, course_id])
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
