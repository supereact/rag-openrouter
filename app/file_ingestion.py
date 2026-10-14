"""Extract UTF-8 text, Markdown, or text-based PDF documents for local RAG."""
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000
MAX_PDF_PAGES = 300
ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}


def extract_document(filename: str, data: bytes) -> tuple[str, str]:
    """Return a safe filename and extracted text; raise ValueError on bad input."""
    # Filename is metadata only. Never use this to construct a disk path.
    name = Path(filename.replace("\\", "/")).name
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Only .txt, .md, and .pdf files are supported")
    if not data:
        raise ValueError("The uploaded file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 10 MB upload limit")

    if extension == ".pdf":
        try:
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError("PDF exceeds the 100-page limit")
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Could not read PDF content") from exc
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Text and Markdown files must be UTF-8") from exc

    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("Extracted text exceeds the 200,000-character limit")
    if len(text.strip()) < 20:
        raise ValueError("No readable text found (scanned PDFs require OCR)")
    return name, text
