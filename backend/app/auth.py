"""Auth helpers — JWT cookies + bcrypt password hashing.

Single-user self-hosted mode is the default: on first request, if the User
table is empty, we seed it from `AUTH_BOOTSTRAP_USER` / `AUTH_BOOTSTRAP_PASSWORD`.
Set `AUTH_DISABLED=true` in .env to bypass auth entirely (useful for trusted
LAN deployments).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User
from app.db.session import get_session

settings = get_settings()
COOKIE_NAME = "botgroup_session"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def make_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "iat": datetime.now(tz=timezone.utc),
        "exp": datetime.now(tz=timezone.utc)
        + timedelta(hours=settings.auth_token_ttl_hours),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.auth_secret, algorithms=["HS256"])
        return int(payload["sub"])
    except Exception:  # noqa: BLE001
        return None


async def ensure_bootstrap_user(session: AsyncSession) -> None:
    """If no users exist, create one from env defaults. Called on app boot."""
    from sqlalchemy import func as sa_func

    result = await session.execute(select(sa_func.count(User.id)))
    count = result.scalar_one() or 0
    if count > 0:
        return
    user = User(
        username=settings.auth_bootstrap_user,
        email=f"{settings.auth_bootstrap_user}@local",
        password_hash=hash_password(settings.auth_bootstrap_password),
    )
    session.add(user)
    await session.commit()


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    botgroup_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> User | None:
    """Resolve the request's user from the session cookie, or None."""
    if settings.auth_disabled:
        # auth off — return the first user (or None if the table is empty).
        result = await session.execute(select(User).order_by(User.id).limit(1))
        return result.scalar_one_or_none()
    if not botgroup_session:
        return None
    uid = decode_token(botgroup_session)
    if uid is None:
        return None
    return await session.get(User, uid)


async def require_user(
    user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
        )
    return user


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.auth_token_ttl_hours * 3600,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")