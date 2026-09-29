"""Auth API router: login, refresh, logout, profile."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from src.auth.rbac import AuthenticatedUser, get_current_user
from src.auth.service import authenticate_user, create_session
from src.config import settings
from src.db.session import get_db
from src.db.models import Tenant
from sqlalchemy import select
from uuid import UUID

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    user_id: str
    tenant_id: str
    username: str
    email: str
    role: str


@router.post("/login", response_model=TokenResponse)
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    # Resolve tenant: use default for now; multi-tenant via subdomain/header later
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.slug == settings.ADMIN_DEFAULT_TENANT)
    )
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Platform not initialized")

    user = await authenticate_user(db, tenant.id, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await create_session(db, user, channel="web")
    await db.commit()

    access_token = create_access_token(user.tenant_id, user.id, user.username, user.role.value)
    refresh_token = create_refresh_token(user.tenant_id, user.id)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.ENVIRONMENT != "development",
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/auth/refresh",
    )
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    refresh_token: str = Cookie(None),
    db: AsyncSession = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Wrong token type")
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    from src.db.models import User
    user_id = UUID(payload["sub"])
    tenant_id = UUID(payload["tenant"])
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token(user.tenant_id, user.id, user.username, user.role.value)
    return TokenResponse(access_token=access_token)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token", path="/auth/refresh")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserProfile)
async def get_me(current_user: AuthenticatedUser = Depends(get_current_user)):
    return UserProfile(
        user_id=str(current_user.user_id),
        tenant_id=str(current_user.tenant_id),
        username=current_user.username,
        email=current_user.email,
        role=current_user.role,
    )
