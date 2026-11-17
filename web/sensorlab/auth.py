import hmac
import secrets
from functools import wraps

from flask import abort, current_app, request, session


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf(value):
    if not isinstance(value, str) or not value.isascii() or not value or not hmac.compare_digest(value, session.get("csrf", "")):
        abort(403, description="Invalid CSRF token")


def token_role(token):
    if not isinstance(token, str) or not token.isascii() or not token:
        return None
    for role in ("admin", "viewer", "device"):
        expected = current_app.config.get(role.upper() + "_TOKEN", "")
        if expected and hmac.compare_digest(token, expected):
            return role
    return None


def require_roles(*roles):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            header = request.headers.get("Authorization")
            if header is not None:
                role = token_role(header[7:]) if header.startswith("Bearer ") else None
            else:
                role = session.get("role")
                if role and request.method not in ("GET", "HEAD", "OPTIONS"):
                    check_csrf(request.headers.get("X-CSRF-Token"))
            if not role:
                abort(401, description="Authentication required")
            if role not in roles:
                abort(403, description="Insufficient access")
            return function(*args, **kwargs)
        return wrapped
    return decorate
