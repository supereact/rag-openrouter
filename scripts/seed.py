from pathlib import Path
from app.services import ingest_document
from app.security import local_admin_principal

SAMPLES = Path(__file__).resolve().parents[1] / "sample_docs"

if __name__ == "__main__":
    principal = local_admin_principal()
    for file in sorted(SAMPLES.glob("*.txt")):
        doc_id, count, existed = ingest_document(
            title=file.stem.replace("_", " ").title(),
            text=file.read_text(encoding="utf-8"),
            principal=principal,
        )
        print(f"{file.name}: document {doc_id}, {count} new chunks, existing={existed}")
