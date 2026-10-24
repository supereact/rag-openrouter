"""Standalone ingestion worker: python -m scripts.ingestion_worker"""
import argparse
import logging
import signal
from threading import Event

from app.embeddings import embed_many
from app.ingestion_jobs import process_one_job

logger = logging.getLogger('rag.ingestion.worker')


def run_worker(stop: Event, *, once: bool = False, poll_seconds: float = 2.0) -> None:
    """Drain the current job on shutdown; never claim another after it finishes."""
    if stop.is_set():
        return
    logger.info('Loading embedding model in ingestion worker...')
    embed_many(['Document ingestion worker warm-up'])
    logger.info('Worker ready (bounded transient retries and heartbeat enabled)')
    while not stop.is_set():
        try:
            processed = process_one_job()
        except Exception:
            logger.exception('Queue/worker infrastructure error')
            if once:
                raise
            stop.wait(poll_seconds)
            continue
        if once:
            return
        if not processed:
            stop.wait(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Process at most one job, then exit')
    parser.add_argument('--poll-seconds', type=float, default=2.0)
    args = parser.parse_args()
    if not 0.2 <= args.poll_seconds <= 60:
        parser.error('--poll-seconds must be between 0.2 and 60')
    logging.basicConfig(level=logging.INFO)
    stop = Event()
    previous = {kind: signal.getsignal(kind) for kind in (signal.SIGTERM, signal.SIGINT)}
    try:
        for kind in previous:
            signal.signal(kind, lambda _number, _frame: stop.set())
        run_worker(stop, once=args.once, poll_seconds=args.poll_seconds)
    finally:
        for kind, handler in previous.items():
            signal.signal(kind, handler)
    logger.info('Worker stopped after draining current work')


if __name__ == '__main__':
    main()
