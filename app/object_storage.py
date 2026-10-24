"""Private S3 objects for Neon deployments; never expose storage credentials.

Keys come from server-generated identifiers. Document ACLs are checked by the
caller before probing or opening an original PDF. No public URLs are returned.
"""
from dataclasses import dataclass
from functools import lru_cache
import os
import re
from urllib.parse import urlsplit
from uuid import UUID

from app import settings
from app.file_ingestion import MAX_FILE_BYTES


class StorageUnavailable(ConnectionError):
    """Sanitized error; SDK exceptions may contain private request details."""


class InvalidRange(ValueError):
    pass


@dataclass(frozen=True)
class RemotePDF:
    key: str
    size: int


def enabled() -> bool:
    if settings.RAG_STORAGE_BACKEND not in ('local', 's3'):
        raise ValueError('RAG_STORAGE_BACKEND must be local or s3')
    return settings.RAG_STORAGE_BACKEND == 's3'


def bucket(kind: str) -> str:
    value = (settings.RAG_DOCUMENTS_BUCKET if kind == 'pdf'
             else settings.RAG_UPLOADS_BUCKET)
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', value):
        raise ValueError('Configure valid private object-storage bucket names')
    if settings.RAG_DOCUMENTS_BUCKET == settings.RAG_UPLOADS_BUCKET:
        raise ValueError('Documents and staged uploads require separate buckets')
    return value


@lru_cache(maxsize=1)
def client():
    # Imported only for the explicitly enabled backend; local installations keep
    # working without contacting S3 or discovering credentials through metadata.
    import boto3
    from botocore.config import Config
    endpoint = os.getenv('AWS_ENDPOINT_URL_S3', '')
    try:
        url = urlsplit(endpoint)
        valid = (url.scheme == 'https' and url.hostname and not url.username
                 and not url.password and not url.query and not url.fragment
                 and url.path in ('', '/'))
        url.port
    except ValueError:
        valid = False
    keys = ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_REGION')
    if not valid or any(not os.getenv(key) for key in keys):
        raise StorageUnavailable('Configure the private S3 endpoint, region and credentials')
    return boto3.client('s3', endpoint_url=endpoint,
        region_name=os.environ['AWS_REGION'],
        aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                      connect_timeout=5, read_timeout=60,
                      retries={'mode': 'standard', 'max_attempts': 3},
                      request_checksum_calculation='when_required',
                      response_checksum_validation='when_required'))


def call(operation: str, **kwargs):
    try:
        return getattr(client(), operation)(**kwargs)
    except StorageUnavailable:
        raise
    except Exception as exc:
        response = getattr(exc, 'response', {})
        code = str(response.get('Error', {}).get('Code', ''))
        if code in ('NoSuchKey', 'NotFound', '404'):
            raise FileNotFoundError('Stored document unavailable') from None
        if code in ('InvalidRange', 'RequestedRangeNotSatisfiable', '416'):
            raise InvalidRange('Requested PDF range is unavailable') from None
        raise StorageUnavailable('Private document storage is temporarily unavailable') from None


def upload_key(job_id: UUID) -> str:
    return f'staged/{UUID(str(job_id)).hex}.upload'


def pdf_key(document_id: int) -> str:
    if type(document_id) is not int or document_id <= 0:
        raise ValueError('Invalid document ID')
    return f'originals/{document_id}.pdf'


def put_upload(job_id: UUID, data: bytes) -> None:
    call('put_object', Bucket=bucket('upload'), Key=upload_key(job_id), Body=data,
         ContentType='application/octet-stream', CacheControl='private, no-store')


def read_upload(job_id: UUID) -> bytes:
    return read_staged_object(upload_key(job_id))


def incoming_key(job_id: UUID) -> str:
    # Browser policies grant access only here, never to worker staging/originals.
    return f'incoming/{UUID(str(job_id)).hex}.upload'


def read_staged_object(key: str) -> bytes:
    result = call('get_object', Bucket=bucket('upload'), Key=key)
    body = result['Body']
    try:
        if result.get('ContentLength', 0) > MAX_FILE_BYTES:
            raise ValueError('File exceeds the upload size limit')
        data = body.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('File exceeds the upload size limit')
        return data
    except ValueError:
        raise
    except Exception:
        raise StorageUnavailable('Could not read staged document') from None
    finally:
        body.close()


def remove_incoming(job_id: UUID) -> None:
    call('delete_object', Bucket=bucket('upload'), Key=incoming_key(job_id))


def remove_upload(job_id: UUID) -> None:
    call('delete_object', Bucket=bucket('upload'), Key=upload_key(job_id))


def upload_exists(job_id: UUID) -> bool:
    try:
        call('head_object', Bucket=bucket('upload'), Key=upload_key(job_id))
        return True
    except FileNotFoundError:
        return False


def put_pdf(document_id: int, data: bytes) -> None:
    call('put_object', Bucket=bucket('pdf'), Key=pdf_key(document_id), Body=data,
         ContentType='application/pdf', CacheControl='private, no-store')


def remove_pdf(document_id: int) -> None:
    call('delete_object', Bucket=bucket('pdf'), Key=pdf_key(document_id))


def find_pdf(document_id: int) -> RemotePDF | None:
    key = pdf_key(document_id)
    try:
        result = call('head_object', Bucket=bucket('pdf'), Key=key)
    except FileNotFoundError:
        return None
    return RemotePDF(key, int(result['ContentLength']))


def open_pdf(pdf: RemotePDF, byte_range: str | None = None):
    options = dict(Bucket=bucket('pdf'), Key=pdf.key)
    if byte_range:
        if not re.fullmatch(r'bytes=(?:\d+-\d*|-\d+)', byte_range):
            raise InvalidRange('Only a single PDF byte range is supported')
        options['Range'] = byte_range
    return call('get_object', **options)


def chunks(body):
    try:
        for chunk in body.iter_chunks(chunk_size=64 * 1024):
            if chunk:
                yield chunk
    except Exception:
        raise StorageUnavailable('PDF transfer interrupted') from None
    finally:
        body.close()
