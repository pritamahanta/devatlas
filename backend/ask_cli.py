"""Step 5 checkpoint: python ask_cli.py <repo-name> "<question>" [--mode hybrid] [-k 8]
Needs an LLM key in backend/.env (see .env.example)."""
import argparse

from app.answer import answer_question
from app.retrieval import MODES

ap = argparse.ArgumentParser()
ap.add_argument("repo")
ap.add_argument("question")
ap.add_argument("--mode", default="hybrid", choices=MODES)
ap.add_argument("-k", type=int, default=8)
a = ap.parse_args()

r = answer_question(a.repo, a.question, a.k, a.mode)
print(r["answer"])
print("\n--- citations (validated) ---")
for c in r["citations"]:
    print(f"  {c['path']}:{c['start_line']}-{c['end_line']}  {c['symbol'] or ''}")
if r["invalid_citations"]:
    print("--- removed (not in retrieved lines) ---")
    for c in r["invalid_citations"]:
        print(f"  {c}")
print(f"\nmodel={r['model']}  sources_shown={len(r['sources'])}")
