"""Step 8 labelling aid: python validate_golden.py <golden.jsonl> [--show]

Checks the golden set parses, every gold file exists in the indexed repo and every
line range lies inside it. With --show, prints the gold lines of each question so
you can eyeball that the labels really answer the question (do this once per label).
"""
import argparse
import sys
from collections import Counter

from app import evaluation as ev
from app.db import get_conn

ap = argparse.ArgumentParser()
ap.add_argument("golden")
ap.add_argument("--show", action="store_true", help="print the gold code for every question")
ap.add_argument("--lines", type=int, default=12, help="max lines shown per gold range")
args = ap.parse_args()

try:
    questions = ev.load_golden(args.golden)
except ValueError as e:
    sys.exit(str(e))

with get_conn() as conn:
    problems = ev.validate_against_index(conn, questions)
    if args.show:
        for q in questions:
            print(f"\n[{q.id}] ({q.category}) {q.repo}: {q.text}")
            for g in q.gold:
                print(f" gold {g.path}:{g.start}-{g.end}")
                print(ev.gold_snippet(conn, q.repo, g, args.lines))

print(f"\n{len(questions)} questions")
for repo, n in sorted(Counter(q.repo for q in questions).items()):
    print(f"  {repo}: {n}")
print("  by category: " + ", ".join(f"{c}={n}" for c, n in sorted(Counter(q.category for q in questions).items())))
warnings = ev.oversized_gold(questions)
if warnings:
    print("\nWARNING: large gold ranges are easy to hit with any chunking; consider narrowing:")
    for w in warnings:
        print("  " + w)
if problems:
    print("\nPROBLEMS:")
    for p in problems:
        print("  " + p)
    sys.exit(1)
print("OK: all gold ranges exist in the index")
