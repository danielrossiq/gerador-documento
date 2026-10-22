from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import CSRF_COOKIE, SESSION_COOKIE, Ctx, client_ip, get_ctx, require_same_origin
from app.db.session import get_db
from app.modules.auth import service

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=200)
    workspace_name: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class ForgotIn(BaseModel):
    email: str = Field(max_length=320)


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=200)


def _set_cookies(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    max_age = s.session_ttl_hours * 3600
    common: dict[str, Any] = {
        "max_age": max_age,
        "secure": s.cookie_secure,
        "samesite": "lax",
        "path": "/",
        "domain": s.cookie_domain,
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)


def _me(ctx_user, ws, role: str, csrf: str | None = None) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "user": {"id": str(ctx_user.id), "name": ctx_user.name, "email": ctx_user.email},
        "workspace": {"id": str(ws.id), "name": ws.name, "slug": ws.slug, "role": role},
        "csrf_token": csrf,
    }


@router.post("/register", status_code=201, dependencies=[Depends(require_same_origin)])
def register(
    body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict[str, Any]:
    ip = client_ip(request)
    user, ws = service.register(
        db,
        name=body.name,
        email=body.email,
        password=body.password,
        workspace_name=body.workspace_name,
        ip=ip,
    )
    token, csrf = service.create_session(db, user, ws, ip, request.headers.get("user-agent"))
    db.commit()
    _set_cookies(response, token, csrf)
    return _me(user, ws, "owner", csrf)


@router.post("/login", dependencies=[Depends(require_same_origin)])
def login(
    body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict[str, Any]:
    user, ws, token, csrf = service.login(
        db,
        email=body.email,
        password=body.password,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _set_cookies(response, token, csrf)
    member_role = next((m.role for m in user.memberships if m.workspace_id == ws.id), "member")
    return _me(user, ws, member_role, csrf)


@router.post("/logout", status_code=204)
def logout(response: Response, ctx: Ctx = Depends(get_ctx)) -> Response:
    service.logout(ctx.db, ctx.session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    data = _me(ctx.user, ctx.workspace, ctx.role, ctx.session.csrf_token)
    data["limits"] = {
        k: ctx.limit(k) for k in ("max_generators", "max_batch_rows", "max_upload_mb", "max_docs_per_month")
    }
    s = get_settings()
    data["features"] = {"pdf_import": s.pdf_import_mode != "off", "external_ai": s.external_ai_enabled}
    return data


@router.post("/forgot-password", status_code=202, dependencies=[Depends(require_same_origin)])
def forgot(body: ForgotIn, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    service.forgot_password(db, body.email, client_ip(request))
    return {"detail": "Se o e-mail estiver cadastrado, enviaremos as instruções de recuperação."}


@router.post("/reset-password", dependencies=[Depends(require_same_origin)])
def reset(body: ResetIn, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    service.reset_password(db, body.token, body.password, client_ip(request))
    return {"detail": "Senha atualizada. Entre com a nova senha."}
