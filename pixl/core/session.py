from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from fastapi import Response, Request

from pixl.core.config import settings
from pixl.core.security import generate_secure_token

# Development-only memory store; production uses the shared Redis adapter.
_session_store: Dict[str, Dict[str, Any]] = {}


class SessionManager:
    @staticmethod
    def get_cookie_name_for_audience(audience: str) -> str:
        names = {
            "pixl:audience:master": "__Host-PIXL-Master-Session",
            "pixl:audience:agency": "__Host-PIXL-Agency-Session",
            "pixl:audience:brand": "__Host-PIXL-Brand-Session",
        }
        name = names.get(audience, settings.SESSION_COOKIE_NAME)
        # Browsers reject __Host- cookies without Secure. Use an unprefixed
        # development cookie on HTTP, preserving the host prefix on HTTPS.
        if settings.ENVIRONMENT != "production" and not settings.SESSION_COOKIE_SECURE:
            name = name.removeprefix("__Host-")
        return name

    @classmethod
    def create_session(
        cls,
        user_id: str,
        role: str,
        audience: str,
        organization_id: Optional[str] = None,
        brand_id: Optional[str] = None
    ) -> str:
        session_token = generate_secure_token(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.SESSION_MAX_AGE_SECONDS)
        
        data = {
            "session_token": session_token,
            "user_id": user_id,
            "role": role,
            "audience": audience,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "created_at": datetime.now(timezone.utc),
            "expires_at": expires_at,
        }
        if settings.SESSION_BACKEND == "redis":
            from pixl.core import session_store
            session_store.save(session_token, data)
        else:
            now = datetime.now(timezone.utc)
            for token in list(_session_store):
                if _session_store[token]["expires_at"] <= now:
                    del _session_store[token]
            _session_store[session_token] = data
        return session_token

    @classmethod
    def get_session(cls, session_token: str) -> Optional[Dict[str, Any]]:
        if not session_token:
            return None
        if settings.SESSION_BACKEND == "redis":
            from pixl.core import session_store
            return session_store.get(session_token)
        if session_token not in _session_store:
            return None
        
        session = _session_store[session_token]
        expires_at = session.get("expires_at")
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and datetime.now(timezone.utc) > expires_at:
            del _session_store[session_token]
            return None
        
        return session

    @classmethod
    def revoke_session(cls, session_token: str) -> bool:
        if settings.SESSION_BACKEND == "redis":
            from pixl.core import session_store
            return session_store.revoke(session_token)
        if session_token in _session_store:
            del _session_store[session_token]
            return True
        return False

    @classmethod
    def revoke_all_user_sessions(cls, user_id: str) -> int:
        if settings.SESSION_BACKEND == "redis":
            from pixl.core import session_store
            return session_store.revoke_user(user_id)
        revoked_count = 0
        to_delete = [
            token for token, sess in _session_store.items()
            if sess.get("user_id") == user_id
        ]
        for token in to_delete:
            del _session_store[token]
            revoked_count += 1
        return revoked_count

    @classmethod
    def attach_session_cookie(
        cls,
        response: Response,
        session_token: str,
        audience: str
    ) -> None:
        cookie_name = cls.get_cookie_name_for_audience(audience)
        is_secure = settings.ENVIRONMENT == "production" or settings.SESSION_COOKIE_SECURE
        response.set_cookie(
            key=cookie_name,
            value=session_token,
            max_age=settings.SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=is_secure,
            samesite="lax",
            path="/"
        )

    @classmethod
    def clear_session_cookie(
        cls,
        response: Response,
        audience: str
    ) -> None:
        cookie_name = cls.get_cookie_name_for_audience(audience)
        response.delete_cookie(
            key=cookie_name,
            path="/",
            secure=settings.ENVIRONMENT == "production" or settings.SESSION_COOKIE_SECURE,
            httponly=True,
            samesite="lax",
        )

    @classmethod
    def extract_session_token(cls, request: Request, audience: Optional[str] = None) -> Optional[str]:
        # Explicit API credentials must not be shadowed by another panel cookie.
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:].strip()

        # 1. Check audience-specific cookie
        if audience:
            cookie_name = cls.get_cookie_name_for_audience(audience)
            if cookie_name in request.cookies:
                return request.cookies[cookie_name]

        # 2. Check general cookies
        for name in [
            cls.get_cookie_name_for_audience("pixl:audience:master"),
            cls.get_cookie_name_for_audience("pixl:audience:agency"),
            cls.get_cookie_name_for_audience("pixl:audience:brand"),
            "__Host-PIXL-Master-Session",
            "__Host-PIXL-Agency-Session",
            "__Host-PIXL-Brand-Session",
            settings.SESSION_COOKIE_NAME,
            "pixl_session"
        ]:
            if name in request.cookies:
                return request.cookies[name]

        return None
