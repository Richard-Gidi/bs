"""Users, approvals and conversion history.

Storage is whatever DATABASE_URL points to (Postgres in production). Without it the app
falls back to a local SQLite file, which is fine for testing but is wiped on every
redeploy/restart on Render and Streamlit Cloud.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        LargeBinary, String, Text, create_engine, select)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    approved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)
    approved_at = Column(DateTime)


class Conversion(Base):
    __tablename__ = "conversions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    bank = Column(String(64), nullable=False)
    source_files = Column(Text, nullable=False)
    rows = Column(Integer, nullable=False)
    total_credits = Column(Float)
    total_debits = Column(Float)
    opening = Column(Float)
    closing = Column(Float)
    excel_name = Column(String(255), nullable=False)
    excel_bytes = Column(LargeBinary, nullable=False)


# ---------- passwords (PBKDF2-SHA256, stdlib only) ----------
_ITER = 310_000


def hash_password(password):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER)
    return f"pbkdf2_sha256${_ITER}${salt}${dk.hex()}"


def verify_password(password, stored):
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


# ---------- engine ----------
def make_session_factory(url=None):
    url = url or os.environ.get("DATABASE_URL") or "sqlite:///bs_local.db"
    if url.startswith("postgres://"):  # Render/Heroku style
        url = "postgresql://" + url[len("postgres://"):]
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False), url.startswith("sqlite")


# ---------- user operations ----------
def ensure_admin(Session, username, password):
    """Create/refresh the admin account from configuration (ADMIN_USERNAME/ADMIN_PASSWORD)."""
    username = username.strip().lower()
    with Session() as s:
        u = s.scalar(select(User).where(User.username == username))
        if u is None:
            u = User(username=username, password_hash=hash_password(password))
            s.add(u)
        elif not verify_password(password, u.password_hash):
            u.password_hash = hash_password(password)
        u.is_admin, u.approved = True, True
        u.approved_at = u.approved_at or _now()
        s.commit()


def register(Session, username, password):
    username = username.strip().lower()
    with Session() as s:
        if s.scalar(select(User).where(User.username == username)):
            return False, "That username is already taken."
        s.add(User(username=username, password_hash=hash_password(password)))
        s.commit()
    return True, "Account created. You can log in once the administrator approves it."


def authenticate(Session, username, password):
    """Returns (user, message). user is None unless the login is allowed."""
    username = username.strip().lower()
    with Session() as s:
        u = s.scalar(select(User).where(User.username == username))
    if u is None or not verify_password(password, u.password_hash):
        return None, "Incorrect username or password."
    if not u.approved:
        return None, "Your account is waiting for administrator approval."
    return u, ""


def pending_users(Session):
    with Session() as s:
        return list(s.scalars(select(User).where(User.approved.is_(False)).order_by(User.created_at)))


def approved_users(Session):
    with Session() as s:
        return list(s.scalars(select(User).where(User.approved.is_(True)).order_by(User.username)))


def approve(Session, user_id):
    with Session() as s:
        u = s.get(User, user_id)
        if u:
            u.approved, u.approved_at = True, _now()
            s.commit()


def reject(Session, user_id):
    with Session() as s:
        u = s.get(User, user_id)
        if u and not u.approved:
            s.delete(u)
            s.commit()


# ---------- history ----------
def save_conversion(Session, **fields):
    with Session() as s:
        s.add(Conversion(**fields))
        s.commit()


def list_conversions(Session, user_id=None):
    """Metadata only (no file bytes). user_id=None returns everyone's (admin view)."""
    cols = [Conversion.id, Conversion.created_at, Conversion.bank, Conversion.source_files,
            Conversion.rows, Conversion.total_credits, Conversion.total_debits,
            Conversion.opening, Conversion.closing, Conversion.excel_name, User.username]
    q = select(*cols).join(User, User.id == Conversion.user_id).order_by(Conversion.created_at.desc())
    if user_id is not None:
        q = q.where(Conversion.user_id == user_id)
    with Session() as s:
        return [dict(r._mapping) for r in s.execute(q)]


def get_conversion_file(Session, conv_id, user_id=None):
    with Session() as s:
        c = s.get(Conversion, conv_id)
        if c is None or (user_id is not None and c.user_id != user_id):
            return None
        return c.excel_name, c.excel_bytes


def delete_conversion(Session, conv_id, user_id=None):
    with Session() as s:
        c = s.get(Conversion, conv_id)
        if c and (user_id is None or c.user_id == user_id):
            s.delete(c)
            s.commit()
