"""Repository ingestion: clone/open -> filter files -> chunk -> store in Postgres.

Embeddings are NOT computed here (Step 4); chunks.embedding stays NULL for now.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Iterator

from git import Repo

from .chunker import Chunk, chunk_python
from .db import get_conn
from .docs import chunk_markdown, chunk_plain

CACHE_DIR = Path(__file__).resolve().parents[1] / "repos_cache"

SKIP_DIRS = {
    "node_modules", "venv", "env", "__pycache__", "build", "dist", "site-packages",
    "htmlcov", "migrations_cache",
}
MAX_FILE_BYTES = 300_000
MAX_CONFIG_BYTES = 50_000
CONFIG_EXT = {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"}
LOCK_NAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml", "Pipfile.lock"}


def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name in SKIP_DIRS or name.endswith(".egg-info")


def classify(path: Path) -> str | None:
    """Return a language label for files we index, else None."""
    name, ext = path.name, path.suffix.lower()
    if name in LOCK_NAMES or name.endswith(".lock"):
        return None
    if ext == ".py":
        return "python"
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext in (".rst", ".txt"):
        return "text"
    if ext in CONFIG_EXT or name in ("Dockerfile", "Makefile"):
        return "config"
    return None


def iter_source_files(root: Path, stats: Counter | None = None) -> Iterator[tuple[str, str, str]]:
    """Yield (relative_posix_path, language, text) for indexable files."""
    stats = stats if stats is not None else Counter()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not _skip_dir(d))
        for fname in sorted(files):
            full = Path(dirpath) / fname
            lang = classify(full)
            if lang is None:
                stats["skipped_type"] += 1
                continue
            try:
                size = full.stat().st_size
                limit = MAX_CONFIG_BYTES if lang == "config" else MAX_FILE_BYTES
                if size > limit or size == 0:
                    stats["skipped_size"] += 1
                    continue
                data = full.read_bytes()
                if b"\x00" in data:
                    stats["skipped_binary"] += 1
                    continue
                text = data.decode("utf-8-sig")
            except (OSError, UnicodeDecodeError):
                stats["skipped_unreadable"] += 1
                continue
            yield full.relative_to(root).as_posix(), lang, text


def chunk_file(path: str, language: str, text: str) -> list[Chunk]:
    if language == "python":
        return chunk_python(text, path)
    if language == "markdown":
        return chunk_markdown(text, path)
    return chunk_plain(text, path, "config" if language == "config" else "doc")


def open_source(source: str) -> tuple[Path, str | None, str, str | None]:
    """Return (root, commit_sha, default_name, url). Accepts https URL or local dir."""
    local = Path(source).expanduser()
    if local.is_dir():
        sha = None
        try:
            sha = subprocess.run(
                ["git", "-C", str(local), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        return local.resolve(), sha, local.resolve().name, None

    if not source.startswith(("https://", "http://")):
        raise ValueError("source must be an http(s) git URL or an existing local directory")
    name = source.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    dest = CACHE_DIR / name
    if dest.exists():
        shutil.rmtree(dest)
    CACHE_DIR.mkdir(exist_ok=True)
    repo = Repo.clone_from(source, dest, depth=1)
    return dest, repo.head.commit.hexsha, name, source


def ingest(source: str, name: str | None = None) -> dict:
    root, sha, default_name, url = open_source(source)
    name = name or default_name
    stats: Counter = Counter()

    parsed = []
    for rel, lang, text in iter_source_files(root, stats):
        parsed.append((rel, lang, text.count("\n") + 1, chunk_file(rel, lang, text)))

    kinds: Counter = Counter()
    n_symbols = n_refs = 0
    with get_conn() as conn:
        with conn.transaction():
            conn.execute("DELETE FROM repos WHERE name = %s", (name,))  # re-index
            repo_id = conn.execute(
                "INSERT INTO repos (name, url, commit_sha) VALUES (%s,%s,%s) RETURNING id",
                (name, url, sha),
            ).fetchone()[0]
            for rel, lang, n_lines, chunks in parsed:
                file_id = conn.execute(
                    "INSERT INTO files (repo_id, path, language, line_count) "
                    "VALUES (%s,%s,%s,%s) RETURNING id",
                    (repo_id, rel, lang, n_lines),
                ).fetchone()[0]
                for c in chunks:
                    chunk_id = conn.execute(
                        "INSERT INTO chunks (repo_id, file_id, path, start_line, end_line,"
                        " symbol, kind, parent, content) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (repo_id, file_id, c.path, c.start_line, c.end_line,
                         c.symbol, c.kind, c.parent, c.content),
                    ).fetchone()[0]
                    kinds[c.kind] += 1
                    if c.part != 0:
                        continue  # symbols/refs only for the first window
                    if c.kind in ("function", "method", "class"):
                        conn.execute(
                            "INSERT INTO symbols (repo_id, chunk_id, name, kind, path, line) "
                            "VALUES (%s,%s,%s,%s,%s,%s)",
                            (repo_id, chunk_id, c.symbol, c.kind, c.path, c.start_line),
                        )
                        n_symbols += 1
                    for callee in c.calls:
                        conn.execute(
                            "INSERT INTO refs (repo_id, caller_chunk_id, callee_name) "
                            "VALUES (%s,%s,%s)",
                            (repo_id, chunk_id, callee),
                        )
                        n_refs += 1
    return {
        "repo": name, "repo_id": repo_id, "commit": sha, "files": len(parsed),
        "chunks": sum(kinds.values()), "by_kind": dict(kinds),
        "symbols": n_symbols, "refs": n_refs, "skipped": dict(stats),
    }
