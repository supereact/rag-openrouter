"""Smoke-test the rehearsal web proxy or direct VPS API without credentials."""
from __future__ import annotations

import argparse
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def probe(url: str, *, expected: int, timeout: float = 10.0) -> int:
    """GET a URL; treat 401 as a valid negative authentication test."""
    req = Request(url, headers={"User-Agent": "rag-deployment-smoke/1.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status
    except HTTPError as exc:
        return exc.code


def run(base: str, *, api_only: bool = False) -> bool:
    base = base.rstrip("/")
    checks = (
        ("Database readiness", f"{base}/health", 200),
        ("Authentication required", f"{base}/documents", 401),
    ) if api_only else (
        ("Web UI", f"{base}/", 200),
        ("Database readiness", f"{base}/api/health", 200),
        ("Authentication required", f"{base}/api/documents", 401),
    )
    ok = True
    for label, url, want in checks:
        try:
            status = probe(url, expected=want)
            match = status == want
            print(f"{'PASS' if match else 'FAIL'} {label}: HTTP {status} (expected {want})")
            ok = match and ok
        except (URLError, TimeoutError, OSError) as exc:
            print(f"FAIL {label}: {type(exc).__name__}: {exc}", file=sys.stderr)
            ok = False
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument('--api-only', action='store_true', help='Check a direct VPS API origin without a frontend proxy.')
    arguments = parser.parse_args()
    sys.exit(0 if run(arguments.url, api_only=arguments.api_only) else 1)
