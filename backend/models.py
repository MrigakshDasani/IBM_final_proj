"""
models.py – SQLAlchemy ORM models with Role-Based Access Control (RBAC)
Roles: normal_user | operational_user | admin
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ── Role constants ─────────────────────────────────────────────────────────────

class Role:
    NORMAL       = "normal_user"
    OPERATIONAL  = "operational_user"
    ADMIN        = "admin"
    ALL          = {NORMAL, OPERATIONAL, ADMIN}
    HIERARCHY    = {NORMAL: 0, OPERATIONAL: 1, ADMIN: 2}

    @classmethod
    def is_valid(cls, role: str) -> bool:
        return role in cls.ALL

    @classmethod
    def rank(cls, role: str) -> int:
        return cls.HIERARCHY.get(role, -1)


# ── Permission constants ───────────────────────────────────────────────────────

class Permission:
    DETECT       = "detect"        # run ANPR on image
    VIEW_OWN     = "view_own"      # own history
    EXPORT_CSV   = "export_csv"    # download CSV of history
    HIGH_UPLOAD  = "high_upload"   # 64 MB limit
    VIEW_TEAM    = "view_team"     # see operational-tier users' records
    VIEW_ALL     = "view_all"      # every user's records
    DELETE_ANY   = "delete_any"    # hard-delete any record
    MANAGE_ROLES = "manage_roles"  # promote / demote users
    SYSTEM_STATS = "system_stats"  # global dashboard


ROLE_PERMISSIONS: dict = {
    Role.NORMAL: {
        Permission.DETECT,
        Permission.VIEW_OWN,
    },
    Role.OPERATIONAL: {
        Permission.DETECT,
        Permission.VIEW_OWN,
        Permission.EXPORT_CSV,
        Permission.HIGH_UPLOAD,
        Permission.VIEW_TEAM,
    },
    Role.ADMIN: {
        Permission.DETECT,
        Permission.VIEW_OWN,
        Permission.EXPORT_CSV,
        Permission.HIGH_UPLOAD,
        Permission.VIEW_TEAM,
        Permission.VIEW_ALL,
        Permission.DELETE_ANY,
        Permission.MANAGE_ROLES,
        Permission.SYSTEM_STATS,
    },
}


# ── Models ─────────────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    username      = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email         = db.Column(db.String(120),unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256),nullable=False)
    role          = db.Column(db.String(30), nullable=False, default=Role.NORMAL, index=True)
    is_active     = db.Column(db.Boolean,    nullable=False, default=True)
    created_at    = db.Column(db.DateTime,   default=datetime.utcnow, nullable=False)
    updated_at    = db.Column(db.DateTime,   default=datetime.utcnow,
                              onupdate=datetime.utcnow, nullable=False)

    plate_records = db.relationship(
        "PlateRecord",
        primaryjoin="User.email == PlateRecord.user_email",
        foreign_keys="PlateRecord.user_email",
        backref="owner",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def set_password(self, plain: str) -> None:
        self.password_hash = generate_password_hash(plain)

    def check_password(self, plain: str) -> bool:
        return check_password_hash(self.password_hash, plain)

    def has_permission(self, perm: str) -> bool:
        return perm in ROLE_PERMISSIONS.get(self.role, set())

    def has_role(self, *roles) -> bool:
        return self.role in roles

    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    def is_operational_or_above(self) -> bool:
        return self.role in (Role.OPERATIONAL, Role.ADMIN)

    @property
    def upload_limit_bytes(self) -> int:
        return 64 * 1024 * 1024 if self.has_permission(Permission.HIGH_UPLOAD) else 16 * 1024 * 1024

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "username":    self.username,
            "email":       self.email,
            "role":        self.role,
            "is_active":   self.is_active,
            "permissions": sorted(ROLE_PERMISSIONS.get(self.role, [])),
            "created_at":  self.created_at.isoformat(),
            "updated_at":  self.updated_at.isoformat(),
        }

    def __repr__(self):
        return f"<User {self.username} [{self.role}]>"


class PlateRecord(db.Model):
    __tablename__ = "plate_records"

    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_email       = db.Column(db.String(120),
                                 db.ForeignKey("users.email", ondelete="CASCADE"),
                                 nullable=False, index=True)
    image_path       = db.Column(db.String(512), nullable=False)
    plate_text       = db.Column(db.String(100), nullable=True)
    yolo_confidence  = db.Column(db.Float, nullable=True)
    ocr_confidence   = db.Column(db.Float, nullable=True)
    timestamp        = db.Column(db.DateTime, default=datetime.utcnow,
                                 nullable=False, index=True)

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "user_email":      self.user_email,
            "username":        self.owner.username if self.owner else None,
            "image_path":      self.image_path,
            "plate_text":      self.plate_text,
            "yolo_confidence": round(self.yolo_confidence, 4) if self.yolo_confidence is not None else None,
            "ocr_confidence":  round(self.ocr_confidence,  4) if self.ocr_confidence  is not None else None,
            "timestamp":       self.timestamp.isoformat(),
        }

    def __repr__(self):
        return f"<PlateRecord {self.plate_text} user={self.user_email}>"