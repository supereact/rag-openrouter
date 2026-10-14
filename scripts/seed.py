from pathlib import Path
from app.services import ingest_document

SAMPLES = Path(__file__).resolve().parents[1] / "sample_docs"

if __name__ == "__main__":
    for file in sorted(SAMPLES.glob("*.txt")):
        doc_id, count, existed = ingest_document(
            title=file.stem.replace("_", " ").title(),
            text=file.read_text(encoding="utf-8"),
        )
        print(f"{file.name}: document {doc_id}, {count} new chunks, existing={existed}")
