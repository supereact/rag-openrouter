"""Authenticated account controls; cookie writes retain existing CSRF checks."""
from datetime import datetime
from typing import Callable

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app import account_security, browser_auth
from app.security import Principal, bearer, require_principal


class PrivateValidationRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()
        async def private_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # Default validation responses include input values. Never echo
                # submitted passwords, including invalid/extra fields.
                raise HTTPException(422, 'Invalid account security request.') from exc
        return private_handler


router = APIRouter(prefix='/auth', tags=['account security'], route_class=PrivateValidationRoute)


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class Session(BaseModel):
    id: int
    created_at: datetime
    expires_at: datetime
    current: bool


class SessionList(BaseModel):
    password_enabled: bool
    password_session: bool
    sessions: list[Session]
    total: int
    page: int
    page_size: int


class PasswordResult(BaseModel):
    sign_in_required: bool


class RevokeResult(PasswordResult):
    revoked_count: int


def _token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str:
    # Match require_principal: explicit Authorization never falls back to cookies.
    if request.headers.get('authorization') is not None:
        return credentials.credentials if credentials else ''
    return request.cookies.get(browser_auth.COOKIE_NAME, '')


def _call(response: Response, function, *args):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return function(*args)
    except (psycopg.Error, OSError) as exc:
        raise HTTPException(503, 'Account security is temporarily unavailable. Please try again later.') from exc


def _clear_if_signed_out(response, request, token, result):
    if result['sign_in_required'] and token == request.cookies.get(browser_auth.COOKIE_NAME):
        browser_auth.clear_cookie(response, request)
    return result


@router.get('/sessions', response_model=SessionList)
def sessions(request: Request, response: Response, page: int = Query(1, ge=1),
             page_size: int = Query(20), principal: Principal = Depends(require_principal),
             credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if page_size not in (20, 50, 100):
        raise HTTPException(422, 'page_size must be 20, 50 or 100')
    return _call(response, account_security.list_sessions, principal, _token(request, credentials), page, page_size)


@router.post('/password', response_model=PasswordResult)
def password(body: PasswordBody, request: Request, response: Response,
             principal: Principal = Depends(require_principal),
             credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    token = _token(request, credentials)
    result = _call(response, account_security.change_password, principal, token,
                   body.current_password.get_secret_value(), body.new_password.get_secret_value())
    return _clear_if_signed_out(response, request, token, result)


@router.post('/sessions/revoke-others', response_model=RevokeResult)
def revoke_others(request: Request, response: Response, principal: Principal = Depends(require_principal),
                  credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    return _call(response, account_security.revoke_other_sessions, principal, _token(request, credentials))


@router.delete('/sessions/{session_id}', response_model=RevokeResult)
def revoke(session_id: int, request: Request, response: Response,
           principal: Principal = Depends(require_principal),
           credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    token = _token(request, credentials)
    result = _call(response, account_security.revoke_session, principal, token, session_id)
    return _clear_if_signed_out(response, request, token, result)
