from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_employee
from backend.app.core.config import (
    ACCESS_TOKEN_MINUTES,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SECURE,
)
from backend.app.core.rate_limit import login_rate_limiter
from backend.app.db.session import get_db_session
from backend.app.models import Employee
from backend.app.schemas.auth import EmployeeRead, LoginRequest
from backend.app.services.auth import authenticate_employee
from backend.app.services.employee_sessions import (
    create_employee_session,
    revoke_employee_session,
)


router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/login", response_model=EmployeeRead)
def login(
    request: LoginRequest,
    response: Response,
    http_request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> Employee:
    client_key = http_request.client.host if http_request.client else "unknown"
    retry_after = login_rate_limiter.consume(client_key)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    employee = authenticate_employee(
        session,
        request.identifier,
        request.password.get_secret_value(),
    )
    if employee is None:
        raise HTTPException(status_code=401, detail="Invalid username/email or password.")

    token = create_employee_session(session, employee)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ACCESS_TOKEN_MINUTES * 60,
        httponly=True,
        samesite="strict",
        secure=SESSION_COOKIE_SECURE,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    login_rate_limiter.reset(client_key)
    return employee


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> Response:
    if token is not None:
        revoke_employee_session(session, token)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="strict",
        secure=SESSION_COOKIE_SECURE,
        path="/",
    )
    response.status_code = 204
    return response


@router.get("/me", response_model=EmployeeRead)
def current_employee(
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> Employee:
    return employee
