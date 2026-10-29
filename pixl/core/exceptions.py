from typing import Any, Dict, Optional
from fastapi import HTTPException, status


class PixlException(HTTPException):
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str = "ERROR",
        headers: Optional[Dict[str, str]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.extra = extra or {}


class AuthenticationError(PixlException):
    def __init__(self, detail: str = "Authentication required or invalid credentials"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            code="UNAUTHENTICATED",
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenError(PixlException):
    def __init__(self, detail: str = "Access forbidden to requested resource or tenant"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            code="FORBIDDEN",
        )


class NotFoundError(PixlException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
            code="NOT_FOUND",
        )


class ConflictError(PixlException):
    def __init__(self, detail: str = "Resource state conflict", extra: Optional[Dict[str, Any]] = None):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            code="CONFLICT",
            extra=extra,
        )


class UnprocessableError(PixlException):
    def __init__(self, detail: str = "Unprocessable entity"):
        super().__init__(
            status_code=422,
            detail=detail,
            code="VALIDATION_FAILED",
        )

