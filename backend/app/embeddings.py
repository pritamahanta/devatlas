"""Embedding backends. Vectors are L2-normalised so cosine distance (<=>) works."""
from __future__ import annotations

import re
import zlib
from typing import Protocol

import numpy as np

from .config import settings
from .textutil import split_identifier

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Local model (default BAAI/bge-small-en-v1.5). Imported lazily: needs torch."""

    def __init__(self, model_name: str, dim: int):
        from sentence_transformers import SentenceTransformer  # heavy import

        self.model = SentenceTransformer(model_name)
        self.dim = dim

    def _encode(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(
            texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False
        ).astype(np.float32)
        if vecs.shape[1] != self.dim:
            raise ValueError(
                f"Model outputs {vecs.shape[1]} dims but the schema/config expects {self.dim}. "
                "Change EMBED_DIM and the vector(N) column together."
            )
        return vecs

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([settings.query_prefix + text])[0]


class HashingEmbedder:
    """Offline bag-of-words hashing embedder for tests/CI. Lexical only, NOT semantic."""

    def __init__(self, dim: int):
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in _TOKEN.findall(text):
            for w in split_identifier(tok) or [tok.lower()]:
                h = zlib.crc32(w.encode())
                v[h % self.dim] += 1.0 if (zlib.crc32(b"s" + w.encode()) & 1) else -1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        if settings.embed_backend == "hash":
            _embedder = HashingEmbedder(settings.embed_dim)
        else:
            _embedder = SentenceTransformerEmbedder(settings.embed_model, settings.embed_dim)
    return _embedder


def set_embedder(e: Embedder | None) -> None:
    """Override (or reset with None) the process-wide embedder; used by tests."""
    global _embedder
    _embedder = e
