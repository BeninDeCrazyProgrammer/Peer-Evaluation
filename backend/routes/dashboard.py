from flask import Blueprint, jsonify, Response
from flask_login import login_required
import csv
import io

from db import execute
from routes.courses import _assert_owns_course

dashboard_bp = Blueprint(
    "dashboard", __name__, url_prefix="/courses/<int:course_id>/evaluations/<int:evaluation_id>"
)


@dashboard_bp.route("/completion", methods=["GET"])
@login_required
def completion(course_id, evaluation_id):
    """Who has and hasn't submitted yet, grouped by group."""
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    rs = execute(
        "SELECT g.id AS group_id, g.group_label, s.id AS student_pk, s.name, s.student_id, "
        "       CASE WHEN sub.id IS NULL THEN 0 ELSE 1 END AS has_submitted "
        "FROM groups g "
        "JOIN students s ON s.group_id = g.id "
        "LEFT JOIN submissions sub ON sub.evaluator_student_id = s.id AND sub.evaluation_id = ? "
        "WHERE g.course_id = ? ORDER BY g.id, s.name",
        [evaluation_id, course_id],
    )

    groups_by_id = {}
    for row in rs.rows:
        r = dict(zip(rs.columns, row))
        g = groups_by_id.setdefault(
            r["group_id"], {"id": r["group_id"], "group_label": r["group_label"], "students": []}
        )
        g["students"].append({
            "id": r["student_pk"],
            "name": r["name"],
            "student_id": r["student_id"],
            "has_submitted": bool(r["has_submitted"]),
        })

    return jsonify(list(groups_by_id.values()))


@dashboard_bp.route("/results", methods=["GET"])
@login_required
def results(course_id, evaluation_id):
    """
    Per-student aggregate averages (overall + per criterion), plus the full
    individual evaluator -> ratee -> criterion -> score breakdown, per the
    lecturer's request to see both.
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    criteria_rs = execute(
        "SELECT id, name FROM evaluation_criteria WHERE evaluation_id = ? ORDER BY sort_order",
        [evaluation_id],
    )
    criteria = [dict(zip(criteria_rs.columns, row)) for row in criteria_rs.rows]

    # Individual breakdown: every evaluator's score for every ratee/criterion
    detail_rs = execute(
        "SELECT ev_s.name AS evaluator_name, ev_s.student_id AS evaluator_student_id, "
        "       rt_s.id AS ratee_id, rt_s.name AS ratee_name, "
        "       ec.name AS criterion, sc.score "
        "FROM submission_scores sc "
        "JOIN submissions sub ON sub.id = sc.submission_id "
        "JOIN students ev_s ON ev_s.id = sub.evaluator_student_id "
        "JOIN students rt_s ON rt_s.id = sc.ratee_student_id "
        "JOIN evaluation_criteria ec ON ec.id = sc.criterion_id "
        "WHERE sub.evaluation_id = ? "
        "ORDER BY rt_s.name, ev_s.name, ec.sort_order",
        [evaluation_id],
    )
    individual_scores = [dict(zip(detail_rs.columns, row)) for row in detail_rs.rows]

    # Aggregates: average score received per student per criterion, plus overall average
    agg_rs = execute(
        "SELECT rt_s.id AS ratee_id, rt_s.name AS ratee_name, ec.id AS criterion_id, "
        "       ec.name AS criterion, AVG(sc.score) AS avg_score, COUNT(sc.score) AS num_ratings "
        "FROM submission_scores sc "
        "JOIN submissions sub ON sub.id = sc.submission_id "
        "JOIN students rt_s ON rt_s.id = sc.ratee_student_id "
        "JOIN evaluation_criteria ec ON ec.id = sc.criterion_id "
        "WHERE sub.evaluation_id = ? "
        "GROUP BY rt_s.id, ec.id "
        "ORDER BY rt_s.name, ec.sort_order",
        [evaluation_id],
    )

    students_agg = {}
    for row in agg_rs.rows:
        r = dict(zip(agg_rs.columns, row))
        student = students_agg.setdefault(
            r["ratee_id"], {"student_id": r["ratee_id"], "name": r["ratee_name"], "by_criterion": [], "overall_average": None}
        )
        student["by_criterion"].append({
            "criterion": r["criterion"],
            "average": round(r["avg_score"], 2),
            "num_ratings": r["num_ratings"],
        })

    for student in students_agg.values():
        vals = [c["average"] for c in student["by_criterion"]]
        student["overall_average"] = round(sum(vals) / len(vals), 2) if vals else None

    return jsonify({
        "criteria": criteria,
        "aggregates": list(students_agg.values()),
        "individual_scores": individual_scores,
    })


@dashboard_bp.route("/results/export.csv", methods=["GET"])
@login_required
def export_csv(course_id, evaluation_id):
    """
    One CSV with two sections: per-student averages first, then the full
    individual evaluator breakdown below it — opens cleanly in Excel/Sheets.
    """
    if not _assert_owns_course(course_id):
        return jsonify({"error": "Course not found"}), 404

    data = results(course_id, evaluation_id).get_json()
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

    eval_row = execute("SELECT title FROM evaluations WHERE id = ?", [evaluation_id])
    title = eval_row.rows[0][0] if eval_row.rows else f"evaluation-{evaluation_id}"
    filename = "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip() or "results"

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
