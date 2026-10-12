"""Step 3: python ingest_repo.py <https-git-url | local-dir> [--name NAME]"""
import argparse
import json

from app.ingest import ingest

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--name")
args = ap.parse_args()
print(json.dumps(ingest(args.source, args.name), indent=2))
