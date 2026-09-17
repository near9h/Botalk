"""Auth API: login, logout, register (only when user table empty), me."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    clear_session_cookie,
    get_current_user,
    hash_password,
    make_token,
    set_session_cookie,
    verify_password,
)
from app.config import get_settings
from app.db.models import User
from app.db.session import get_session

router = APIRouter()
settings = get_settings()


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=256)
    password: str = Field(min_length=8, max_length=256)


class MeOut(BaseModel):
    id: int
    username: str
    email: str | None


@router.post("/login")
async def login(
    body: LoginBody,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeOut:
    result = await session.execute(
        select(User).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        # Same error for "no such user" and "wrong password" — avoid
        # user-enumeration leaks.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = make_token(user.id)
    set_session_cookie(response, token)
    return MeOut(id=user.id, username=user.username, email=user.email)


@router.post("/logout")
async def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/register")
async def register(
    body: RegisterBody,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeOut:
    """Only allowed when the users table is empty (i.e. first-run bootstrap)."""
    result = await session.execute(select(sa_func.count(User.id)))
    count = result.scalar_one() or 0
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="已有用户存在,请直接登录或联系管理员",
        )
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    set_session_cookie(response, make_token(user.id))
    return MeOut(id=user.id, username=user.username, email=user.email)


@router.get("/me")
async def me(
    user: Annotated[User | None, Depends(get_current_user)],
) -> MeOut | None:
    if user is None:
        return None
    return MeOut(id=user.id, username=user.username, email=user.email)