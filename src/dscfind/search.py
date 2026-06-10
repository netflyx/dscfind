"""A small, dependency-free BM25 ranker over the cached records."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .index import Record

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class Hit:
    record: Record
    score: float


class BM25:
    """Classic Okapi BM25. Plenty for a few thousand short documents."""

    def __init__(self, records: list[Record], k1: float = 1.5, b: float = 0.75):
        self.records = records
        self.k1, self.b = k1, b
        self.docs = [tokenize(r.haystack()) for r in records]
        self.doc_len = [len(d) for d in self.docs]
        self.avgdl = (sum(self.doc_len) / len(self.docs)) if self.docs else 0.0
        self.freqs = [Counter(d) for d in self.docs]

        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def _score(self, i: int, q_terms: list[str]) -> float:
        score = 0.0
        freq, dl = self.freqs[i], self.doc_len[i]
        for term in q_terms:
            if term not in freq:
                continue
            tf = freq[term]
            denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            score += self.idf.get(term, 0.0) * (tf * (self.k1 + 1)) / denom
        return score

    def search(self, query: str, limit: int = 10,
               course: str | None = None) -> list[Hit]:
        q_terms = tokenize(query)
        if not q_terms:
            return []
        course_norm = re.sub(r"\s+", "", course.lower()) if course else None

        hits: list[Hit] = []
        for i, rec in enumerate(self.records):
            if course_norm and course_norm not in re.sub(
                r"\s+", "", rec.course_code.lower()
            ):
                continue
            s = self._score(i, q_terms)
            if s > 0:
                # Small bonus when query words appear in the title itself.
                title_tokens = set(tokenize(rec.title))
                s += 0.3 * sum(1 for t in q_terms if t in title_tokens)
                hits.append(Hit(record=rec, score=s))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]
