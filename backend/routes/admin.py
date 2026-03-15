"""
routes/admin.py – Admin-only Blueprint
All routes require role=admin.

GET    /admin/users                  – list all users with role + status
GET    /admin/users/<id>             – single user detail
PATCH  /admin/users/<id>/role        – change a user's role
PATCH  /admin/users/<id>/activate    – reactivate a user
PATCH  /admin/users/<id>/deactivate  – soft-ban a user
DELETE /admin/users/<id>             – hard-delete a user + all their records
GET    /admin/dashboard              – system-wide stats
"""

import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from models import db, User, PlateRecord, Role, Permission
from middleware.rbac import require_permission, require_role, inject_user

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ── GET /admin/users ───────────────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@jwt_required()
@require_role(Role.ADMIN)
@inject_user
def list_users(current_user: User):
    """Return all users with optional role filter."""
    role_filter = request.args.get("role")
    query = User.query

    if role_filter:
        if not Role.is_valid(role_filter):
            return jsonify({"success": False, "message": f"Invalid role: {role_filter}"}), 400
        query = query.filter_by(role=role_filter)

    page     = max(1, request.args.get("page",     1,  type=int))
    per_page = min(100, request.args.get("per_page", 20, type=int))

    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Annotate each user with their record count
    users_out = []
    for u in pagination.items:
        d = u.to_dict()
        d["total_detections"] = PlateRecord.query.filter_by(user_email=u.email).count()
        users_out.append(d)

    return jsonify({
        "success": True,
        "users": users_out,
        "pagination": {
            "page":     pagination.page,
            "per_page": pagination.per_page,
            "total":    pagination.total,
            "pages":    pagination.pages,
        },
    }), 200


# ── GET /admin/users/<id> ──────────────────────────────────────────────────────

@admin_bp.route("/users/<int:user_id>", methods=["GET"])
@jwt_required()
@require_role(Role.ADMIN)
@inject_user
def get_user(user_id: int, current_user: User):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404

    data = user.to_dict()
    data["total_detections"] = PlateRecord.query.filter_by(user_email=user.email).count()
    data["recent_records"]   = [
        r.to_dict() for r in
        PlateRecord.query.filter_by(user_email=user.email)
                   .order_by(PlateRecord.timestamp.desc()).limit(5).all()
    ]
    return jsonify({"success": True, "user": data}), 200


# ── PATCH /admin/users/<id>/role ───────────────────────────────────────────────

@admin_bp.route("/users/<int:user_id>/role", methods=["PATCH"])
@jwt_required()
@require_role(Role.ADMIN)
@require_permission(Permission.MANAGE_ROLES)
@inject_user
def change_role(user_id: int, current_user: User):
    """
    Promote or demote a user.
    Body: { "role": "normal_user" | "operational_user" | "admin" }
    An admin cannot demote themselves.
    """
    data     = request.get_json(silent=True) or {}
    new_role = data.get("role", "").strip()

    if not Role.is_valid(new_role):
        return jsonify({
            "success": False,
            "message": f"Invalid role. Choose from: {', '.join(sorted(Role.ALL))}",
        }), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404

    if user.id == current_user.id:
        return jsonify({"success": False, "message": "You cannot change your own role."}), 403

    old_role = user.role
    user.role = new_role
    db.session.commit()

    logger.info("Admin %s changed user %s role: %s → %s",
                current_user.username, user.username, old_role, new_role)

    return jsonify({
        "success": True,
        "message": f"Role updated: {old_role} → {new_role}",
        "user": user.to_dict(),
    }), 200


# ── PATCH /admin/users/<id>/deactivate ────────────────────────────────────────

@admin_bp.route("/users/<int:user_id>/deactivate", methods=["PATCH"])
@jwt_required()
@require_role(Role.ADMIN)
@inject_user
def deactivate_user(user_id: int, current_user: User):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
    if user.id == current_user.id:
        return jsonify({"success": False, "message": "Cannot deactivate yourself."}), 403

    user.is_active = False
    db.session.commit()
    logger.info("Admin %s deactivated user %s", current_user.username, user.username)
    return jsonify({"success": True, "message": f"User '{user.username}' deactivated."}), 200


# ── PATCH /admin/users/<id>/activate ─────────────────────────────────────────

@admin_bp.route("/users/<int:user_id>/activate", methods=["PATCH"])
@jwt_required()
@require_role(Role.ADMIN)
@inject_user
def activate_user(user_id: int, current_user: User):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404

    user.is_active = True
    db.session.commit()
    logger.info("Admin %s activated user %s", current_user.username, user.username)
    return jsonify({"success": True, "message": f"User '{user.username}' activated."}), 200


# ── DELETE /admin/users/<id> ───────────────────────────────────────────────────

@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
@jwt_required()
@require_role(Role.ADMIN)
@inject_user
def delete_user(user_id: int, current_user: User):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
    if user.id == current_user.id:
        return jsonify({"success": False, "message": "Cannot delete yourself."}), 403

    username = user.username
    db.session.delete(user)   # cascade deletes plate_records
    db.session.commit()
    logger.info("Admin %s deleted user %s", current_user.username, username)
    return jsonify({"success": True, "message": f"User '{username}' and all their records deleted."}), 200


# ── GET /admin/dashboard ───────────────────────────────────────────────────────

@admin_bp.route("/dashboard", methods=["GET"])
@jwt_required()
@require_role(Role.ADMIN)
@require_permission(Permission.SYSTEM_STATS)
@inject_user
def dashboard(current_user: User):
    """Comprehensive system statistics for the admin dashboard."""
    total_records     = PlateRecord.query.count()
    successful        = PlateRecord.query.filter(
        PlateRecord.plate_text.isnot(None), PlateRecord.plate_text != ""
    ).count()

    users_by_role = {
        r: User.query.filter_by(role=r).count()
        for r in [Role.NORMAL, Role.OPERATIONAL, Role.ADMIN]
    }

    # Top 5 most scanned plates
    from sqlalchemy import func
    top_plates = (
        db.session.query(PlateRecord.plate_text, func.count(PlateRecord.id).label("hits"))
        .filter(PlateRecord.plate_text.isnot(None), PlateRecord.plate_text != "")
        .group_by(PlateRecord.plate_text)
        .order_by(func.count(PlateRecord.id).desc())
        .limit(5).all()
    )

    # Top 5 most active users
    top_users = (
        db.session.query(User.username, User.role, func.count(PlateRecord.id).label("scans"))
        .join(PlateRecord, PlateRecord.user_email == User.email)
        .group_by(User.id)
        .order_by(func.count(PlateRecord.id).desc())
        .limit(5).all()
    )

    return jsonify({
        "success": True,
        "dashboard": {
            "total_detections":      total_records,
            "successful_detections": successful,
            "failed_detections":     total_records - successful,
            "success_rate":          round(successful / total_records * 100, 1) if total_records else 0,
            "total_users":           sum(users_by_role.values()),
            "active_users":          User.query.filter_by(is_active=True).count(),
            "users_by_role":         users_by_role,
            "top_plates":            [{"plate": p, "hits": h} for p, h in top_plates],
            "top_users":             [{"username": u, "role": r, "scans": s} for u, r, s in top_users],
        },
    }), 200