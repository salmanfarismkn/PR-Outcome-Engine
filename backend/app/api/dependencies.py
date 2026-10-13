from enum import StrEnum
import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

security = HTTPBearer(auto_error=False)


class ApiRole(StrEnum):
    READ = "read"
    ADMIN = "admin"


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> ApiRole:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    read_token = settings.api_read_token
    admin_token = settings.api_admin_token
    if (
        not read_token
        or not read_token.strip()
        or not admin_token
        or not admin_token.strip()
        or hmac.compare_digest(
            read_token.encode("utf-8"),
            admin_token.encode("utf-8"),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API credentials are not configured securely.",
        )

    supplied_token = credentials.credentials.encode("utf-8")
    is_read_token = hmac.compare_digest(
        supplied_token,
        read_token.encode("utf-8"),
    )
    is_admin_token = hmac.compare_digest(
        supplied_token,
        admin_token.encode("utf-8"),
    )
    if is_admin_token:
        return ApiRole.ADMIN
    if is_read_token:
        return ApiRole.READ

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bearer credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_read_access(
    role: ApiRole = Depends(get_current_user),
) -> ApiRole:
    return role


def require_admin_access(
    role: ApiRole = Depends(get_current_user),
) -> ApiRole:
    if role is not ApiRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative access required.",
        )
    return role
