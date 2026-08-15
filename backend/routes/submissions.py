from flask import Blueprint, request, jsonify

from models import Evaluation, Student, Submission, SubmissionScore, EvaluationScale, EvaluationCriterion

submissions_bp = Blueprint("submissions", __name__, url_prefix="/courses/<int:course_id>/evaluations/<int:evaluation_id>")


@submissions_bp.route("/lookup", methods=["POST"])
def lookup(course_id, evaluation_id):
    """
    Body: {"identifier": "10984191"}   -- student ID or full name
    Returns the student's record, their group's other members (self excluded),
    and 409s if they've already submitted this evaluation.
    """
    data = request.get_json(force=True)
    identifier = (data.get("identifier") or "").strip()
    if not identifier:
        return jsonify({"error": "Enter your name or student ID"}), 400

    student = Student.find_in_course(course_id, identifier)
    if not student:
        return jsonify({"error": "We couldn't find you in this course's groups. Check your ID/name and try again."}), 404

    if Submission.exists(evaluation_id=evaluation_id, evaluator_student_id=student.id):
        return jsonify({"error": "You've already submitted this evaluation.", "already_submitted": True}), 409

    peers = Student.groupmates(student.group_id, excluding_id=student.id)

    return jsonify({
        "student": {"id": student.id, "name": student.name, "student_id": student.student_id},
        "peers_to_evaluate": [{"id": p.id, "name": p.name} for p in peers],
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

    evaluator = Student.find(evaluator_id)
    if not evaluator:
        return jsonify({"error": "Student not found in this course"}), 404
    # Confirm the student's group actually belongs to this course.
    from models import Group
    group = Group.first(id=evaluator.group_id, course_id=course_id)
    if not group:
        return jsonify({"error": "Student not found in this course"}), 404

    if Submission.exists(evaluation_id=evaluation_id, evaluator_student_id=evaluator_id):
        return jsonify({"error": "You've already submitted this evaluation."}), 409

    valid_values = {s.value for s in EvaluationScale.where(evaluation_id=evaluation_id)}
    valid_criteria = {c.id for c in EvaluationCriterion.where(evaluation_id=evaluation_id)}
    valid_ratees = {p.id for p in Student.groupmates(evaluator.group_id, excluding_id=evaluator_id)}

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

    submission = Submission.create(evaluation_id=evaluation_id, evaluator_student_id=evaluator_id)
    for s in scores:
        SubmissionScore.create(
            submission_id=submission.id,
            ratee_student_id=s["ratee_student_id"],
            criterion_id=s["criterion_id"],
            score=s["score"],
        )

    return jsonify({"message": "Submitted — thank you!"}), 201
