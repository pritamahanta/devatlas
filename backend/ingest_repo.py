"""Step 3: python ingest_repo.py <https-git-url | local-dir> [--name NAME] [--embed]

Step 8 (evaluation baseline): add --chunker fixed to index the same source with
naive fixed-size line windows; it is stored as "<name>@fixed".
"""
import argparse
import json

from app.baseline import DEFAULT_OVERLAP, DEFAULT_WINDOW
from app.ingest import ingest

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--name")
ap.add_argument("--embed", action="store_true", help="also embed chunks (Step 4)")
ap.add_argument("--chunker", choices=("ast", "fixed"), default="ast",
                help="'fixed' = evaluation baseline (Python files only)")
ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="fixed chunker: lines per chunk")
ap.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP, help="fixed chunker: overlapping lines")
args = ap.parse_args()
summary = ingest(args.source, args.name, args.chunker, args.window, args.overlap)
print(json.dumps(summary, indent=2))
if args.embed:
    from app.embed import embed_repo
    embed_repo(summary["repo"])
