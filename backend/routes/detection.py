"""
routes/detection.py – Detection Blueprint with RBAC
POST /detect                – JWT + Permission.DETECT
GET  /history               – JWT; own records (all roles), team (operational+), all (admin)
GET  /history/<id>          – JWT; own or admin
DELETE /history/<id>        – JWT + Permission.DELETE_ANY (admin only)
GET  /export/csv            – JWT + Permission.EXPORT_CSV (operational+)
GET  /stats                 – JWT; personal stats (all) or system stats (admin)
GET  /image/<path>          – JWT
"""

import os
import io
import csv
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app, send_file, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from sqlalchemy import or_

from models import db, User, PlateRecord, Role, Permission
from middleware.rbac import require_permission, require_active, inject_user
from services.anpr_service import run_detection

logger = logging.getLogger(__name__)
detect_bp = Blueprint("detection", __name__)


def _allowed_file(filename: str) -> bool:
    allowed = current_app.config.get("ALLOWED_EXTENSIONS", {"png", "jpg", "jpeg"})
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


# ── POST /detect ───────────────────────────────────────────────────────────────

@detect_bp.route("/detect", methods=["POST"])
@jwt_required()
@require_active
@require_permission(Permission.DETECT)
@inject_user
def detect(current_user: User):
    """Upload image → run ANPR → persist result."""

    # Per-role upload size check
    content_length = request.content_length or 0
    if content_length > current_user.upload_limit_bytes:
        limit_mb = current_user.upload_limit_bytes // (1024 * 1024)
        return jsonify({
            "success": False,
            "message": f"File too large. Your role ({current_user.role}) allows up to {limit_mb} MB.",
        }), 413

    if "image" not in request.files:
        return jsonify({"success": False, "message": "No image file provided."}), 400

    file = request.files["image"]
    if not file.filename or not _allowed_file(file.filename):
        return jsonify({"success": False, "message": "Unsupported file type."}), 400

    image_bytes = file.read()
    if not image_bytes:
        return jsonify({"success": False, "message": "Empty image."}), 400

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    model_path    = current_app.config["MODEL_PATH"]

    try:
        result = run_detection(
            image_bytes=image_bytes,
            upload_folder=upload_folder,
            model_path=model_path,
            original_filename=secure_filename(file.filename),
        )
    except RuntimeError as exc:
        print(f"[ERROR] run_detection raised RuntimeError: {exc}")
        return jsonify({"success": False, "message": str(exc)}), 500

    try:
        logger.info("Attempting to save record: user_email=%s, plate=%s", 
                    current_user.email, result.get("plate_text"))
        
        record = PlateRecord(
            user_email      = current_user.email,
            image_path      = result.get("annotated_path") or "",
            plate_text      = result.get("plate_text"),
            yolo_confidence = result.get("yolo_conf"),
            ocr_confidence  = result.get("ocr_conf"),
            timestamp       = datetime.utcnow(),
        )
        db.session.add(record)
        db.session.commit()
        logger.info("Record saved successfully. ID: %s", record.id)
    except Exception as e:
        db.session.rollback()
        logger.error("DB insert error after detection: %s", str(e))
        return jsonify({"success": False, "message": f"Detection OK but DB save failed: {str(e)}"}), 500

    if not result["success"]:
        return jsonify({
            "success": False,
            "message": result.get("error", "No plate detected."),
            "record": record.to_dict(),
        }), 422

    return jsonify({
        "success": True,
        "message": "Number plate detected.",
        "result": {
            "plate_text":      result["plate_text"],
            "yolo_confidence": round(result["yolo_conf"], 4),
            "ocr_confidence":  round(result["ocr_conf"],  4),
            "image_path":      result["annotated_path"],
            "record_id":       record.id,
            "timestamp":       record.timestamp.isoformat(),
        },
    }), 200


# ── GET /history ───────────────────────────────────────────────────────────────

@detect_bp.route("/history", methods=["GET"])
@jwt_required()
@require_active
@inject_user
def history(current_user: User):
    """
    normal_user      → own records only
    operational_user → own + other operational users' records (team view)
    admin            → all records
    """
    page     = max(1, request.args.get("page",     1,  type=int))
    per_page = min(100, request.args.get("per_page", 20, type=int))

    query = PlateRecord.query

    if current_user.is_admin():
        # No filter — see everything
        pass
    elif current_user.has_permission(Permission.VIEW_TEAM):
        # Operational: own records + other operational/normal users
        # (exclude admin records — admins aren't "team members")
        team_emails = db.session.query(User.email).filter(
            User.role.in_([Role.NORMAL, Role.OPERATIONAL]),
            User.is_active == True,
        ).subquery()
        query = query.filter(PlateRecord.user_email.in_(team_emails))
    else:
        # Normal user: only own records
        query = query.filter_by(user_email=current_user.email)

    pagination = (
        query.order_by(PlateRecord.timestamp.desc())
             .paginate(page=page, per_page=per_page, error_out=False)
    )

    return jsonify({
        "success":    True,
        "scope":      "all" if current_user.is_admin() else
                      ("team" if current_user.has_permission(Permission.VIEW_TEAM) else "own"),
        "records":    [r.to_dict() for r in pagination.items],
        "pagination": {
            "page":     pagination.page,
            "per_page": pagination.per_page,
            "total":    pagination.total,
            "pages":    pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        },
    }), 200


