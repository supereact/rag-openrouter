"""Short-lived direct uploads, frozen into private worker input after verification.

The signed policy can write one incoming key only. Completion checks the current
writer, ticket, byte length and digest, then stores a separate server-only object.
An advisory lock makes replay safe even after a worker has consumed its input.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from app import object_storage, settings
from app.db import db_connection
from app.file_ingestion import MAX_FILE_BYTES
from app.ingestion_jobs import safe_filename
from app.schemas import DirectUploadRequest
from app.security import Principal

TTL_SECONDS = 600
LOCK_NAMESPACE = 78171024
logger = logging.getLogger('rag.direct_uploads')


def signing_key() -> bytes:
    if not object_storage.enabled() or len(settings.RAG_UPLOAD_SIGNING_KEY.encode()) < 32:
        raise object_storage.StorageUnavailable('Configure private direct-upload signing')
    return settings.RAG_UPLOAD_SIGNING_KEY.encode()


def scope() -> str:
    database = urlsplit(settings.DATABASE_URL)
    text = '|'.join([database.hostname or '', database.path,
        os.getenv('AWS_ENDPOINT_URL_S3', '').rstrip('/'), object_storage.bucket('upload')])
    return hashlib.sha256(text.encode()).hexdigest()


def signature(payload: str) -> str:
    return hmac.new(signing_key(), b'rag-direct-upload-v1\n' + payload.encode('ascii'), hashlib.sha256).hexdigest()


def prepare(body: DirectUploadRequest, principal: Principal) -> dict:
    if principal.role not in ('admin', 'editor'):
        raise PermissionError('Write permission required')
    signing_key()  # Fail before issuing any storage capability.
    filename = safe_filename(body.filename)
    job_id = uuid4()
    expires = int(time.time()) + TTL_SECONDS
    claims = {'v': 1, 'id': job_id.hex, 'tenant': principal.tenant_id, 'user': principal.user_id,
              'filename': filename, 'size': body.size, 'sha256': body.sha256,
              'exp': expires, 'scope': scope()}
    payload = base64.urlsafe_b64encode(json.dumps(claims, separators=(',', ':')).encode()).decode().rstrip('=')
    ticket = payload + '.' + signature(payload)
    fields = {'Content-Type': 'application/octet-stream', 'Cache-Control': 'private, no-store'}
    target = object_storage.call('generate_presigned_post', Bucket=object_storage.bucket('upload'),
        Key=object_storage.incoming_key(job_id), Fields=fields,
        Conditions=[{'Content-Type': fields['Content-Type']}, {'Cache-Control': fields['Cache-Control']},
                    ['content-length-range', body.size, body.size]], ExpiresIn=TTL_SECONDS)
    return dict(ticket=ticket, url=target['url'], fields=target['fields'], expires_at=expires)


def claims_for(ticket: str, principal: Principal) -> dict:
    try:
        payload, supplied = ticket.split('.')
        if not hmac.compare_digest(signature(payload), supplied):
            raise ValueError()
        value = json.loads(base64.b64decode(payload + '=' * (-len(payload) % 4), altchars=b'-_', validate=True))
        if (value['v'] != 1 or value['exp'] <= time.time() or value['scope'] != scope()
                or not 0 < value['size'] <= MAX_FILE_BYTES):
            raise ValueError()
        UUID(value['id'])
    except object_storage.StorageUnavailable:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError('Upload authorization is invalid or expired; select the file again') from None
    if value['tenant'] != principal.tenant_id or value['user'] != principal.user_id:
        raise PermissionError('Upload access denied')
    return value


def complete(ticket: str, principal: Principal) -> dict:
    if principal.role not in ('admin', 'editor'):
        raise PermissionError('Write permission required')
    claims = claims_for(ticket, principal)
    job_id = UUID(claims['id'])
    with db_connection() as conn:
        # Separate lock namespace from budget reservations. Collisions only
        # serialize unrelated finalizations, never grant access to another job.
        conn.execute('SELECT pg_advisory_xact_lock(%s,%s)',
                     (LOCK_NAMESPACE, int.from_bytes(job_id.bytes[:4], 'big', signed=True)))
        existing = conn.execute('''SELECT tenant_id,user_id,filename,created_at
            FROM ingestion_jobs WHERE id=%s''', (job_id,)).fetchone()
        if existing:
            if existing[:3] != (principal.tenant_id, principal.user_id, claims['filename']):
                raise PermissionError('Upload access denied')
            created_at = existing[3]
        else:
            try:
                data = object_storage.read_staged_object(object_storage.incoming_key(job_id))
            except FileNotFoundError:
                raise ValueError('Upload has not reached storage; retry the file upload') from None
            if len(data) != claims['size'] or hashlib.sha256(data).hexdigest() != claims['sha256']:
                raise ValueError('Uploaded file does not match its authorized size and checksum')
            if claims['filename'].lower().endswith('.pdf') and not data.startswith(b'%PDF-'):
                raise ValueError('Uploaded bytes are not a PDF')
            # Full PDF/text extraction and page-count validation remain in the
            # existing worker, outside the HTTP acknowledgement path.
            object_storage.put_upload(job_id, data)
            created_at = conn.execute('''INSERT INTO ingestion_jobs
                (id,tenant_id,user_id,filename,status) VALUES (%s,%s,%s,%s,'queued')
                RETURNING created_at''', (job_id, principal.tenant_id,
                principal.user_id, claims['filename'])).fetchone()[0]
        result = dict(id=str(job_id), filename=claims['filename'], status='queued', created_at=created_at)
    # Do not delete frozen input on an uncertain commit. A retry can discover
    # the committed job; deleting input could destroy a worker's accepted file.
    try:
        object_storage.remove_incoming(job_id)
    except object_storage.StorageUnavailable:
        logger.warning('Incoming upload cleanup deferred; use the expired-upload cleanup command')
    return result
