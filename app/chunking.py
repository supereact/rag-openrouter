"""Paragraph- and sentence-aware character-budget chunking.

The budget is in characters, not model tokens. Overlap copies complete words.
"""
import re

_SENTENCES = re.compile(r'(?<=[.!?])\s+(?=["\'“‘(]*[A-Z0-9])')


def _words_fit(text: str, size: int) -> list[str]:
    words = text.split()
    out, current = [], ''
    for word in words:
        if len(word) > size:
            raise ValueError(f'One word exceeds chunk_size ({size} characters)')
        candidate = f'{current} {word}' if current else word
        if len(candidate) > size and current:
            out.append(current)
            current = word
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def _units(text: str, size: int) -> list[str]:
    paragraphs = re.split(r'\n\s*\n+', text.strip())
    units = []
    for paragraph in paragraphs:
        paragraph = ' '.join(paragraph.split())
        if not paragraph:
            continue
        if len(paragraph) <= size:
            units.append(paragraph)
            continue
        for sentence in _SENTENCES.split(paragraph):
            if len(sentence) <= size:
                units.append(sentence)
            else:
                units.extend(_words_fit(sentence, size))
    return units


def _tail_words(text: str, max_chars: int) -> str:
    if max_chars == 0:
        return ''
    chosen = []
    for word in reversed(text.split()):
        candidate = ' '.join(reversed([*chosen, word]))
        if len(candidate) > max_chars:
            break
        chosen.append(word)
    return ' '.join(reversed(chosen))


def chunk_text(raw_text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    if chunk_size < 10:
        raise ValueError('chunk_size must be at least 10')
    if not 0 <= overlap < chunk_size:
        raise ValueError('overlap must satisfy 0 <= overlap < chunk_size')
    units = _units(raw_text, chunk_size)
    if not units:
        return []
    chunks = []
    current = ''
    for unit in units:
        combined = f'{current} {unit}' if current else unit
        if len(combined) <= chunk_size:
            current = combined
            continue
        if current:
            chunks.append(current)
        tail = _tail_words(current, overlap)
        candidate = f'{tail} {unit}' if tail else unit
        # Never let overlap consume the whole new chunk or exceed the budget.
        while tail and len(candidate) > chunk_size:
            tail = tail.split(' ', 1)[1] if ' ' in tail else ''
            candidate = f'{tail} {unit}' if tail else unit
        current = candidate
    if current:
        chunks.append(current)
    return chunks
