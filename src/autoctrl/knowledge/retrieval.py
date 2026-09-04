from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .corpus import ROS2_KNOWLEDGE


_LATIN_TOKEN = re.compile(r"[a-z0-9_./-]+")
_CHINESE_RUN = re.compile(r"[\u3400-\u9fff]+")


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    id: str
    title: str
    content: str
    source_url: str
    keywords: tuple[str, ...]

    def prompt_text(self) -> str:
        return f"[{self.id}] {self.title}\n{self.content}\nSource: {self.source_url}"


@dataclass(frozen=True, slots=True)
class KnowledgeMatch:
    chunk: KnowledgeChunk
    score: float


class Ros2KnowledgeBase:
    def __init__(self, chunks: tuple[KnowledgeChunk, ...]) -> None:
        self._chunks = chunks

    @classmethod
    def builtins(cls) -> Ros2KnowledgeBase:
        return cls(
            tuple(
                KnowledgeChunk(
                    id=item["id"],
                    title=item["title"],
                    content=item["content"],
                    source_url=item["source_url"],
                    keywords=tuple(item["keywords"]),
                )
                for item in ROS2_KNOWLEDGE
            )
        )

    @property
    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        return self._chunks

    def search(
        self, query: str, *, limit: int = 3, minimum_score: float = 3.0
    ) -> tuple[KnowledgeMatch, ...]:
        normalized_query = _normalize(query)
        query_terms = _terms(normalized_query)
        matches: list[KnowledgeMatch] = []
        for chunk in self._chunks:
            haystack = _normalize(
                " ".join((chunk.title, chunk.content, *chunk.keywords))
            )
            score = sum(5.0 for keyword in chunk.keywords if _normalize(keyword) in normalized_query)
            score += sum(1.0 for term in query_terms if term in haystack)
            if score >= minimum_score:
                matches.append(KnowledgeMatch(chunk=chunk, score=score))
        matches.sort(key=lambda item: (-item.score, item.chunk.id))
        return tuple(matches[:limit])


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().strip()


def _terms(text: str) -> set[str]:
    terms = set(_LATIN_TOKEN.findall(text))
    for run in _CHINESE_RUN.findall(text):
        if len(run) == 1:
            terms.add(run)
        else:
            terms.update(run[index : index + 2] for index in range(len(run) - 1))
    return terms