# ── GET /history/<id> ──────────────────────────────────────────────────────────

@detect_bp.route("/history/<int:record_id>", methods=["GET"])
@jwt_required()
@require_active
@inject_user
def history_detail(record_id: int, current_user: User):
    record = PlateRecord.query.get(record_id)
    if not record:
        return jsonify({"success": False, "message": "Record not found."}), 404

    # Admins see all; others only their own (or team if operational)
    if not current_user.is_admin() and record.user_email != current_user.email:
        if not (current_user.has_permission(Permission.VIEW_TEAM)
                and record.owner.role in (Role.NORMAL, Role.OPERATIONAL)):
            return jsonify({"success": False, "message": "Access denied."}), 403

    return jsonify({"success": True, "record": record.to_dict()}), 200


# ── DELETE /history/<id> ───────────────────────────────────────────────────────

@detect_bp.route("/history/<int:record_id>", methods=["DELETE"])
@jwt_required()
@require_active
@require_permission(Permission.DELETE_ANY)
@inject_user
def delete_record(record_id: int, current_user: User):
    """Admin only — permanently delete any record."""
    record = PlateRecord.query.get(record_id)
    if not record:
        return jsonify({"success": False, "message": "Record not found."}), 404

    # Optionally delete the image file too
    try:
        if record.image_path and os.path.isfile(record.image_path):
            os.remove(record.image_path)
    except OSError:
        pass

    db.session.delete(record)
    db.session.commit()
    logger.info("Admin %s deleted record #%d", current_user.username, record_id)
    return jsonify({"success": True, "message": f"Record #{record_id} deleted."}), 200


# ── GET /export/csv ────────────────────────────────────────────────────────────

@detect_bp.route("/export/csv", methods=["GET"])
@jwt_required()
@require_active
@require_permission(Permission.EXPORT_CSV)
@inject_user
def export_csv(current_user: User):
    """
    Export detection history as CSV.
    Operational users export their team's records.
    Admins export all records.
    """
    query = PlateRecord.query

    if current_user.is_admin():
        records = query.order_by(PlateRecord.timestamp.desc()).all()
    else:
        team_emails = db.session.query(User.email).filter(
            User.role.in_([Role.NORMAL, Role.OPERATIONAL]),
            User.is_active == True,
        ).subquery()
        records = (query.filter(PlateRecord.user_email.in_(team_emails))
                        .order_by(PlateRecord.timestamp.desc()).all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "user_email", "username", "plate_text",
                     "yolo_confidence", "ocr_confidence", "timestamp", "image_path"])
    for r in records:
        writer.writerow([
            r.id, r.user_email,
            r.owner.username if r.owner else "",
            r.plate_text or "",
            f"{r.yolo_confidence:.4f}" if r.yolo_confidence is not None else "",
            f"{r.ocr_confidence:.4f}"  if r.ocr_confidence  is not None else "",
            r.timestamp.isoformat(),
            r.image_path,
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=anpr_history.csv"},
    )


# ── GET /stats ─────────────────────────────────────────────────────────────────

@detect_bp.route("/stats", methods=["GET"])
@jwt_required()
@require_active
@inject_user
def stats(current_user: User):
    """
    normal_user / operational → personal stats
    admin                     → global system stats
    """
    if current_user.has_permission(Permission.SYSTEM_STATS):
        total      = PlateRecord.query.count()
        successful = PlateRecord.query.filter(
            PlateRecord.plate_text.isnot(None),
            PlateRecord.plate_text != "",
        ).count()
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()

        role_counts = {}
        for role in [Role.NORMAL, Role.OPERATIONAL, Role.ADMIN]:
            role_counts[role] = User.query.filter_by(role=role).count()

        return jsonify({
            "success": True,
            "scope":   "system",
            "stats": {
                "total_detections":       total,
                "successful_detections":  successful,
                "failed_detections":      total - successful,
                "total_users":            total_users,
                "active_users":           active_users,
                "users_by_role":          role_counts,
            },
        }), 200
    else:
        total = PlateRecord.query.filter_by(user_email=current_user.email).count()
        successful = PlateRecord.query.filter(
            PlateRecord.user_email == current_user.email,
            PlateRecord.plate_text.isnot(None),
            PlateRecord.plate_text != "",
        ).count()
        return jsonify({
            "success": True,
            "scope":   "personal",
            "stats": {
                "total_detections":      total,
                "successful_detections": successful,
                "failed_detections":     total - successful,
            },
        }), 200


# ── GET /image/<path> ──────────────────────────────────────────────────────────

@detect_bp.route("/image/<path:filename>", methods=["GET"])
@jwt_required()
@require_active
def serve_image(filename: str):
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    safe_path = os.path.join(upload_folder, os.path.basename(filename))
    if not os.path.isfile(safe_path):
        return jsonify({"success": False, "message": "Image not found."}), 404
    return send_file(safe_path, mimetype="image/jpeg")