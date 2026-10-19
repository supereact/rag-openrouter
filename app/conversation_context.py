"""Bounded, authorized chat context. This module performs no provider calls."""
from dataclasses import dataclass
import json
import re

MAX_TURNS = 4
MAX_QUESTION_CHARS = 500
MAX_ANSWER_CHARS = 1000
MAX_RETRIEVAL_CONTEXT_CHARS = 1000
_CITATIONS = re.compile(r'\[\d+\]')


@dataclass(frozen=True)
class ContextTurn:
    question: str
    answer: str
    document_ids: frozenset[int]


@dataclass(frozen=True)
class ConversationContext:
    turns: tuple[ContextTurn, ...] = ()

    @property
    def document_ids(self) -> set[int]:
        return {doc for turn in self.turns for doc in turn.document_ids}

    def retrieval_query(self, question: str) -> str:
        if not self.turns:
            return question
        # The current question comes first. Only the latest authorized turn is
        # used for retrieval; generation can use the full bounded window.
        latest = self.turns[-1]
        previous = f'{latest.question}\n{_CITATIONS.sub("", latest.answer)}'
        return f'{question}\n\nPrevious conversation topic:\n{previous[:MAX_RETRIEVAL_CONTEXT_CHARS]}'

    def prompt(self) -> str:
        # Prior citation numbers refer to different searches. Never present them
        # as usable evidence references in the current answer.
        return json.dumps([
            {'question': turn.question, 'answer': _CITATIONS.sub('', turn.answer)}
            for turn in self.turns
        ], ensure_ascii=False)
