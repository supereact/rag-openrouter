"""Vercel entrypoint; ordinary local Uvicorn startup remains app.main:app."""
from pathlib import Path

from app.hosted_runtime import configure

configure(Path(__file__).parent)

from app.main import app  # noqa: E402,F401
