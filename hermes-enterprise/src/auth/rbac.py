"""RBAC FastAPI security dependencies for Hermes Enterprise."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from src.auth.jwt import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class AuthenticatedUser:
    tenant_id: UUID
    user_id: UUID
    username: str
    email: str
    role: Literal["admin", "member"]
    is_active: bool


def get_current_user(token: str = Depends(oauth2_scheme)) -> AuthenticatedUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id = payload.get("sub")
        tenant_id = payload.get("tenant")
        username = payload.get("username")
        role = payload.get("role")
        if not all([user_id, tenant_id, username, role]):
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    return AuthenticatedUser(
        tenant_id=UUID(tenant_id),
        user_id=UUID(user_id),
        username=username,
        email="",  # populated from DB when needed
        role=role,
        is_active=True,
    )


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )
    return user
