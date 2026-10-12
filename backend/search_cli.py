"""Step 4 checkpoint: python search_cli.py <repo-name> "<question>" [--mode hybrid] [-k 8]"""
import argparse

from app.db import get_conn
from app.retrieval import MODES, get_repo_id, search

ap = argparse.ArgumentParser()
ap.add_argument("repo")
ap.add_argument("query")
ap.add_argument("--mode", default="hybrid", choices=MODES)
ap.add_argument("-k", type=int, default=8)
a = ap.parse_args()

with get_conn() as conn:
    hits = search(conn, get_repo_id(conn, a.repo), a.query, a.k, a.mode)
for i, h in enumerate(hits, 1):
    qual = f"{h.parent}.{h.symbol}" if h.parent else (h.symbol or "-")
    src = " ".join(f"{n}#{r}" for n, r in h.sources.items())
    print(f"{i:>2}. {h.score:.4f}  {h.kind:<8} {h.path}:{h.start_line}-{h.end_line}  {qual}  [{src}]")
if not hits:
    print("no hits (did you run embed_repo.py / ingest with --embed?)")
