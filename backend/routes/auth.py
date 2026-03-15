import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token

from models import db, User, Role

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not all([username, email, password]):
        return jsonify({"success": False, "message": "Missing required fields."}), 400

    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"success": False, "message": "Username or email already exists."}), 409

    try:
        user = User(username=username, email=email, role=Role.NORMAL)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        access_token = create_access_token(identity=str(user.id))
        return jsonify({
            "success": True,
            "message": "User registered successfully.",
            "access_token": access_token,
            "user": user.to_dict()
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.exception("Registration error")
        return jsonify({"success": False, "message": "Failed to register user."}), 500

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    ident = data.get("username", "").strip()  # can be username or email
    password = data.get("password", "")

    if not ident or not password:
        return jsonify({"success": False, "message": "Missing credentials."}), 400

    user = User.query.filter((User.username == ident) | (User.email == ident)).first()

    if not user or not user.check_password(password):
        return jsonify({"success": False, "message": "Invalid username/email or password."}), 401

    if not user.is_active:
        return jsonify({"success": False, "message": "Account is deactivated."}), 403

    access_token = create_access_token(identity=str(user.id))
    return jsonify({
        "success": True,
        "message": "Logged in successfully.",
        "access_token": access_token,
        "user": user.to_dict()
    }), 200
