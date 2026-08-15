from flask import Blueprint, request, jsonify

from models import Evaluation, Student, Submission, EvaluationScale, EvaluationCriterion, AmbiguousStudentError
from db import batch_execute
from rate_limit import limiter, pin_attempt_key

submissions_bp = Blueprint("submissions", __name__, url_prefix="/courses/<int:course_id>/evaluations/<int:evaluation_id>")

# lookup/ and submit/ both verify a student's PIN and are unauthenticated, so
# they get a per-identity limit (pin_attempt_key) on top of the plain per-IP
# one — a 4-digit PIN is only 10,000 combinations, and without this an
# attacker could brute-force one student's PIN in well under a minute.


def _valid_pin_format(pin):
    return isinstance(pin, str) and len(pin) == 4 and pin.isdigit()


def _find_student_or_error(course_id, identifier):
    """
    Wraps Student.find_in_course for the three routes below: returns
    (student, None) on a clean match, or (None, (response, status)) if the
    caller should return early — either nobody matched, or more than one
    student did (see AmbiguousStudentError's docstring in models.py).
    """
    try:
        student = Student.find_in_course(course_id, identifier)
    except AmbiguousStudentError:
        return None, (jsonify({
            "error": "More than one student matches that. If you used your name, try your student ID instead — "
                     "if your ID doesn't work either, ask your lecturer to check the roster for a duplicate ID."
        }), 409)
    if not student:
        return None, (jsonify({"error": "We couldn't find you in this course's groups. Check your ID/name and try again."}), 404)
    return student, None


@submissions_bp.route("/identify", methods=["POST"])
@limiter.limit("30 per hour")
def identify(course_id, evaluation_id):
    """
    Body: {"identifier": "10984191"}   -- student ID or full name
    First step of access: just resolves who the student is and whether
    they've claimed a PIN yet, so the frontend knows whether to show a
    "create your PIN" or "enter your PIN" form next. Doesn't touch scores
    or reveal groupmates — that only happens after /lookup succeeds.
    """
    data = request.get_json(force=True)
    identifier = (data.get("identifier") or "").strip()
    if not identifier:
        return jsonify({"error": "Enter your name or student ID"}), 400

    student, error = _find_student_or_error(course_id, identifier)
    if error:
        return error

    return jsonify({"name": student.name, "has_pin": student.has_pin()})


@submissions_bp.route("/claim-pin", methods=["POST"])
@limiter.limit("20 per hour")
def claim_pin(course_id, evaluation_id):
    """
    Body: {"identifier": "10984191", "pin": "4821", "confirm_pin": "4821"}
    First-time-only: sets this student's PIN. Whoever gets here first for a
    given name/ID owns that identity from then on — same as any "claim your
    account" flow. If a PIN is already set, this refuses; the lecturer can
    clear it (roster > Reset PIN) if a student is legitimately locked out.
    On success, behaves like /lookup and returns the peer list right away.
    """
    data = request.get_json(force=True)
    identifier = (data.get("identifier") or "").strip()
    pin = (data.get("pin") or "").strip()
    confirm_pin = (data.get("confirm_pin") or "").strip()

    if not _valid_pin_format(pin):
        return jsonify({"error": "PIN must be exactly 4 digits"}), 400
    if pin != confirm_pin:
        return jsonify({"error": "PINs don't match"}), 400

    student, error = _find_student_or_error(course_id, identifier)
    if error:
        return error
    if student.has_pin():
        return jsonify({"error": "A PIN is already set for this name/ID. Log in with it instead, or ask your lecturer to reset it."}), 409

    student.claim_pin(pin)
    return _access_response(student, evaluation_id)


