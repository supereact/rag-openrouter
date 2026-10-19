"""Plan or explicitly apply a model change without replacing documents/chunks.

Default invocation only counts rows. No content, vectors, credentials, or provider
calls are printed. Apply only during an approved API/worker maintenance window.
"""
import argparse
import json

from app.db import db_connection

DEFAULT_MODEL = 'intfloat/multilingual-e5-small'


def plan(model_name: str) -> dict:
    with db_connection() as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        row = conn.execute('''SELECT count(*),count(DISTINCT document_id)
                              FROM chunks''').fetchone()
    return dict(model=model_name, chunks=int(row[0]), documents=int(row[1]),
                dimensions=384, applied=False)


def apply(model_name: str, expected_chunks: int, batch_size: int = 32) -> dict:
    if batch_size < 1 or expected_chunks < 0:
        raise ValueError('Invalid batch size or expected chunk count')
    from app.embeddings import embed_many
    # Download/check the model before taking locks. This is local inference,
    # never an external embedding API; no document text leaves this process.
    embed_many(['Model compatibility check'], model_name=model_name)
    updated, last_id = 0, 0
    with db_connection() as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute('LOCK TABLE documents,chunks IN SHARE ROW EXCLUSIVE MODE')
        count = conn.execute('SELECT count(*) FROM chunks').fetchone()[0]
        if count != expected_chunks:
            raise ValueError('Chunk count changed; run the read-only plan again')
        while True:
            rows = conn.execute('''SELECT id,content FROM chunks WHERE id>%s
                                   ORDER BY id LIMIT %s''', (last_id, batch_size)).fetchall()
            if not rows:
                break
            vectors = embed_many([row[1] for row in rows], model_name=model_name)
            with conn.cursor() as cursor:
                cursor.executemany('UPDATE chunks SET embedding=%s WHERE id=%s',
                                   [(vector, row[0]) for row, vector in zip(rows, vectors)])
            updated += len(rows)
            last_id = rows[-1][0]
        if updated != count:
            raise RuntimeError('Incomplete re-embedding; all changes rolled back')
    return dict(model=model_name, chunks=updated, dimensions=384, applied=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-chunks', type=int)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--confirm-services-stopped', action='store_true')
    args = parser.parse_args()
    if args.apply and (not args.confirm_services_stopped or args.expected_chunks is None):
        parser.error('--apply requires --confirm-services-stopped and --expected-chunks from a reviewed plan')
    try:
        result = (apply(args.model, args.expected_chunks, args.batch_size)
                  if args.apply else plan(args.model))
    except Exception as exc:
        # Database/provider exception strings can contain connection details.
        print(json.dumps({'applied': False, 'error_type': type(exc).__name__,
                          'message': 'Operation failed; no partial vector updates were committed.'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
