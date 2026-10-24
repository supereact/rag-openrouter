"""Run the existing worker with the model bundle shipped in its image."""
from pathlib import Path

from app.hosted_runtime import configure


def main() -> None:
    configure(Path(__file__).resolve().parents[1])
    from scripts.ingestion_worker import main as worker
    worker()


if __name__ == '__main__':
    main()
