"""Browser cookie transport for the existing expiring, revocable sessions."""
from dataclasses import asdict

from fastapi import HTTPException, Request, Response

COOKIE_NAME = 'rag_browser_session'
CSRF_HEADER = 'X-RAG-CSRF'
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def require_browser_request(request: Request) -> None:
    # Custom headers cannot be sent by cross-origin HTML forms. No credentialed
    # CORS is enabled. Also reject cross-origin fetches, including sibling sites.
    origin = request.headers.get('origin')
    expected = f'{request.url.scheme}://{request.url.netloc}'
    if (request.headers.get(CSRF_HEADER) != '1'
            or request.headers.get('sec-fetch-site') not in (None, 'same-origin', 'none')
            or (origin is not None and origin != expected)):
        raise HTTPException(403, 'Same-origin browser request required')


def secure_cookie(request: Request) -> bool:
    # Local HTTP development remains usable; every other host requires HTTPS.
    return not (request.url.scheme == 'http' and
                request.url.hostname in ('localhost', '127.0.0.1', '::1', '[::1]'))


def check_browser_transport(request: Request) -> None:
    require_browser_request(request)
    if secure_cookie(request) and request.url.scheme != 'https':
        raise HTTPException(400, 'HTTPS is required for browser sign-in outside localhost')


def clear_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE_NAME, path='/', secure=secure_cookie(request),
                           httponly=True, samesite='strict')
    response.headers['Cache-Control'] = 'no-store'


def start_session(response: Response, request: Request, result: dict) -> dict:
    from app.security import principal_from_api_key
    principal = principal_from_api_key(result['access_token'])
    if principal is None:
        raise HTTPException(401, 'Session unavailable; please sign in again')
    response.set_cookie(COOKIE_NAME, result['access_token'], max_age=result['expires_in'],
                        path='/', secure=secure_cookie(request), httponly=True,
                        samesite='strict')
    response.headers['Cache-Control'] = 'no-store'
    # The browser never receives the session secret in JSON.
    return asdict(principal)
