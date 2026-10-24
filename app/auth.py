import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from uuid import uuid4
import jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.database import get_db
from app.models import User, FacultyAssignment, RevokedToken, Student

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32 or SECRET_KEY.startswith("CHANGE_ME"):
    raise RuntimeError(
        "SECRET_KEY is missing or insecure. Copy .env.example to .env and generate a key with: "
        'python -c "import secrets; print(secrets.token_urlsafe(48))".'
    )
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "jti": uuid4().hex})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Authenticate user via Bearer token, query param 'token', or 'Authorization' header.
    Raises 401 if invalid or missing.
    """
    token = credentials.credentials if credentials else None

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username: str = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_id = payload.get("jti")
    if not token_id or db.query(RevokedToken.jti).filter(RevokedToken.jti == token_id).first():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(allowed_roles: List[str]):
    """Enforce endpoint access restricted to specific roles."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Role '{current_user.role}' lacks permission for this resource"
            )
        return current_user
    return role_checker


def check_student_access(student_id: str, current_user: User, db: Session) -> bool:
    """
    Strict role enforcement for student record access:
    - ADMIN: full access to any student
    - FACULTY: only their assigned students
    - STUDENT: only their own record (based on current_user.student_id)
    Returns True or raises HTTPException(403).
    """
    # Normalize ID for comparison
    clean_student_id = student_id.strip().upper()

    if current_user.role == "ADMIN":
        return True

    if current_user.role == "FACULTY":
        assignment = db.query(FacultyAssignment).filter(
            FacultyAssignment.faculty_id == current_user.id,
            FacultyAssignment.student_id == clean_student_id
        ).first()
        if assignment:
            return True
        # Check if mentor_id matches
        student = db.query(Student).filter(Student.student_id == clean_student_id).first()
        if student and student.mentor_id == current_user.id:
            return True

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Student '{clean_student_id}' is not in your assigned cohort"
        )

    if current_user.role == "STUDENT":
        user_sid = (current_user.student_id or "").strip().upper()
        if user_sid and user_sid == clean_student_id:
            return True
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Students are only permitted to access their own record"
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: Unauthorized access"
    )
