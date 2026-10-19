"""Small Han-script helpers; no external tokenizer or database extension."""
import re

HAN = '\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f'
_HAN = re.compile(f'[{HAN}]')
_RUNS = re.compile(f'[{HAN}]+|[A-Za-z0-9_]+')
_ATOMS = re.compile(f'[{HAN}]|[A-Za-z0-9_]+|[^\\sA-Za-z0-9_{HAN}]|\\s+')


def contains_han(text: str) -> bool:
    return _HAN.search(text) is not None


def search_terms(question: str, limit: int = 64) -> list[str]:
    """Literal overlapping bigrams avoid assuming whitespace separates Chinese.

    This is lexical matching, not linguistic word segmentation or translation.
    Terms are always bound as SQL values, never interpolated into SQL syntax.
    """
    terms = []
    for run in _RUNS.findall(question):
        pieces = ([run[i:i + 2] for i in range(len(run) - 1)]
                  if contains_han(run) and len(run) > 1 else [run.lower()])
        for term in pieces:
            if term not in terms:
                terms.append(term)
            if len(terms) >= limit:
                return terms
    return terms


def chunk_han(text: str, chunk_size: int, overlap: int) -> list[str]:
    # Keep Chinese passages shorter to reduce multilingual tokenizer truncation.
    size = min(chunk_size, 256)
    overlap = min(overlap, size // 3)
    tokens = _ATOMS.findall(' '.join(text.split()))
    if any(len(token) > chunk_size for token in tokens):
        raise ValueError(f'One word exceeds chunk_size ({chunk_size} characters)')
    parts, start = [], 0
    while start < len(tokens):
        end, length, sentence_end = start, 0, None
        # Preserve a Latin word that fits the caller's budget but exceeds the
        # shorter Chinese target, rather than rejecting previously valid input.
        budget = max(size, len(tokens[start]))
        while end < len(tokens) and length + len(tokens[end]) <= budget:
            length += len(tokens[end])
            end += 1
            if tokens[end - 1] in '。！？；' and length >= budget // 2:
                sentence_end = end
        if end < len(tokens) and sentence_end is not None:
            end = sentence_end
        part = ''.join(tokens[start:end]).strip()
        if part:
            parts.append(part)
        if end == len(tokens):
            break
        following, copied = end, 0
        while following > start + 1 and copied + len(tokens[following - 1]) <= overlap:
            following -= 1
            copied += len(tokens[following])
        start = following
    return parts
