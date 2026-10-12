from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from .db import get_conn
from .embeddings import get_embedder
from .retrieval import get_repo_id, search

SNIPPET_CHARS = 800


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_embedder()  # load the model once at startup, not on the first request
    yield


app = FastAPI(title="DevAtlas", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/repos")
def repos():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.id, r.name, r.url, r.commit_sha, r.indexed_at, "
            " (SELECT count(*) FROM files f WHERE f.repo_id = r.id), "
            " (SELECT count(*) FROM chunks c WHERE c.repo_id = r.id), "
            " (SELECT count(*) FROM chunks c WHERE c.repo_id = r.id AND c.embedding IS NOT NULL) "
            "FROM repos r ORDER BY r.name"
        ).fetchall()
    keys = ("id", "name", "url", "commit_sha", "indexed_at", "files", "chunks", "embedded_chunks")
    return [dict(zip(keys, r)) for r in rows]


@app.get("/search")
def search_endpoint(
    repo: str,
    q: str = Query(min_length=1),
    k: int = Query(8, ge=1, le=30),
    mode: Literal["hybrid", "vector", "keyword", "symbol"] = "hybrid",
):
    with get_conn() as conn:
        try:
            repo_id = get_repo_id(conn, repo)
        except KeyError:
            raise HTTPException(404, f"repo not found: {repo}")
        hits = search(conn, repo_id, q, k, mode)
    out = []
    for h in hits:
        d = asdict(h)
        d["snippet"] = d.pop("content")[:SNIPPET_CHARS]
        out.append(d)
    return {"repo": repo, "query": q, "mode": mode, "hits": out}
