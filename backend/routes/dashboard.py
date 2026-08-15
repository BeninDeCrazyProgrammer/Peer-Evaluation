import csv
import io

from flask import Blueprint, jsonify, Response
from flask_login import login_required

from models import Evaluation
from routes.courses import _assert_owns_course

dashboard_bp = Blueprint(
    "dashboard", __name__, url_prefix="/courses/<int:course_id>/evaluations/<int:evaluation_id>"
)


def _get_owned_evaluation(course_id, evaluation_id):
    if not _assert_owns_course(course_id):
        return None
    return Evaluation.first(id=evaluation_id, course_id=course_id)


@dashboard_bp.route("/completion", methods=["GET"])
@login_required
def completion(course_id, evaluation_id):
    """Who has and hasn't submitted yet, grouped by group."""
    evaluation = _get_owned_evaluation(course_id, evaluation_id)
    if not evaluation:
        return jsonify({"error": "Evaluation not found"}), 404
    return jsonify(evaluation.completion())


@dashboard_bp.route("/results", methods=["GET"])
@login_required
def results(course_id, evaluation_id):
    """Per-student aggregate averages plus the full individual evaluator breakdown."""
    evaluation = _get_owned_evaluation(course_id, evaluation_id)
    if not evaluation:
        return jsonify({"error": "Evaluation not found"}), 404
    return jsonify(evaluation.results())


@dashboard_bp.route("/results/export.csv", methods=["GET"])
@login_required
def export_csv(course_id, evaluation_id):
    """
    One CSV with two sections: per-student averages first, then the full
    individual evaluator breakdown below it — opens cleanly in Excel/Sheets.
    """
    evaluation = _get_owned_evaluation(course_id, evaluation_id)
    if not evaluation:
        return jsonify({"error": "Evaluation not found"}), 404

    data = evaluation.results()
    criteria_names = [c["name"] for c in data["criteria"]]

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(["Averages per student"])
    writer.writerow(["Student"] + criteria_names + ["Overall average"])
    for s in data["aggregates"]:
        by_name = {c["criterion"]: c["average"] for c in s["by_criterion"]}
        writer.writerow([s["name"]] + [by_name.get(c, "") for c in criteria_names] + [s["overall_average"]])

    writer.writerow([])
    writer.writerow(["Individual evaluator scores"])
    writer.writerow(["Evaluator", "Rated", "Criterion", "Score"])
    for r in data["individual_scores"]:
        writer.writerow([r["evaluator_name"], r["ratee_name"], r["criterion"], r["score"]])

    filename = "".join(c if c.isalnum() or c in " -_" else "_" for c in evaluation.title).strip() or "results"

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
