"""Step 3: python ingest_repo.py <https-git-url | local-dir> [--name NAME]"""
import argparse
import json

from app.ingest import ingest

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--name")
ap.add_argument("--embed", action="store_true", help="also embed chunks (Step 4)")
args = ap.parse_args()
summary = ingest(args.source, args.name)
print(json.dumps(summary, indent=2))
if args.embed:
    from app.embed import embed_repo
    embed_repo(summary["repo"])
