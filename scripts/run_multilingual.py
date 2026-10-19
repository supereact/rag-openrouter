"""Start a local API or worker with matching, cached multilingual models.

Use only after the approved all-chunk re-embedding has completed successfully.
Existing .env secrets and other settings still load normally; this launcher sets
only the model/cache settings before importing any application modules.
"""
import argparse
import os
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=['api', 'worker'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    os.environ.update({
        'EMBEDDING_MODEL': 'intfloat/multilingual-e5-small',
        'RERANKER_MODEL': 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1',
        'RAG_RETRIEVAL_MODE': 'rerank',
        'HF_HOME': str(Path(__file__).resolve().parents[1] / '.model_cache'),
        'HF_HUB_OFFLINE': '1',
    })
    # exec preserves signals, exit codes, and the caller's foreground terminal.
    command = (['uvicorn', 'app.main:app'] if args.service == 'api'
               else ['scripts.ingestion_worker'])
    os.execv(sys.executable, [sys.executable, '-m', *command, *args.arguments])


if __name__ == '__main__':
    main()
