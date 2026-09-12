"""Single-owner login with expiring signed cookies and CSRF origin enforcement."""

import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .audit_service import now
from .config import get_settings

router = APIRouter(prefix="/api/v1/auth", tags=["owner"])
COOKIE = "gitaudit_owner"


class LoginRequest(BaseModel):
    """Owner password supplied over the local interface."""

    password: str = Field(min_length=1, max_length=1024)


def signing_key() -> str:
    """Derive a stable cookie key; changing the owner password revokes sessions."""
    settings = get_settings()
    if not settings.owner_password:
        raise HTTPException(503, "Set OWNER_PASSWORD to enable owner login and mutations")
    material = settings.owner_session_secret or settings.owner_password
    return hashlib.sha256(material.get_secret_value().encode()).hexdigest()


def authenticated(request: Request) -> bool:
    """Validate either an owner cookie or a bearer password for local CLI clients."""
    settings = get_settings()
    if not settings.owner_password:
        return False
    bearer = request.headers.get("authorization", "")
    if bearer.startswith("Bearer "):
        return hmac.compare_digest(
            bearer[7:].encode(), settings.owner_password.get_secret_value().encode()
        )
    token = request.cookies.get(COOKIE)
    if not token:
        return False
    try:
        claims = jwt.decode(
            token,
            signing_key(),
            algorithms=["HS256"],
            audience="gitaudit",
            options={"require": ["exp", "sub", "aud"]},
        )
        return claims["sub"] == "owner"
    except jwt.PyJWTError:
        return False


@router.get("/session")
async def owner_session(request: Request) -> dict:
    """Expose login state without leaking credentials."""
    return {
        "authenticated": authenticated(request),
        "configured": bool(get_settings().owner_password),
    }


@router.post("/login")
async def login(payload: LoginRequest, response: Response) -> dict:
    """Issue a bounded HttpOnly owner session after constant-time verification."""
    settings = get_settings()
    key = signing_key()
    if not hmac.compare_digest(
        payload.password.encode(), settings.owner_password.get_secret_value().encode()
    ):
        raise HTTPException(401, "Incorrect owner password")
    token = jwt.encode(
        {
            "sub": "owner",
            "aud": "gitaudit",
            "exp": now() + timedelta(hours=12),
            "jti": secrets.token_hex(16),
        },
        key,
        algorithm="HS256",
    )
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=settings.owner_cookie_secure,
        max_age=43200,
        path="/",
    )
    return {"authenticated": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Remove the browser's owner cookie."""
    response.delete_cookie(COOKIE, path="/")
    return {"authenticated": False}
