"""Explicitly replace ONLY the four bundled demo documents.

Usage: python -m scripts.reindex_samples --confirm
Does not drop tables or touch other document titles.
"""
import argparse
from pathlib import Path
from app.db import db_connection
from app.services import ingest_document

SAMPLES = Path(__file__).resolve().parents[1] / 'sample_docs'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    if not args.confirm:
        parser.error('Pass --confirm to replace bundled demo documents')
    files = sorted(SAMPLES.glob('*.txt'))
    if not files:
        raise RuntimeError('No bundled .txt demo documents found')
    # Delete only exact demo titles, and only after the user explicitly opts in.
    # The existing ingest_document() uses a content hash to avoid duplicates;
    # replacing demo documents is necessary to update stored chunk boundaries.
    for file in files:
        title = file.stem.replace('_', ' ').title()
        text = file.read_text(encoding='utf-8')
        if 'DEMO DOCUMENT' not in text:
            raise RuntimeError(f'Refusing to replace non-demo file: {file}')
        with db_connection() as conn:
            conn.execute('DELETE FROM documents WHERE title = %s AND EXISTS '
                         '(SELECT 1 FROM chunks WHERE document_id = documents.id '
                         'AND content LIKE %s)', (title, '%DEMO DOCUMENT%'))
        doc_id, count, existed = ingest_document(title, text)
        print(f'{title}: id={doc_id}, chunks={count}, existed={existed}')


if __name__ == '__main__':
    main()
