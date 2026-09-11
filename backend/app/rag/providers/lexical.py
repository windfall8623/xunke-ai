"""Versioned Chinese/ASCII lexical projection with scoped Okapi BM25 ranking.

The small project-owned terminology dictionary plus character/bigram fallback is
deterministic and distributable. Negation, code identifiers and numbers are retained.
Updating its terms requires a new tokenizer_version and build manifest.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from app.rag.contracts import RankScore, stable_hash

TOKENIZER_VERSION = "zh-ascii-v1"
DOMAIN_TERMS = frozenset(
    {
        "协方差",
        "方差",
        "概率",
        "标准差",
        "相关系数",
        "线性",
        "独立",
        "条件",
        "否定",
        "例外",
        "光合作用",
        "叶绿体",
        "二氧化碳",
        "氧气",
        "需要",
        "定义",
        "原理",
        "成立",
        "温度",
        "实验",
        "向量",
        "检索",
        "模型",
        "学习",
        "知识",
        "参数",
        "数据",
        "接口",
        "资料",
        "生成",
        "中文",
    }
)
DICTIONARY_HASH = stable_hash(sorted(DOMAIN_TERMS))
_PARTS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\+\+|#)?|\d+(?:\.\d+)?|[\u3400-\u9fff]+")


def tokenize_for_retrieval(
    text: str, tokenizer_version: str = TOKENIZER_VERSION
) -> list[str]:
    if tokenizer_version != TOKENIZER_VERSION:
        raise ValueError("Unknown retrieval tokenizer version")
    result = []
    for match in _PARTS.finditer(text):
        part = match[0]
        if not "\u3400" <= part[0] <= "\u9fff":
            result.append(part.lower())
            continue
        i = 0
        while i < len(part):
            word = next(
                (
                    part[i : i + n]
                    for n in range(min(6, len(part) - i), 1, -1)
                    if part[i : i + n] in DOMAIN_TERMS
                ),
                None,
            )
            if word:
                result.append(word)
                i += len(word)
            else:
                result.append(part[i])
                if i + 1 < len(part):
                    result.append(part[i : i + 2])
                i += 1
    return result


class LexicalIndex:
    def __init__(
        self, records: list[dict], *, tokenizer_version: str = TOKENIZER_VERSION
    ):
        self.tokenizer_version = tokenizer_version
        self.tokens = {
            record["id"]: tokenize_for_retrieval(record["text"], tokenizer_version)
            for record in records
        }
        if len(self.tokens) != len(records):
            raise ValueError("Duplicate lexical node identity")

    def search(
        self, query: str, *, allowed_ids: set[str] | None = None, top_k: int = 20
    ) -> list[RankScore]:
        if top_k <= 0:
            return []
        # Statistics and ranking are calculated after authorization filtering.
        selected = {
            key: terms
            for key, terms in self.tokens.items()
            if allowed_ids is None or key in allowed_ids
        }
        if not selected:
            return []
        terms = set(tokenize_for_retrieval(query, self.tokenizer_version))
        n = len(selected)
        avgdl = sum(len(t) for t in selected.values()) / n or 1
        df = Counter(
            term for tokens in selected.values() for term in set(tokens) & terms
        )
        scored = []
        for identity, tokens in selected.items():
            counts = Counter(tokens)
            score = 0.0
            for term in terms & counts.keys():
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                tf = counts[term]
                score += (
                    idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * len(tokens) / avgdl))
                )
            if score > 0:
                scored.append(RankScore(id=identity, score=score))
        return sorted(scored, key=lambda item: (-item.score, item.id))[:top_k]

    def persist(self, path: str | Path) -> None:
        data = {
            "tokenizer_version": self.tokenizer_version,
            "dictionary_hash": DICTIONARY_HASH,
            "tokens": self.tokens,
        }
        payload = {**data, "checksum": stable_hash(data)}
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> LexicalIndex:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        checksum = payload.pop("checksum")
        if stable_hash(payload) != checksum:
            raise ValueError("Lexical projection checksum mismatch")
        if (
            payload["tokenizer_version"] != TOKENIZER_VERSION
            or payload["dictionary_hash"] != DICTIONARY_HASH
        ):
            raise ValueError(
                "Lexical projection requires the matching dictionary version"
            )
        result = cls([], tokenizer_version=payload["tokenizer_version"])
        result.tokens = payload["tokens"]
        return result
