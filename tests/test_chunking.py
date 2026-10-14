import pytest
from app.chunking import chunk_text


def test_empty_document():
    assert chunk_text('  \n \t') == []


def test_small_document():
    assert chunk_text('This is a very short example.') == ['This is a very short example.']


def test_long_document_is_split():
    text = ' '.join(f'sentence{i}' for i in range(300))
    parts = chunk_text(text, chunk_size=100, overlap=20)
    assert len(parts) > 2
    assert all(0 < len(p) <= 100 for p in parts)
    assert 'sentence0' in parts[0]
    assert 'sentence299' in parts[-1]


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text('test', chunk_size=20, overlap=20)


def test_never_breaks_words():
    text = 'The network operations team can review VPN gateway health and firewall rules. '
    parts = chunk_text(text * 5, chunk_size=85, overlap=18)
    assert all(not part.startswith('eam ') for part in parts)
    assert all(len(part) <= 85 for part in parts)


def test_preserves_sentence_when_possible():
    text = 'First sentence is here. Second sentence is here. Third sentence is here.'
    parts = chunk_text(text, chunk_size=50, overlap=0)
    assert parts == ['First sentence is here. Second sentence is here.', 'Third sentence is here.']


def test_rejects_unbreakable_oversized_word():
    with pytest.raises(ValueError, match='One word exceeds'):
        chunk_text('x' * 101, chunk_size=100, overlap=10)
