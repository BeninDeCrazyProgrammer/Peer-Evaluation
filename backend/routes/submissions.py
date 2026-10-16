from flask import Blueprint, request, jsonify

from db import execute

submissions_bp = Blueprint("submissions", __name__, url_prefix="/courses/<int:course_id>/evaluations/<int:evaluation_id>")


def _find_student(course_id, identifier):
    """Match by student_id first (exact), then by name (case-insensitive), within this course."""
    rs = execute(
        "SELECT s.id, s.name, s.student_id, s.group_id "
        "FROM students s JOIN groups g ON g.id = s.group_id "
        "WHERE g.course_id = ? AND s.student_id = ?",
        [course_id, identifier.strip()],
    )
    if rs.rows:
        return dict(zip(rs.columns, rs.rows[0]))

    rs = execute(
        "SELECT s.id, s.name, s.student_id, s.group_id "
        "FROM students s JOIN groups g ON g.id = s.group_id "
        "WHERE g.course_id = ? AND LOWER(s.name) = LOWER(?)",
        [course_id, identifier.strip()],
    )
    if rs.rows:
        return dict(zip(rs.columns, rs.rows[0]))

    return None


@submissions_bp.route("/lookup", methods=["POST"])
def lookup(course_id, evaluation_id):
    """
    Body: {"identifier": "10984191"}   -- student ID or full name
    Returns the student's record, their group's other members (self excluded),
    and whether they've already submitted this evaluation.
    """
    data = request.get_json(force=True)
    identifier = (data.get("identifier") or "").strip()
    if not identifier:
        return jsonify({"error": "Enter your name or student ID"}), 400

    student = _find_student(course_id, identifier)
    if not student:
        return jsonify({"error": "We couldn't find you in this course's groups. Check your ID/name and try again."}), 404

    already = execute(
        "SELECT id FROM submissions WHERE evaluation_id = ? AND evaluator_student_id = ?",
        [evaluation_id, student["id"]],
    )
    if already.rows:
        return jsonify({"error": "You've already submitted this evaluation.", "already_submitted": True}), 409

    peers = execute(
        "SELECT id, name FROM students WHERE group_id = ? AND id != ? ORDER BY name",
        [student["group_id"], student["id"]],
    )
    peers_list = [dict(zip(peers.columns, row)) for row in peers.rows]

    return jsonify({
        "student": {"id": student["id"], "name": student["name"], "student_id": student["student_id"]},
        "peers_to_evaluate": peers_list,
    })


@submissions_bp.route("/submit", methods=["POST"])
def submit(course_id, evaluation_id):
    """
    Body:
    {
      "evaluator_student_id": 42,
      "scores": [{"ratee_student_id": 7, "criterion_id": 3, "score": 4}, ...]
    }
    Every (peer x criterion) combination is expected — validated for completeness
    and that every score is a legal value on this evaluation's scale.
    """
    data = request.get_json(force=True)
    evaluator_id = data.get("evaluator_student_id")
    scores = data.get("scores") or []

    if not evaluator_id or not scores:
        return jsonify({"error": "evaluator_student_id and scores are required"}), 400

    # Evaluator must belong to this course
    rs = execute(
        "SELECT s.group_id FROM students s JOIN groups g ON g.id = s.group_id "
        "WHERE s.id = ? AND g.course_id = ?",
        [evaluator_id, course_id],
    )
    if not rs.rows:
        return jsonify({"error": "Student not found in this course"}), 404
    evaluator_group_id = rs.rows[0][0]

    # Block a repeat submission before doing any other work
    already = execute(
        "SELECT id FROM submissions WHERE evaluation_id = ? AND evaluator_student_id = ?",
        [evaluation_id, evaluator_id],
    )
    if already.rows:
        return jsonify({"error": "You've already submitted this evaluation."}), 409

    # Valid scale values for this evaluation
    scale_rs = execute("SELECT value FROM evaluation_scale WHERE evaluation_id = ?", [evaluation_id])
    valid_values = {row[0] for row in scale_rs.rows}

    # Valid criteria for this evaluation
    crit_rs = execute("SELECT id FROM evaluation_criteria WHERE evaluation_id = ?", [evaluation_id])
    valid_criteria = {row[0] for row in crit_rs.rows}

    # Valid ratees: everyone else in the evaluator's group
    peers_rs = execute("SELECT id FROM students WHERE group_id = ? AND id != ?", [evaluator_group_id, evaluator_id])
    valid_ratees = {row[0] for row in peers_rs.rows}

    for s in scores:
        if s.get("ratee_student_id") == evaluator_id:
            return jsonify({"error": "You can't rate yourself"}), 400
        if s.get("ratee_student_id") not in valid_ratees:
            return jsonify({"error": "One of the rated students isn't in your group"}), 400
        if s.get("criterion_id") not in valid_criteria:
            return jsonify({"error": "Unrecognized criterion"}), 400
        if s.get("score") not in valid_values:
            return jsonify({"error": f"Score {s.get('score')} isn't on this evaluation's scale"}), 400

    expected = len(valid_ratees) * len(valid_criteria)
    if len(scores) != expected:
        return jsonify({"error": f"Expected {expected} scores (every peer x every criterion), got {len(scores)}"}), 400

    sub_rs = execute(
        "INSERT INTO submissions (evaluation_id, evaluator_student_id) VALUES (?, ?) RETURNING id",
        [evaluation_id, evaluator_id],
    )
    submission_id = sub_rs.rows[0][0]

    for s in scores:
        execute(
            "INSERT INTO submission_scores (submission_id, ratee_student_id, criterion_id, score) VALUES (?, ?, ?, ?)",
            [submission_id, s["ratee_student_id"], s["criterion_id"], s["score"]],
        )

    return jsonify({"message": "Submitted — thank you!"}), 201