@submissions_bp.route("/lookup", methods=["POST"])
@limiter.limit("30 per hour")
@limiter.limit("8 per 15 minutes", key_func=pin_attempt_key)
def lookup(course_id, evaluation_id):
    """
    Body: {"identifier": "10984191", "pin": "4821"}
    Log in with an already-claimed PIN. Returns the student's record, their
    group's other members (self excluded), and 409s if they've already
    submitted this evaluation.
    """
    data = request.get_json(force=True)
    identifier = (data.get("identifier") or "").strip()
    pin = (data.get("pin") or "").strip()
    if not identifier:
        return jsonify({"error": "Enter your name or student ID"}), 400
    if not pin:
        return jsonify({"error": "Enter your PIN"}), 400

    student, error = _find_student_or_error(course_id, identifier)
    if error:
        return error
    if not student.has_pin():
        return jsonify({"error": "No PIN has been set for this name/ID yet — create one first.", "needs_claim": True}), 409

    # Deliberately the same error as "not found" — don't reveal whether the
    # ID/name matched a real student, only that the identifier+PIN pair failed.
    if not student.check_pin(pin):
        return jsonify({"error": "Incorrect PIN. Forgot it? Ask your lecturer to reset it."}), 401

    return _access_response(student, evaluation_id)


def _access_response(student, evaluation_id):
    if Submission.exists(evaluation_id=evaluation_id, evaluator_student_id=student.id):
        return jsonify({"error": "You've already submitted this evaluation.", "already_submitted": True}), 409

    peers = Student.groupmates(student.group_id, excluding_id=student.id)

    return jsonify({
        "student": {"id": student.id, "name": student.name, "student_id": student.student_id},
        "peers_to_evaluate": [{"id": p.id, "name": p.name} for p in peers],
    })


@submissions_bp.route("/submit", methods=["POST"])
@limiter.limit("30 per hour")
@limiter.limit("8 per 15 minutes", key_func=pin_attempt_key)
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
    pin = (data.get("pin") or "").strip()
    scores = data.get("scores") or []

    if not evaluator_id or not scores:
        return jsonify({"error": "evaluator_student_id and scores are required"}), 400
    if not pin:
        return jsonify({"error": "Your PIN is required to submit"}), 400

    evaluator = Student.find(evaluator_id)
    if not evaluator:
        return jsonify({"error": "Student not found in this course"}), 404
    # Confirm the student's group actually belongs to this course.
    from models import Group
    group = Group.first(id=evaluator.group_id, course_id=course_id)
    if not group:
        return jsonify({"error": "Student not found in this course"}), 404
    # Re-verify the PIN here too — /lookup and /submit are independent
    # requests, and this is the call that actually writes scores, so it
    # can't trust that whoever calls it already passed /lookup.
    if not evaluator.check_pin(pin):
        return jsonify({"error": "Incorrect PIN"}), 401

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

    # Check the exact set of (ratee, criterion) pairs, not just the count —
    # matching counts alone would let a client send two scores for one
    # peer/criterion and silently skip another, passing validation while
    # leaving a gap in the data.
    expected_pairs = {(r, c) for r in valid_ratees for c in valid_criteria}
    submitted_pairs = {(s["ratee_student_id"], s["criterion_id"]) for s in scores}
    if submitted_pairs != expected_pairs:
        missing = expected_pairs - submitted_pairs
        extra = submitted_pairs - expected_pairs
        duplicates = len(scores) != len(submitted_pairs)
        detail = "Duplicate entries for the same peer/criterion." if duplicates and not missing and not extra \
            else "Missing or unexpected peer/criterion combinations."
        return jsonify({
            "error": f"Expected exactly one score per peer per criterion — every peer x every criterion. {detail}"
        }), 400

    # Written as one atomic batch (Submission + every SubmissionScore) so a
    # dropped connection or DB error partway through can't leave a Submission
    # row on its own with only some of its scores — that would both corrupt
    # this student's data and permanently lock them out of resubmitting,
    # since submissions are one-per-student with no reset.
    statements = [
        (
            "INSERT INTO submissions (evaluation_id, evaluator_student_id) VALUES (?, ?)",
            [evaluation_id, evaluator_id],
        )
    ]
    for s in scores:
        statements.append((
            "INSERT INTO submission_scores (submission_id, ratee_student_id, criterion_id, score) "
            "VALUES (last_insert_rowid(), ?, ?, ?)",
            [s["ratee_student_id"], s["criterion_id"], s["score"]],
        ))

    try:
        batch_execute(statements)
    except Exception:
        return jsonify({"error": "Something went wrong saving your submission. Please try again."}), 500

    return jsonify({"message": "Submitted — thank you!"}), 201
