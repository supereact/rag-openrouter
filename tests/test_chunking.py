import pytest
from app.chunking import chunk_text


def test_empty_document():
    assert chunk_text("  \n \t") == []


def test_small_document():
    assert chunk_text("This is a very short example.") == ["This is a very short example."]


def test_long_document_is_split():
    text = " ".join([f"sentence{i}" for i in range(300)])
    parts = chunk_text(text, chunk_size=100, overlap=20)
    assert len(parts) > 2
    assert all(0 < len(p) <= 100 for p in parts)
    assert "sentence0" in parts[0]
    assert "sentence299" in parts[-1]


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("test", chunk_size=20, overlap=20)
