"""Private local original-PDF storage for source verification (development MVP).

Not a public static directory. All reads must pass document authorization first.
Never use user-supplied filenames as disk paths.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from uuid import uuid4

from app.db import db_connection
from app.security import Principal

PDF_DIR = Path(os.getenv(
    'RAG_PDF_STORAGE_DIR',
    str(Path(__file__).resolve().parents[1] / '.original_pdfs'),
))


def _pdf_path(document_id: int) -> Path:
    if type(document_id) is not int or document_id <= 0:
        raise ValueError('Invalid document ID')
    return PDF_DIR / f'{document_id}.pdf'


def store_pdf(document_id: int, data: bytes) -> None:
    """Atomically replace original file, restricted to the server's user."""
    if not data.startswith(b'%PDF-'):
        raise ValueError('Uploaded bytes are not a PDF')
    if PDF_DIR.is_symlink():
        raise RuntimeError('PDF storage directory must not be a symlink')
    PDF_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _pdf_path(document_id)
    temporary = PDF_DIR / f'.{document_id}.{uuid4().hex}.tmp'
    descriptor = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_pdf(document_id: int) -> None:
    _pdf_path(document_id).unlink(missing_ok=True)


def authorized_pdf(principal: Principal, document_id: int) -> tuple[Path, str] | None:
    """Return the original PDF for an authorized user only; else None.

    The SQL policy intentionally matches vector and full-text search access rules.
    Never test file presence or report metadata before the permission query.
    """
    from app.services import ACCESS_SQL, access_args

    with db_connection() as conn:
        row = conn.execute(
            f'''SELECT d.title FROM documents d
                WHERE d.id=%s AND {ACCESS_SQL}''',
            (document_id, *access_args(principal)),
        ).fetchone()
    if not row or not row[0].lower().endswith('.pdf'):
        return None
    path = _pdf_path(document_id)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    return path, row[0]
