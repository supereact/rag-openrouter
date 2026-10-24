"""Opt-in live verification on an expiring Neon validation branch only.

Starts real API/worker processes and uses synthetic accounts/documents. No local
database, original user files or paid generation is used. Fixtures remain on the
validation branch until it expires; no production records are deleted.
"""
import argparse
from io import BytesIO
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

from scripts.run_neon import environment


def synthetic_pdf(padding_bytes: int = 0) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    if padding_bytes:
        writer.add_metadata({'/Subject': 'X' * padding_bytes})
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(b'BT /F1 12 Tf 50 700 Td (Orchid calibration policy requires two independent approvals before release.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def wait_for(check, *, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ConnectionError):
            pass
        time.sleep(1)
    raise RuntimeError('Verification step timed out')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path('.env.neon-validation'))
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--direct-uploads', action='store_true', help='Verify signed uploads above the Vercel payload limit.')
    args = parser.parse_args()
    if not args.run:
        print('Preview: starts API/worker and creates synthetic fixtures on a validation branch. Add --run.')
        return 0
    processes = []
    try:
        env = environment(args.env_file)
        if not env.get('NEON_BRANCH', '').startswith('codex-neon-validation-'):
            raise ValueError('Live smoke fixtures require a codex-neon-validation-* branch')
        env.update(OPENROUTER_API_KEY='', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='1',
                   RAG_PUBLIC_REGISTRATION_ENABLED='true', RAG_PAYMENTS_MODE='disabled',
                   RAG_WALLET_ENFORCEMENT='false')
        if args.direct_uploads:
            env['RAG_ALLOWED_ORIGINS'] = 'http://127.0.0.1:5173'
        import psycopg
        with psycopg.connect(env['DATABASE_URL'], connect_timeout=10) as conn:
            role = conn.execute('''SELECT current_user,rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls,
                pg_has_role(current_user,'neon_superuser','MEMBER') FROM pg_roles WHERE rolname=current_user''').fetchone()
            assert role and role[0] == 'rag_app' and not role[1] and not role[2]
        print('PASS: API/worker use the restricted runtime database role', flush=True)
        # Only synthetic test logs go here, never console dumps of env or tokens.
        descriptor, log_name = tempfile.mkstemp(prefix='rag-neon-smoke-', suffix='.log')
        import httpx
        from uuid import UUID
        with os.fdopen(descriptor, 'wb') as logs, socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
            reserve.close()
            api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
                '--host', '127.0.0.1', '--port', str(port), '--no-access-log'],
                env=env, stdout=logs, stderr=logs)
            processes.append(api)
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=90, trust_env=False) as client:
                def ready():
                    if api.poll() is not None:
                        raise RuntimeError('API startup failed; inspect the private synthetic-test log')
                    try:
                        return client.get('/health').status_code == 200
                    except httpx.TransportError:
                        return False
                wait_for(ready)
                print('PASS: real FastAPI process started; Neon-backed /health returns 200', flush=True)
                assert client.get('/documents').status_code == 401
                identities = []
                suffix = secrets.token_hex(6)
                for index in (1, 2):
                    response = client.post('/auth/register', json={
                        'email': f'neon-smoke-{suffix}-{index}@example.invalid',
                        'username': f'neon_smoke_{suffix}_{index}',
                        'password': secrets.token_urlsafe(24)})
                    response.raise_for_status()
                    identities.append({'Authorization': 'Bearer ' + response.json()['access_token']})
                owner, outsider = identities
                identity = client.get('/me', headers=owner).json()
                assert identity['role'] == 'editor'
                print('PASS: public registration, persistent authentication and isolated editor identity', flush=True)
                pdf = synthetic_pdf(5 * 1024 * 1024 if args.direct_uploads else 0)
                documents = [('neon-smoke.pdf', pdf, 'application/pdf'),
                    ('neon-smoke.md', b'# Synthetic handbook\nOrchid calibration requires a logged independent review.', 'text/markdown')]
                queued = []
                for name, data, mime in documents:
                    if args.direct_uploads:
                        import hashlib
                        from concurrent.futures import ThreadPoolExecutor
                        prepared = client.post('/documents/uploads/prepare', headers=owner,
                            json={'filename': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
                        prepared.raise_for_status()
                        target = prepared.json()
                        origin = {'Origin': 'http://127.0.0.1:5173'}
                        denied = client.post('/documents/uploads/complete', headers=outsider,
                            json={'ticket': target['ticket']})
                        assert denied.status_code == 403
                        with httpx.Client(timeout=120, trust_env=False) as storage_client:
                            preflight = storage_client.options(target['url'], headers={**origin,
                                'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
                            assert preflight.status_code in (200,204), 'Storage preflight status'
                            cors_origin = preflight.headers.get('access-control-allow-origin')
                            assert cors_origin in (origin['Origin'], '*'), 'Storage preflight origin'
                            if cors_origin == '*':
                                print('NOTICE: provider returns wildcard CORS; exact-origin restriction is not verified', flush=True)
                            # Exact-size storage policy must reject a larger body.
                            oversized = storage_client.post(target['url'], data=target['fields'],
                                files={'file': (name, data+b'X', mime)}, headers=origin)
                            assert oversized.status_code in (400,403), 'Storage must enforce exact-size policy'
                            uploaded = storage_client.post(target['url'], data=target['fields'],
                                files={'file': (name, data, mime)}, headers=origin)
                            assert uploaded.status_code in (200,201,204), 'Signed storage POST status'
                            assert uploaded.headers.get('access-control-allow-origin') in (origin['Origin'], '*'), 'Storage upload origin'
                            def finish():
                                return client.post('/documents/uploads/complete', headers=owner,
                                    json={'ticket': target['ticket']})
                            with ThreadPoolExecutor(max_workers=2) as pool:
                                results = list(pool.map(lambda _: finish(), range(2)))
                            assert all(result.status_code == 202 for result in results)
                            response = results[0]
                            assert results[1].json()['id'] == response.json()['id']
                            # Reusing the browser policy cannot replace frozen worker input.
                            changed = storage_client.post(target['url'], data=target['fields'],
                                files={'file': (name, b'X'+data[1:], mime)}, headers=origin)
                            assert changed.status_code in (200,201,204)
                            assert finish().json()['id'] == response.json()['id']
                        print('PASS: direct upload CORS, exact-size policy, ownership, concurrent completion and replay safety', flush=True)
                    else:
                        response = client.post('/documents/upload-async', headers=owner,
                            files={'file': (name, data, mime)})
                        assert response.status_code == 202
                    queued.append(response.json()['id'])
                if args.direct_uploads:
                    assert len(pdf) > 4.5 * 1024 * 1024
                    print('PASS: PDF larger than 4.5 MiB uploaded directly; API requests carried metadata only', flush=True)
                print('PASS: PDF and Markdown uploads queued through the real API', flush=True)
                worker = subprocess.Popen([sys.executable, '-m', 'scripts.ingestion_worker', '--poll-seconds', '1'],
                    env=env, stdout=logs, stderr=logs)
                processes.append(worker)
                def completed():
                    rows = [client.get('/ingestion-jobs/' + job, headers=owner).json() for job in queued]
                    if any(row.get('status') == 'failed' for row in rows):
                        raise RuntimeError('Synthetic ingestion failed; inspect private test logs')
                    return rows if all(row.get('status') == 'completed' for row in rows) else None
                rows = wait_for(completed)
                print('PASS: separate worker completed both jobs using real local embeddings and Neon pgvector', flush=True)
                doc_id = rows[0]['document_id']
                response = client.get(f'/documents/{doc_id}/original-pdf', headers=owner)
                assert response.status_code == 200 and response.content == pdf
                assert response.headers['cache-control'] == 'private, no-store'
                response = client.get(f'/documents/{doc_id}/original-pdf', headers={**owner, 'Range': 'bytes=0-4'})
                assert response.status_code == 206 and response.content == b'%PDF-'
                assert client.get(f'/documents/{doc_id}/original-pdf', headers=outsider).status_code == 404
                print('PASS: original PDF round-trip, byte ranges, no-store and cross-tenant denial', flush=True)
                response = client.post('/search', headers=owner,
                    json={'question': 'What approvals does Orchid calibration require?', 'top_k': 3})
                response.raise_for_status()
                hits = response.json()['hits']
                assert any(hit['document_id'] == doc_id and hit['page_number'] == 1 for hit in hits)
                response = client.post('/search', headers=outsider,
                    json={'question': 'Orchid calibration', 'top_k': 3})
                assert response.status_code == 200 and response.json()['hits'] == []
                print('PASS: real retrieval with physical page citations and tenant isolation', flush=True)
                response = client.post('/ask', headers=outsider,
                    json={'question': 'Orchid calibration', 'top_k': 3})
                assert response.status_code == 200 and response.json()['sources'] == []
                print('PASS: empty-source answer and budget accounting without a provider call', flush=True)
                os.environ.update(env)
                from app import object_storage
                for job in queued:
                    assert not object_storage.upload_exists(UUID(job))
                print('PASS: completed-job staging objects removed', flush=True)
                # Verify bucket privacy without signing or printing any URLs.
                from urllib.parse import quote
                url = env['AWS_ENDPOINT_URL_S3'].rstrip('/') + '/rag-documents/' + quote(f'originals/{doc_id}.pdf', safe='/')
                response = httpx.get(url, follow_redirects=False, timeout=30, trust_env=False)
                assert response.status_code in (401, 403, 404)
                print('PASS: unsigned original-PDF request denied by private storage', flush=True)
                print('PASS: all live Neon smoke checks; no local data imported or paid generation used', flush=True)
        return 0
    except Exception as exc:
        # Assertion labels are static, never SDK messages/tickets/credentials.
        label = str(exc) if isinstance(exc, AssertionError) else ''
        safe_labels = {'Storage preflight status', 'Storage preflight origin',
                       'Storage must enforce exact-size policy', 'Signed storage POST status', 'Storage upload origin'}
        reason = ': ' + label if label in safe_labels else ''
        print(f'FAIL: live Neon verification ({type(exc).__name__}{reason}); private synthetic logs withheld')
        return 1
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    raise SystemExit(main())
