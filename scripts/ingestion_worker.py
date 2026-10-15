"""Standalone ingestion worker: python -m scripts.ingestion_worker"""
import argparse
import logging
import time

from app.embeddings import embed_many
from app.ingestion_jobs import process_one_job

logger = logging.getLogger('rag.ingestion.worker')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Process at most one job, then exit')
    parser.add_argument('--poll-seconds', type=float, default=2.0)
    args = parser.parse_args()
    if not 0.2 <= args.poll_seconds <= 60:
        parser.error('--poll-seconds must be between 0.2 and 60')
    logging.basicConfig(level=logging.INFO)
    logger.info('Loading embedding model in ingestion worker...')
    embed_many(['Document ingestion worker warm-up'])
    logger.info('Worker ready (bounded transient retries and heartbeat enabled)')
    while True:
        try:
            processed = process_one_job()
        except Exception:
            logger.exception('Queue/worker infrastructure error')
            if args.once:
                raise
            time.sleep(args.poll_seconds)
            continue
        if args.once:
            return
        if not processed:
            time.sleep(args.poll_seconds)


if __name__ == '__main__':
    main()
