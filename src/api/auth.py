from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import secrets
import jwt
from fastapi import Header, HTTPException, status

ALLOWED_ALGORITHM = "HS256"
EXPECTED_ISSUER = "techrepair-auth-local"
EXPECTED_AUDIENCE = "techrepair-api"

# Ключ береться з оточення або генерується ефемерно при старті процесу (поза Git)
_RUNTIME_JWT_SECRET: str = os.getenv("TECHREPAIR_JWT_SECRET") or secrets.token_urlsafe(32)


def get_jwt_secret() -> str:
    return _RUNTIME_JWT_SECRET


@dataclass(frozen=True)
class AuthenticatedUser:
    sub: str
    role: str


def issue_test_access_token(
    sub: str,
    role: str,
    expires_delta: timedelta = timedelta(minutes=15),
    issuer: str = EXPECTED_ISSUER,
    audience: str = EXPECTED_AUDIENCE,
    secret: str | None = None,
    algorithm: str = ALLOWED_ALGORITHM,
) -> str:
    """Локальний навчальний емітент тестових JWT access token (RFC 7519)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    signing_key = secret if secret is not None else get_jwt_secret()
    return jwt.encode(payload, signing_key, algorithm=algorithm)


def verify_access_token(token: str) -> AuthenticatedUser:
    """Сувора перевірка JWT за алгоритмом, підписом, iss, aud та exp (RFC 8725)."""
    try:
        payload = jwt.decode(
            token,
            get_jwt_secret(),
            algorithms=[ALLOWED_ALGORITHM],
            issuer=EXPECTED_ISSUER,
            audience=EXPECTED_AUDIENCE,
            options={
                "require": ["exp", "iss", "aud", "sub", "role"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Невалідний або прострочений токен доступу: {type(exc).__name__}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = payload.get("sub")
    role = payload.get("role")
    if not isinstance(sub, str) or not sub or role not in {"technician", "supervisor"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен не містить коректних тверджень sub або role",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthenticatedUser(sub=sub, role=role)


def get_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    """Залежність FastAPI для витягування та верифікації Bearer-токена."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Відсутній заголовок Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw_token = authorization.removeprefix("Bearer ").strip()
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Порожній токен доступу",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_access_token(raw_token)