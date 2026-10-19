"""Small NOWPayments adapter. Fixed HTTPS hosts, no credentials/payloads in logs."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from fastapi import HTTPException

from app import settings

NETWORKS = {'usdttrc20': 'USDT · Tron (TRC-20)',
            'usdtbsc': 'USDT · BNB Smart Chain (BEP-20)',
            'usdterc20': 'USDT · Ethereum (ERC-20)'}


def mode() -> str:
    selected = settings.RAG_PAYMENTS_MODE
    if selected not in ('disabled', 'sandbox', 'live'):
        raise HTTPException(503, 'Invalid payment mode configuration')
    return selected


def credentials(selected: str) -> tuple[str, str]:
    if selected == 'sandbox':
        return settings.NOWPAYMENTS_SANDBOX_API_KEY, settings.NOWPAYMENTS_SANDBOX_IPN_SECRET
    if selected == 'live':
        return settings.NOWPAYMENTS_API_KEY, settings.NOWPAYMENTS_IPN_SECRET
    return '', ''


def callback_url(selected: str) -> str:
    base = settings.RAG_PAYMENTS_CALLBACK_BASE_URL
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment):
        raise HTTPException(503, 'Configure a public HTTPS payment callback base URL')
    return f'{base}/payments/nowpayments/{selected}/ipn'


def ready(selected: str) -> bool:
    key, secret = credentials(selected)
    if not key or not secret:
        return False
    try:
        callback_url(selected)
        return True
    except HTTPException:
        return False


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_request(selected: str, method: str, path: str, body: dict | None = None) -> dict:
    key, _ = credentials(selected)
    if not key or selected not in ('sandbox', 'live'):
        raise HTTPException(503, 'Payment provider is not configured')
    if not re.fullmatch(r'/payment(?:/[0-9]{1,40})?', path):
        raise ValueError('Invalid provider endpoint')
    host = 'api-sandbox.nowpayments.io' if selected == 'sandbox' else 'api.nowpayments.io'
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(f'https://{host}/v1{path}', data=payload, method=method,
                      headers={'x-api-key': key, 'Content-Type': 'application/json'})
    try:
        # Never forward the API key through a redirect. No automatic POST retries:
        # an interrupted creation may already have created a provider payment.
        with build_opener(NoRedirects()).open(request, timeout=2 if method == 'GET' else 8) as response:
            data = response.read(128_001)
        if len(data) > 128_000:
            raise ValueError('Response too large')
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError('Invalid provider response')
        return result
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise HTTPException(502, 'Payment provider unavailable; check this order before starting another payment') from exc


def verify_ipn(selected: str, raw: bytes, signature: str) -> tuple[dict, str]:
    _, secret = credentials(selected)
    if not secret:
        raise HTTPException(503, 'Payment notifications are not configured')
    if not re.fullmatch(r'[a-fA-F0-9]{128}', signature):
        raise HTTPException(401, 'Invalid payment signature')
    try:
        # Reject duplicate keys and non-JSON numeric values before canonicalizing.
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate key')
                result[key] = value
            return result
        payload = json.loads(raw, object_pairs_hook=unique_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(payload, dict):
            raise ValueError('Expected object')
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HTTPException(400, 'Invalid payment notification') from exc
    expected = hmac.new(secret.encode(), canonical, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise HTTPException(401, 'Invalid payment signature')
    return payload, hashlib.sha256(canonical).hexdigest()
