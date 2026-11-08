import os
import re

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from models import Course, CourseMember, CourseInvite, Lecturer
from db import execute
from rate_limit import limiter
from routes.courses import _assert_course_owner

# Team management for a course: the owner invites TAs, who then get access to
# the course (evaluations, classes, rosters, results) but can't delete things
# or manage the team. See routes/courses.py (_assert_course_owner) for what
# "owner only" covers.
members_bp = Blueprint("members", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _invite_link(token):
    frontend_url = os.environ.get("FRONTEND_URL", "").rstrip("/")
    return f"{frontend_url}/lecturer/login.html?invite={token}"


@members_bp.route("/courses/<int:course_id>/members", methods=["GET"])
@login_required
def list_members(course_id):
    if not _assert_course_owner(course_id):
        return jsonify({"error": "Course not found"}), 404
    course = Course.find(course_id)
    owner = Lecturer.find(course.lecturer_id)
    return jsonify({
        "owner": {"name": owner.name, "email": owner.email},
        "members": CourseMember.with_lecturers(course_id),
        "invites": CourseInvite.pending_for_course(course_id),
    })


@members_bp.route("/courses/<int:course_id>/members", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def add_member(course_id):
    """
    Body: {"email": "ta@university.edu"}
    If that email already has an account, the TA is added straight away and
    sees the course on their dashboard. If not, a one-time invite link is
    created (shown once) for the owner to send; it lets that address register
    without the department system key and joins them to this course.
    """
    if not _assert_course_owner(course_id):
        return jsonify({"error": "Course not found"}), 404

    email = ((request.get_json(force=True) or {}).get("email") or "").strip()
    if not _EMAIL_RE.match(email):
        return jsonify({"error": "Enter a valid email address"}), 400
    if email.lower() == current_user.email.strip().lower():
        return jsonify({"error": "You already own this course"}), 400

    lecturer = Lecturer.find_by_email(email)
    if lecturer:
        if CourseMember.exists(course_id=course_id, lecturer_id=lecturer.id):
            return jsonify({"error": f"{lecturer.name} already has access to this course"}), 409
        CourseMember.create(course_id=course_id, lecturer_id=lecturer.id, role="ta")
        return jsonify({"status": "added", "name": lecturer.name, "email": lecturer.email}), 201

    invite, token = CourseInvite.issue(course_id, email, current_user.id)
    return jsonify({"status": "invited", "email": invite.email, "invite_link": _invite_link(token),
                    "expires_at": invite.expires_at}), 201


@members_bp.route("/courses/<int:course_id>/members/<int:lecturer_id>", methods=["DELETE"])
@login_required
def remove_member(course_id, lecturer_id):
    if not _assert_course_owner(course_id):
        return jsonify({"error": "Course not found"}), 404
    if not CourseMember.exists(course_id=course_id, lecturer_id=lecturer_id):
        return jsonify({"error": "That person isn't on this course's team"}), 404
    CourseMember.delete_where(course_id=course_id, lecturer_id=lecturer_id)
    return jsonify({"message": "Access removed"})


@members_bp.route("/courses/<int:course_id>/invites/<int:invite_id>", methods=["DELETE"])
@login_required
def revoke_invite(course_id, invite_id):
    if not _assert_course_owner(course_id):
        return jsonify({"error": "Course not found"}), 404
    if not CourseInvite.exists(id=invite_id, course_id=course_id):
        return jsonify({"error": "Invite not found"}), 404
    CourseInvite.delete_where(id=invite_id, course_id=course_id)
    return jsonify({"message": "Invite revoked"})


@members_bp.route("/invites/preview", methods=["GET"])
@limiter.limit("30 per hour")
def preview_invite():
    """Public: lets the login page show who/what an invite link is for (needs the secret token)."""
    invite = CourseInvite.find_valid(request.args.get("token", ""))
    if not invite:
        return jsonify({"error": "This invite link is invalid, expired, or already used."}), 404
    course = Course.find(invite.course_id)
    inviter = Lecturer.find(invite.invited_by)
    return jsonify({"email": invite.email, "course_name": course.name if course else "a course",
                    "invited_by": inviter.name if inviter else None})


@members_bp.route("/invites/accept", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def accept_invite():
    """Body: {"token": "..."}. The signed-in account's email must match the address that was invited."""
    token = (request.get_json(force=True) or {}).get("token", "")
    invite = CourseInvite.find_valid(token, email=current_user.email)
    if not invite:
        return jsonify({"error": "This invite link is invalid, expired, already used, or was sent to a different email address."}), 400

    if Course.role_for(invite.course_id, current_user.id) is None:
        CourseMember.create(course_id=invite.course_id, lecturer_id=current_user.id, role="ta")
    execute("UPDATE course_invites SET accepted_at = datetime('now') WHERE id = ?", [invite.id])
    return jsonify({"course_id": invite.course_id})
