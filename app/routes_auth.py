from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RevokedToken, Student, StudentAccountRequest, User
from app.auth import (
    bearer_scheme,
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class StudentAccountRequestCreate(BaseModel):
    student_id: str = Field(..., min_length=3, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    password: str = Field(..., min_length=12, max_length=72)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    name: str
    student_id: str | None = None


@router.post("/login", response_model=LoginResponse)
def login(creds: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user with username and password; returns JWT access token."""
    username_clean = creds.username.strip()
    user = db.query(User).filter(User.username.ilike(username_clean)).first()

    if not user or not verify_password(creds.password, user.hashed_password):
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


@router.post("/student-account-requests", status_code=status.HTTP_202_ACCEPTED)
def request_student_account(
    payload: StudentAccountRequestCreate,
    db: Session = Depends(get_db),
):
    """Submit a student-only account request for administrative approval."""
    student_id = payload.student_id.strip().upper()
    if len(payload.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="Password must be at most 72 UTF-8 bytes.")

    student = db.query(Student).filter(Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student record not found. Contact your administrator.")
    if db.query(User.id).filter(
        (User.username == student_id) | (User.student_id == student_id)
    ).first():
        raise HTTPException(status_code=409, detail="An account already exists for this student.")

    existing_request = db.query(StudentAccountRequest).filter(
        StudentAccountRequest.student_id == student_id,
    ).first()
    if existing_request and existing_request.status == "pending":
        raise HTTPException(status_code=409, detail="An account request is already awaiting approval.")

    if existing_request:
        existing_request.hashed_password = hash_password(payload.password)
        existing_request.status = "pending"
        existing_request.created_at = datetime.now(timezone.utc)
        existing_request.reviewed_at = None
    else:
        db.add(StudentAccountRequest(
            student_id=student_id,
            hashed_password=hash_password(payload.password),
        ))
    db.commit()
    return {
        "status": "pending_approval",
        "message": "Your request was sent to an administrator for approval.",
    }


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
