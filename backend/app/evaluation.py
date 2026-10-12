"""Retrieval evaluation (Step 8): golden questions -> hit@k, recall@k, MRR.

Definitions (keep these in mind when quoting numbers):
- A golden question lists one or more GOLD RANGES: the file + line range(s) a
  reader needs in order to answer it.
- A retrieved chunk is a HIT for a gold range if it is in the same file and its
  line range overlaps the gold range by at least one line. Overlap (not chunk
  identity) is what lets different chunking strategies be compared fairly.
- hit@k    = 1 if ANY gold range is hit within the top k chunks, else 0.
- recall@k = fraction of the question's gold ranges hit within the top k.
- MRR      = 1 / rank of the first hit (0 if none in the top K_MAX).
Larger chunks overlap more easily, so this definition slightly FAVOURS the
fixed-size baseline when its chunks are bigger than the AST chunks; the report
prints average chunk sizes so that can be checked.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .baseline import FIXED_SUFFIX
from .retrieval import get_repo_id, search

KS = (1, 3, 5, 10)
K_MAX = max(KS)
CATEGORIES = ("lookup", "behavior", "multi")  # where is X / how does X work / spans several places


class EvalSetupError(RuntimeError):
    pass


# ---------- golden set ----------

@dataclass(frozen=True)
class Gold:
    path: str
    start: int
    end: int


@dataclass(frozen=True)
class Question:
    id: str
    repo: str
    text: str
    category: str
    gold: tuple[Gold, ...]


def load_golden(path: str | Path) -> list[Question]:
    """Read a JSONL golden set (blank lines and lines starting with '#' are ignored).
    All problems are collected and reported together, with line numbers."""
    questions: list[Question] = []
    errors: list[str] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            d = json.loads(line)
            qid, repo, text = str(d["id"]), str(d["repo"]), str(d["question"]).strip()
            category = str(d["category"])
            gold = tuple(Gold(str(g["path"]), int(g["start"]), int(g["end"])) for g in d["gold"])
        except (ValueError, KeyError, TypeError) as e:
            errors.append(f"line {lineno}: {type(e).__name__}: {e}")
            continue
        if not text:
            errors.append(f"line {lineno}: empty question")
        if category not in CATEGORIES:
            errors.append(f"line {lineno} ({qid}): category must be one of {CATEGORIES}")
        if not gold:
            errors.append(f"line {lineno} ({qid}): gold must list at least one range")
        for g in gold:
            if g.start < 1 or g.end < g.start:
                errors.append(f"line {lineno} ({qid}): bad range {g.path}:{g.start}-{g.end}")
        if qid in seen:
            errors.append(f"line {lineno}: duplicate id {qid}")
        seen.add(qid)
        questions.append(Question(qid, repo, text, category, gold))
    if errors:
        raise ValueError("golden set has problems:\n  " + "\n  ".join(errors))
    return questions


def validate_against_index(conn, questions: list[Question]) -> list[str]:
    """Every gold file must exist in the indexed (AST) repo and the lines must lie inside it."""
    problems: list[str] = []
    cache: dict[tuple[str, str], int | None] = {}
    for q in questions:
        try:
            get_repo_id(conn, q.repo)
        except KeyError:
            problems.append(f"{q.id}: repo '{q.repo}' is not indexed")
            continue
        for g in q.gold:
            key = (q.repo, g.path)
            if key not in cache:
                row = conn.execute(
                    "SELECT f.line_count FROM files f JOIN repos r ON r.id = f.repo_id "
                    "WHERE r.name = %s AND f.path = %s", key).fetchone()
                cache[key] = row[0] if row else None
            n = cache[key]
            if n is None:
                problems.append(f"{q.id}: file not found in '{q.repo}': {g.path}")
            elif g.end > n:
                problems.append(f"{q.id}: {g.path}:{g.start}-{g.end} runs past the end ({n} lines)")
    return problems


def oversized_gold(questions: list[Question], limit: int = 60) -> list[str]:
    """Warnings (not errors) for gold ranges longer than `limit` lines. A huge range is
    easy to hit with ANY chunking, which inflates scores; label the code that answers
    the question (e.g. the function body), not a whole class or file."""
    return [f"{q.id}: {g.path}:{g.start}-{g.end} is {g.end - g.start + 1} lines"
            for q in questions for g in q.gold if g.end - g.start + 1 > limit]


def gold_snippet(conn, repo: str, g: Gold, max_lines: int = 12) -> str:
    """The gold lines as stored in the index, numbered, for eyeballing labels."""
    row = conn.execute(
        "SELECT f.content FROM files f JOIN repos r ON r.id = f.repo_id "
        "WHERE r.name = %s AND f.path = %s", (repo, g.path)).fetchone()
    if not row or row[0] is None:
        return "  (file content not available)"
    lines = row[0].split("\n")[g.start - 1:g.end]
    out = [f"  {g.start + i:>5} | {ln}" for i, ln in enumerate(lines[:max_lines])]
    if len(lines) > max_lines:
        out.append(f"        ... ({len(lines) - max_lines} more lines)")
    return "\n".join(out)


# ---------- metrics ----------

@dataclass
class QResult:
    qid: str
    category: str
    ranks: list[int | None]   # per gold range: rank of the first overlapping chunk, or None

    @property
    def first(self) -> int | None:
        found = [r for r in self.ranks if r is not None]
        return min(found) if found else None


def overlaps(path: str, start: int, end: int, g: Gold) -> bool:
    return path == g.path and start <= g.end and g.start <= end


def gold_ranks(hits, gold) -> list[int | None]:
    """hits: objects with .path/.start_line/.end_line in rank order (best first)."""
    ranks: list[int | None] = [None] * len(gold)
    for rank, h in enumerate(hits, start=1):
        for i, g in enumerate(gold):
            if ranks[i] is None and overlaps(h.path, h.start_line, h.end_line, g):
                ranks[i] = rank
    return ranks


def hit_at(r: QResult, k: int) -> float:
    return 1.0 if r.first is not None and r.first <= k else 0.0


def recall_at(r: QResult, k: int) -> float:
    return sum(1 for x in r.ranks if x is not None and x <= k) / len(r.ranks)


def reciprocal_rank(r: QResult) -> float:
    return 1.0 / r.first if r.first is not None else 0.0


def summarize(results: list[QResult]) -> dict[str, float]:
    n = len(results)
    if n == 0:
        return {"n": 0}
    out: dict[str, float] = {"n": n}
    for k in KS:
        out[f"hit@{k}"] = sum(hit_at(r, k) for r in results) / n
    out["recall@5"] = sum(recall_at(r, 5) for r in results) / n
    out["mrr"] = sum(reciprocal_rank(r) for r in results) / n
    return out


def by_category(results: list[QResult]) -> dict[str, dict[str, float]]:
    return {c: summarize([r for r in results if r.category == c])
            for c in CATEGORIES if any(r.category == c for r in results)}


def paired_bootstrap(a: list[float], b: list[float], n_boot: int = 2000, seed: int = 0,
                     alpha: float = 0.05) -> tuple[float, float, float]:
    """Mean(b) - mean(a) over the same questions, with a percentile bootstrap CI.
    Resamples QUESTIONS (pairs) with replacement, so the pairing is preserved."""
    if len(a) != len(b) or not a:
        raise ValueError("need two equal-length, non-empty lists")
    n = len(a)
    diffs = [y - x for x, y in zip(a, b)]
    rng = random.Random(seed)
    boots = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return sum(diffs) / n, lo, hi


def per_question(results: list[QResult], metric) -> dict[str, float]:
    return {r.qid: metric(r) for r in results}


# ---------- running ----------

def arm_repo(repo: str, arm: str) -> str:
    return repo + FIXED_SUFFIX if arm == "fixed" else repo


def run_arm(conn, questions: list[Question], arm: str, mode: str, k: int = K_MAX) -> list[QResult]:
    """Run every question against one chunking arm ('ast' | 'fixed') with one retrieval mode."""
    ids: dict[str, int] = {}
    out: list[QResult] = []
    for q in questions:
        if q.repo not in ids:
            ids[q.repo] = get_repo_id(conn, arm_repo(q.repo, arm))
        hits = search(conn, ids[q.repo], q.text, k, mode)
        out.append(QResult(q.id, q.category, gold_ranks(hits, q.gold)))
    return out


def top_hits(conn, q: Question, arm: str, mode: str, k: int = 3):
    return search(conn, get_repo_id(conn, arm_repo(q.repo, arm)), q.text, k, mode)


def repo_stats(conn, name: str) -> dict:
    """What was indexed: commit, chunk counts, and size of the Python chunks
    (the only chunks that differ between the two arms)."""
    row = conn.execute("SELECT id, commit_sha FROM repos WHERE name = %s", (name,)).fetchone()
    if row is None:
        raise EvalSetupError(f"repo '{name}' is not indexed")
    rid, sha = row
    total, embedded = conn.execute(
        "SELECT count(*), count(embedding) FROM chunks WHERE repo_id = %s", (rid,)).fetchone()
    py_n, py_avg, py_med = conn.execute(
        "SELECT count(*), avg(end_line - start_line + 1), "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY end_line - start_line + 1) "
        "FROM chunks WHERE repo_id = %s AND path LIKE '%%.py'", (rid,)).fetchone()
    return {"name": name, "commit": sha, "chunks": total, "embedded": embedded,
            "py_chunks": py_n, "py_avg_lines": float(py_avg or 0), "py_median_lines": float(py_med or 0)}


def check_arms(conn, repos: list[str], baseline: bool) -> dict[str, dict]:
    """Fail loudly if the index is not in a state where the comparison would be valid."""
    stats: dict[str, dict] = {}
    for repo in repos:
        names = [repo] + ([repo + FIXED_SUFFIX] if baseline else [])
        for name in names:
            st = repo_stats(conn, name)
            if st["embedded"] != st["chunks"]:
                raise EvalSetupError(
                    f"'{name}' has {st['chunks'] - st['embedded']} chunks without embeddings; "
                    f"run: python embed_repo.py {name}")
            stats[name] = st
        if baseline:
            a, b = stats[repo]["commit"], stats[repo + FIXED_SUFFIX]["commit"]
            if a and b and a != b:
                raise EvalSetupError(
                    f"'{repo}' and '{repo}{FIXED_SUFFIX}' were indexed from different commits "
                    f"({a[:8]} vs {b[:8]}); re-ingest both from the same local checkout")
    return stats
