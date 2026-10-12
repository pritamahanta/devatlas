"""Hybrid retrieval: vector + keyword (Postgres FTS) + symbol lookup, fused with RRF.

Note: keyword search uses Postgres full-text ranking (ts_rank_cd). It is a
lexical ranker but NOT BM25 (no BM25 length/IDF formula).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import settings
from .embeddings import get_embedder
from .textutil import STOPWORDS, split_identifier

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MODES = ("hybrid", "vector", "keyword", "symbol", "vector+keyword")  # last: RRF without symbol lookup


@dataclass
class Hit:
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    kind: str
    parent: str | None
    symbol: str | None
    content: str
    score: float
    sources: dict[str, int] = field(default_factory=dict)  # retriever -> 1-indexed rank


def get_repo_id(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM repos WHERE name = %s", (name,)).fetchone()
    if row is None:
        raise KeyError(f"repo not found: {name}")
    return row[0]


def rrf(ranked_lists: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank)."""
    scores: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, doc_id in enumerate(lst, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _variants(w: str) -> list[str]:
    """Crude query-side stemming (the index uses the 'simple' config: no stemming).
    Extra terms are OR-ed in, so a wrong guess only adds a harmless miss."""
    out: list[str] = []
    if w.endswith("ies") and len(w) > 4:
        out.append(w[:-3] + "y")
    elif w.endswith("ing") and len(w) > 5:
        out += [w[:-3], w[:-3] + "e"]
    elif w.endswith("ed") and len(w) > 4:
        out += [w[:-2], w[:-1]]
    elif w.endswith("es") and len(w) > 4:
        out += [w[:-1], w[:-2]]
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        out.append(w[:-1])
    return out


def keyword_terms(query: str, limit: int = 24) -> list[str]:
    """Terms matching how the tsvector is built (identifier separators -> spaces).
    snake_case splits into parts; camelCase stays one lowercase token AND is split."""
    terms: list[str] = []
    seen: set[str] = set()

    def add(t: str):
        if len(t) >= 2 and t not in STOPWORDS and t not in seen:
            seen.add(t)
            terms.append(t)

    for tok in _IDENT.findall(query):
        if "_" not in tok:
            add(tok.lower())            # e.g. getUserById -> getuserbyid, userid
        for part in split_identifier(tok):
            add(part)
            for v in _variants(part):
                add(v)
    return terms[:limit]


def vector_search(conn, repo_id: int, query: str, n: int) -> list[int]:
    qvec = get_embedder().embed_query(query)
    conn.execute(f"SET LOCAL hnsw.ef_search = {int(settings.hnsw_ef_search)}")
    rows = conn.execute(
        "SELECT id FROM chunks WHERE repo_id = %s AND embedding IS NOT NULL "
        "ORDER BY embedding <=> %s LIMIT %s", (repo_id, qvec, n)
    ).fetchall()
    return [r[0] for r in rows]


def keyword_search(conn, repo_id: int, query: str, n: int) -> list[int]:
    terms = keyword_terms(query)
    if not terms:
        return []
    tsq = " | ".join(terms)  # terms are [a-z0-9] only, safe for to_tsquery
    rows = conn.execute(
        "SELECT id FROM chunks WHERE repo_id = %s AND tsv @@ to_tsquery('simple', %s) "
        "ORDER BY ts_rank_cd(tsv, to_tsquery('simple', %s), 1) DESC, id LIMIT %s",
        (repo_id, tsq, tsq, n),
    ).fetchall()
    return [r[0] for r in rows]


def symbol_search(conn, repo_id: int, query: str, n: int) -> list[int]:
    """Definitions whose name exactly matches an identifier-like token in the query."""
    names, seen = [], set()
    for tok in _IDENT.findall(query):
        if len(tok) >= 3 and tok.lower() not in STOPWORDS and tok not in seen:
            seen.add(tok)
            names.append(tok)
    if not names:
        return []
    rows = conn.execute(
        "SELECT chunk_id, name FROM symbols WHERE repo_id = %s AND name = ANY(%s)",
        (repo_id, names),
    ).fetchall()
    order = {nm: i for i, nm in enumerate(names)}  # follow query order
    rows.sort(key=lambda r: (order[r[1]], r[0]))
    out: list[int] = []
    for chunk_id, _ in rows:
        if chunk_id not in out:
            out.append(chunk_id)
    return out[:n]


def search(conn, repo_id: int, query: str, k: int = 8, mode: str = "hybrid") -> list[Hit]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    n = settings.candidates_per_retriever
    lists: dict[str, list[int]] = {}
    if mode in ("hybrid", "vector"):
        lists["vector"] = vector_search(conn, repo_id, query, n)
    if mode in ("hybrid", "keyword"):
        lists["keyword"] = keyword_search(conn, repo_id, query, n)
    if mode in ("hybrid", "symbol"):
        lists["symbol"] = symbol_search(conn, repo_id, query, n)

    fused = rrf(list(lists.values()), settings.rrf_k)[:k]
    if not fused:
        return []
    rows = conn.execute(
        "SELECT id, path, start_line, end_line, kind, parent, symbol, content "
        "FROM chunks WHERE id = ANY(%s)", ([cid for cid, _ in fused],)
    ).fetchall()
    by_id = {r[0]: r for r in rows}
    hits = []
    for cid, score in fused:
        _, path, s, e, kind, parent, symbol, content = by_id[cid]
        sources = {name: lst.index(cid) + 1 for name, lst in lists.items() if cid in lst}
        hits.append(Hit(cid, path, s, e, kind, parent, symbol, content, round(score, 5), sources))
    return hits
