"""Step 4: python embed_repo.py <repo-name>"""
import sys

from app.embed import embed_repo

if len(sys.argv) != 2:
    sys.exit("usage: python embed_repo.py <repo-name>")
print(f"done: {embed_repo(sys.argv[1])} chunks embedded")
