"""Endpoints de autenticação de usuários — registro e login."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.auth import authenticate_user, create_token, get_current_user, register_user
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = register_user(payload.name, payload.email, payload.password, db)
    token = create_token(user)
    return {
        "token": token,
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
    }


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(payload.email, payload.password, db)
    token = create_token(user)
    return {
        "token": token,
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
    }


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
