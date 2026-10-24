from datetime import datetime, timezone
import re
import threading
import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AccountRequest, RevokedToken, Student, User
from app.auth import (
    bearer_scheme,
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_rate_limit_lock = threading.Lock()
_rate_limit_events: dict[tuple[str, str], list[float]] = {}
_RATE_LIMIT_MAX_REQUESTS = 20
_RATE_LIMIT_WINDOW_SECONDS = 60


def _enforce_rate_limit(request: Request, action: str) -> None:
    address = request.client.host if request.client else "unknown"
    key = (action, address)
    now = time.monotonic()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
    with _rate_limit_lock:
        recent = [timestamp for timestamp in _rate_limit_events.get(key, []) if timestamp > cutoff]
        if len(recent) >= _RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please wait a minute and try again.",
            )
        recent.append(now)
        _rate_limit_events[key] = recent


def _submit_account_request(payload: "AccountRequestCreate", db: Session):
    if len(payload.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="Password must be at most 72 UTF-8 bytes.")

    requested_username = (
        (payload.student_id or "").strip().upper()
        if payload.role == "STUDENT"
        else (payload.username or "").strip()
    )
    pending_username = db.query(AccountRequest.id).filter(
        AccountRequest.status == "pending",
        func.lower(AccountRequest.requested_username) == requested_username.lower(),
    ).first()
    if pending_username:
        raise HTTPException(status_code=409, detail="A request for this username is already awaiting approval.")

    if payload.role == "STUDENT":
        student_id = (payload.student_id or "").strip().upper()
        student = db.query(Student).filter(Student.student_id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Student record not found. Contact your administrator.")
        if db.query(User.id).filter(
            or_(func.lower(User.username) == student_id.lower(), User.student_id == student_id)
        ).first():
            raise HTTPException(status_code=409, detail="An account already exists for this student.")

        account_request = db.query(AccountRequest).filter(
            AccountRequest.role == "STUDENT",
            AccountRequest.student_id == student_id,
        ).order_by(AccountRequest.created_at.desc()).first()
        if account_request and account_request.status == "pending":
            raise HTTPException(status_code=409, detail="An account request is already awaiting approval.")
        values = {
            "student_id": student_id,
            "name": student.name,
            "email": student.email,
            "department": student.department,
            "requested_username": student_id,
        }
    else:
        username = (payload.username or "").strip()
        email = (payload.email or "").strip().lower()
        if db.query(User.id).filter(
            or_(func.lower(User.username) == username.lower(), func.lower(User.email) == email)
        ).first():
            raise HTTPException(status_code=409, detail="An account already exists for this username or email.")
        pending_match = db.query(AccountRequest).filter(
            AccountRequest.role == "FACULTY",
            AccountRequest.status == "pending",
            func.lower(AccountRequest.email) == email,
        ).first()
        if pending_match:
            raise HTTPException(status_code=409, detail="A request for this username or email is already awaiting approval.")

        account_request = db.query(AccountRequest).filter(
            AccountRequest.role == "FACULTY",
            AccountRequest.status == "rejected",
            or_(
                func.lower(AccountRequest.requested_username) == username.lower(),
                func.lower(AccountRequest.email) == email,
            ),
        ).order_by(AccountRequest.created_at.desc()).first()
        values = {
            "student_id": None,
            "name": (payload.name or "").strip(),
            "email": email,
            "department": (payload.department or "").strip(),
            "requested_username": username,
        }

    if account_request is None:
        account_request = AccountRequest(role=payload.role, **values)
        db.add(account_request)
    else:
        for field, value in values.items():
            setattr(account_request, field, value)
        account_request.status = "pending"
    account_request.hashed_password = hash_password(payload.password)
    account_request.created_at = datetime.now(timezone.utc)
    account_request.reviewed_at = None
    account_request.reviewed_by = None
    account_request.reject_reason = None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A request for this username or email is already awaiting approval.",
        ) from exc
    return {
        "status": "pending_approval",
        "message": "Request sent. An administrator will review it. You can sign in once it is approved.",
    }


class LoginRequest(BaseModel):
    username: str
    password: str


class StudentAccountRequestCreate(BaseModel):
    student_id: str = Field(..., min_length=3, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    password: str = Field(..., min_length=12, max_length=72)


class AccountRequestCreate(BaseModel):
    role: Literal["STUDENT", "FACULTY"] = "STUDENT"
    student_id: str | None = Field(None, min_length=3, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str | None = Field(None, min_length=2, max_length=100)
    email: str | None = Field(None, min_length=3, max_length=120)
    department: str | None = Field(None, min_length=2, max_length=50)
    username: str | None = Field(None, min_length=3, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    password: str = Field(..., min_length=12, max_length=72)

    @model_validator(mode="after")
    def validate_role_fields(self):
        if self.role == "STUDENT" and not self.student_id:
            raise ValueError("Student ID is required for student account requests.")
        if self.role == "FACULTY":
            required = {
                "name": self.name,
                "email": self.email,
                "department": self.department,
                "username": self.username,
            }
            missing = [field for field, value in required.items() if not value or not value.strip()]
            if missing:
                raise ValueError(f"Required faculty fields: {', '.join(missing)}.")
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.email or ""):
                raise ValueError("Enter a valid email address.")
        return self


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    name: str
    student_id: str | None = None


@router.post("/login", response_model=LoginResponse)
def login(creds: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate user with username and password; returns JWT access token."""
    _enforce_rate_limit(request, "login")
    username_clean = creds.username.strip()
    user = db.query(User).filter(func.lower(User.username) == username_clean.lower()).first()

    if not user:
        account_request = db.query(AccountRequest).filter(
            func.lower(AccountRequest.requested_username) == username_clean.lower()
        ).order_by(AccountRequest.created_at.desc()).first()
        if account_request and verify_password(creds.password, account_request.hashed_password):
            if account_request.status == "pending":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Your account is waiting for admin approval",
                )
            if account_request.status == "rejected":
                detail = "Your request was rejected"
                if account_request.reject_reason:
                    detail = f"{detail}: {account_request.reject_reason}"
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not verify_password(creds.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    token = create_access_token({
        "sub": user.username,
        "role": user.role,
        "student_id": user.student_id
    })

    display_name = user.faculty_name if user.faculty_name else (user.student_id or user.username)

    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
        "name": display_name,
        "student_id": user.student_id
    }


@router.post("/account-requests", status_code=status.HTTP_202_ACCEPTED)
def request_account(
    payload: AccountRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Submit a student or faculty account request for administrative approval."""
    _enforce_rate_limit(request, "account-request")
    return _submit_account_request(payload, db)


@router.post("/student-account-requests", status_code=status.HTTP_202_ACCEPTED)
def request_student_account(
    payload: StudentAccountRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Legacy alias for student account requests."""
    _enforce_rate_limit(request, "account-request")
    return _submit_account_request(AccountRequestCreate(
        role="STUDENT",
        student_id=payload.student_id,
        password=payload.password,
    ), db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Revoke the current bearer token for subsequent protected API requests."""
    token_payload = decode_access_token(credentials.credentials) if credentials else None
    if token_payload and token_payload.get("jti"):
        expires_at = datetime.fromtimestamp(token_payload["exp"], tz=timezone.utc)
        db.merge(RevokedToken(jti=token_payload["jti"], expires_at=expires_at))
        db.commit()


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    """Returns currently authenticated user profile."""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "faculty_name": current_user.faculty_name,
        "student_id": current_user.student_id,
        "email": current_user.email
    }
