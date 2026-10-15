from datetime import datetime, timedelta, timezone
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError as JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from api.db import get_db
from api.models import User
from api.settings import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt

def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_cookie_max_age,
        expires=settings.auth_cookie_max_age,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def set_csrf_cookie(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        max_age=settings.auth_cookie_max_age,
        expires=settings.auth_cookie_max_age,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=False,
        samesite="lax",
    )
    return token


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    response.delete_cookie(key=settings.csrf_cookie_name, path="/")


def require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="Untrusted request origin")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not request.url.path.endswith(("/auth/register", "/auth/login")):
        cookie_token = request.cookies.get(settings.csrf_cookie_name)
        header_token = request.headers.get(settings.csrf_header_name)
        if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
            raise HTTPException(status_code=403, detail="CSRF validation failed")


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    session_token = token or request.cookies.get(settings.auth_cookie_name)
    if not session_token:
        raise credentials_exception

    try:
        payload = jwt.decode(session_token, settings.secret_key, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user
