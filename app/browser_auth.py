"""Browser cookie transport for the existing expiring, revocable sessions."""
from dataclasses import asdict
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from app import settings

COOKIE_NAME = 'rag_browser_session'
CSRF_HEADER = 'X-RAG-CSRF'
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def allowed_origins() -> list[str]:
    """Explicit origins only: never wildcard credentialed browser access."""
    result = []
    for value in settings.RAG_ALLOWED_ORIGINS.split(','):
        origin = value.strip().rstrip('/')
        if not origin:
            continue
        try:
            url = urlsplit(origin)
            valid = (url.scheme in ('http', 'https') and url.hostname
                and not url.username and not url.password
                and not url.path and not url.query and not url.fragment
                and '*' not in origin and '\\' not in origin
                and not any(char.isspace() for char in origin)
                and (url.scheme == 'https' or url.hostname in ('localhost', '127.0.0.1', '::1')))
            url.port  # Reject malformed/out-of-range ports as configuration errors.
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('RAG_ALLOWED_ORIGINS requires exact HTTPS origins (HTTP is allowed only for loopback).')
        if origin not in result:
            result.append(origin)
    return result


def cors_options() -> dict:
    return dict(allow_origins=allowed_origins(), allow_credentials=True,
                allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
                allow_headers=['Authorization', 'Content-Type', CSRF_HEADER],
                expose_headers=['X-Request-ID'], max_age=600)


def is_forbidden_cross_site_request(request: Request) -> bool:
    """Reject untrusted browser traffic before handlers, including safe methods.

    Origin-less clients remain supported; authentication still applies. Fetch
    Metadata prevents cross-site navigations that do not send an Origin header.
    """
    origin = request.headers.get('origin')
    expected = f'{request.url.scheme}://{request.url.netloc}'
    return (request.headers.get('sec-fetch-site') == 'cross-site'
            or (origin is not None
                and origin != expected and origin not in allowed_origins()))


def require_browser_request(request: Request) -> None:
    # Custom headers cannot be sent by cross-origin HTML forms. Only explicitly
    # configured same-site frontends may make cross-origin cookie requests.
    origin = request.headers.get('origin')
    expected = f'{request.url.scheme}://{request.url.netloc}'
    site = request.headers.get('sec-fetch-site')
    trusted = origin == expected or origin in allowed_origins()
    if (request.headers.get(CSRF_HEADER) != '1'
            or site not in (None, 'same-origin', 'same-site', 'none')
            or (origin is not None and not trusted)
            or (site == 'same-site' and not trusted)):
        raise HTTPException(403, 'Trusted same-site browser request required')


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
