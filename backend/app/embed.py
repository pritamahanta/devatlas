"""Embed all not-yet-embedded chunks of a repo."""
from __future__ import annotations

from .chunker import build_embed_text
from .db import get_conn
from .embeddings import get_embedder


def embed_repo(name: str, batch_size: int = 64, progress=print) -> int:
    emb = get_embedder()
    done = 0
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM repos WHERE name = %s", (name,)).fetchone()
        if row is None:
            raise KeyError(f"repo not found: {name}")
        rows = conn.execute(
            "SELECT id, path, kind, parent, symbol, content FROM chunks "
            "WHERE repo_id = %s AND embedding IS NULL ORDER BY id", (row[0],)
        ).fetchall()
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            vecs = emb.embed_documents(
                [build_embed_text(p, k, par, sym, content) for _, p, k, par, sym, content in batch]
            )
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE chunks SET embedding = %s WHERE id = %s",
                    [(vecs[j], batch[j][0]) for j in range(len(batch))],
                )
            conn.commit()  # keep progress if interrupted
            done += len(batch)
            progress(f"embedded {done}/{len(rows)}")
    return done
