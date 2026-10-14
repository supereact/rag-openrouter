"""Small and inspectable character-based document chunker.

A production system would normally add token-aware splitting, stable chunk IDs,
structure-aware extraction, and more rigorous text normalization.
"""


def chunk_text(raw_text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    if chunk_size < 10:
        raise ValueError("chunk_size must be at least 10")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")

    text = " ".join(raw_text.split())
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # Prefer a word boundary near the end of the current window.
            space = text.rfind(" ", start + chunk_size // 2, end)
            if space > start:
                end = space + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks
