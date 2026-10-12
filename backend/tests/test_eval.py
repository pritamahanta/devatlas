"""Step 8: fixed-size baseline, golden-set loading, metrics, and an end-to-end eval run."""
import json
from types import SimpleNamespace

import numpy as np
import pytest
from psycopg import Rollback

from app import evaluation as ev
from app.baseline import FIXED_SUFFIX, chunk_fixed

# ---------- fixed-size chunker ----------


def test_chunk_fixed_ranges_overlap_and_cover_everything():
    src = "\n".join(f"line{i}" for i in range(1, 101))          # 100 lines
    chunks = chunk_fixed(src, "a.py", window=40, overlap=10)
    assert [(c.start_line, c.end_line) for c in chunks] == [(1, 40), (31, 70), (61, 100)]
    covered = {ln for c in chunks for ln in range(c.start_line, c.end_line + 1)}
    assert covered == set(range(1, 101))
    for c in chunks:                                              # content matches the ranges
        assert c.content.split("\n") == [f"line{i}" for i in range(c.start_line, c.end_line + 1)]
        assert c.kind == "window" and c.symbol is None and c.calls == []


def test_chunk_fixed_short_file_is_one_chunk_and_blank_windows_skipped():
    assert [(c.start_line, c.end_line) for c in chunk_fixed("x = 1\ny = 2\n", "a.py")] == [(1, 2)]
    assert chunk_fixed("\n\n\n", "a.py") == []
    gap = "a = 1\n" + "\n" * 60 + "b = 2\n"                       # a window of only blanks is dropped
    spans = [(c.start_line, c.end_line) for c in chunk_fixed(gap, "a.py", window=20, overlap=0)]
    assert spans[0] == (1, 20) and spans[-1][1] == 62 and (21, 40) not in spans


def test_chunk_fixed_rejects_bad_parameters():
    for w, o in [(0, 0), (10, 10), (10, -1)]:
        with pytest.raises(ValueError):
            chunk_fixed("x\n", "a.py", w, o)


# ---------- metrics ----------

def _hits(*spans):
    return [SimpleNamespace(path=p, start_line=s, end_line=e) for p, s, e in spans]


def test_overlap_requires_same_file_and_one_shared_line():
    g = ev.Gold("a.py", 10, 20)
    assert ev.overlaps("a.py", 20, 30, g) and ev.overlaps("a.py", 1, 10, g)
    assert not ev.overlaps("a.py", 21, 30, g) and not ev.overlaps("b.py", 10, 20, g)


def test_gold_ranks_first_overlapping_chunk_per_range():
    gold = (ev.Gold("a.py", 10, 20), ev.Gold("b.py", 5, 6), ev.Gold("c.py", 1, 2))
    ranks = ev.gold_ranks(_hits(("x.py", 1, 9), ("a.py", 1, 12), ("b.py", 1, 50), ("a.py", 15, 18)), gold)
    assert ranks == [2, 3, None]


def test_metrics_on_handmade_results():
    rs = [ev.QResult("q1", "lookup", [1]), ev.QResult("q2", "lookup", [4, None]),
          ev.QResult("q3", "multi", [None]), ev.QResult("q4", "multi", [7, 2])]
    s = ev.summarize(rs)
    assert s["n"] == 4
    assert s["hit@1"] == 0.25 and s["hit@3"] == 0.5 and s["hit@5"] == 0.75 and s["hit@10"] == 0.75
    assert s["mrr"] == pytest.approx((1 + 1 / 4 + 0 + 1 / 2) / 4)
    assert s["recall@5"] == pytest.approx((1 + 0.5 + 0 + 0.5) / 4)   # q4: only the rank-2 range is within 5
    assert ev.by_category(rs)["lookup"]["hit@1"] == 0.5


def test_paired_bootstrap():
    same = [1.0, 0.0, 1.0, 0.0] * 10
    assert ev.paired_bootstrap(same, same) == (0.0, 0.0, 0.0)
    worse = [0.0] * 40
    better = [1.0, 1.0, 1.0, 0.0] * 10
    d, lo, hi = ev.paired_bootstrap(worse, better)
    assert d == pytest.approx(0.75) and 0 < lo <= d <= hi
    assert ev.paired_bootstrap(worse, better, seed=3) == ev.paired_bootstrap(worse, better, seed=3)
    with pytest.raises(ValueError):
        ev.paired_bootstrap([1.0], [1.0, 0.0])


# ---------- golden file ----------

def _golden(tmp_path, *lines):
    p = tmp_path / "g.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return p


def _q(i="q1", **kw):
    d = {"id": i, "repo": "r", "question": "where is x?", "category": "lookup",
         "gold": [{"path": "a.py", "start": 1, "end": 3}]}
    d.update(kw)
    return json.dumps(d)


def test_load_golden_ok_ignores_comments_and_blank_lines(tmp_path):
    qs = ev.load_golden(_golden(tmp_path, "# a comment", "", _q("q1"), _q("q2", category="multi")))
    assert [q.id for q in qs] == ["q1", "q2"]
    assert qs[0].gold == (ev.Gold("a.py", 1, 3),)


def test_load_golden_reports_every_problem_with_line_numbers(tmp_path):
    with pytest.raises(ValueError) as e:
        ev.load_golden(_golden(tmp_path, _q("q1"), "{not json", _q("q1"),
                               _q("q3", category="weird"), _q("q4", gold=[]),
                               _q("q5", gold=[{"path": "a.py", "start": 9, "end": 2}])))
    msg = str(e.value)
    for needle in ("line 2", "duplicate id q1", "category must be", "at least one range", "bad range"):
        assert needle in msg


# ---------- against a real index (hash embedder: checks plumbing, NOT quality) ----------

REPO = "pytest-eval-repo"
FILES = {
    "auth.py": ("import hashlib\n\n\n"
                "def hash_password(password):\n"
                "    return hashlib.sha256(password.encode()).hexdigest()\n\n\n"
                "def verify_password(password, hashed):\n"
                "    return hash_password(password) == hashed\n"),
    "payments.py": ("def charge_card(card_number, amount):\n"
                    "    return gateway.charge(card_number, amount)\n"),
    "README.md": "# Demo\n\nA tiny service with users and payments.\n",
}


@pytest.fixture(scope="module")
def two_arms(indexed, tmp_path_factory):   # `indexed` skips without Postgres and installs the hash embedder
    from app.db import get_conn
    from app.embed import embed_repo
    from app.ingest import ingest

    root = tmp_path_factory.mktemp("evalrepo")
    for name, text in FILES.items():
        (root / name).write_text(text)
    ast = ingest(str(root), name=REPO)
    fixed = ingest(str(root), name=REPO, chunker="fixed", window=4, overlap=1)
    embed_repo(REPO, progress=lambda *_: None)
    embed_repo(REPO + FIXED_SUFFIX, progress=lambda *_: None)
    yield ast, fixed
    with get_conn() as conn:
        conn.execute("DELETE FROM repos WHERE name IN (%s, %s)", (REPO, REPO + FIXED_SUFFIX))


def _questions():
    return [
        ev.Question("t1", REPO, "how are passwords hashed", "behavior", (ev.Gold("auth.py", 4, 5),)),
        ev.Question("t2", REPO, "where is verify_password defined", "lookup", (ev.Gold("auth.py", 8, 9),)),
        ev.Question("t3", REPO, "how is a card charged", "behavior", (ev.Gold("payments.py", 1, 2),)),
    ]


def test_fixed_arm_differs_only_for_python_files(two_arms, indexed):
    from app.db import get_conn
    ast, fixed = two_arms
    assert fixed["repo"] == REPO + FIXED_SUFFIX and fixed["chunker"] == "fixed"
    assert ast["files"] == fixed["files"] and fixed["symbols"] == 0 and fixed["refs"] == 0
    with get_conn() as conn:
        def kinds(name):
            return dict(conn.execute(
                "SELECT c.kind, count(*) FROM chunks c JOIN repos r ON r.id = c.repo_id "
                "WHERE r.name = %s GROUP BY c.kind", (name,)).fetchall())
        assert set(kinds(REPO + FIXED_SUFFIX)) == {"window", "doc"}
        assert "function" in kinds(REPO) and "window" not in kinds(REPO)
        assert kinds(REPO)["doc"] == kinds(REPO + FIXED_SUFFIX)["doc"]   # docs identical in both arms


def test_validate_against_index_flags_bad_labels(two_arms):
    from app.db import get_conn
    bad = [ev.Question("b1", REPO, "q", "lookup", (ev.Gold("nope.py", 1, 2),)),
           ev.Question("b2", REPO, "q", "lookup", (ev.Gold("auth.py", 1, 500),)),
           ev.Question("b3", "no-such-repo", "q", "lookup", (ev.Gold("auth.py", 1, 2),))]
    with get_conn() as conn:
        assert ev.validate_against_index(conn, _questions()) == []
        msgs = ev.validate_against_index(conn, bad)
    assert len(msgs) == 3
    assert "file not found" in msgs[0] and "past the end" in msgs[1] and "not indexed" in msgs[2]


def test_run_arm_both_arms_and_all_modes(two_arms):
    from app.db import get_conn
    from app.retrieval import MODES
    qs = _questions()
    with get_conn() as conn:
        for arm in ("ast", "fixed"):
            for mode in MODES:
                res = ev.run_arm(conn, qs, arm, mode)
                assert [r.qid for r in res] == ["t1", "t2", "t3"]
        hybrid = ev.run_arm(conn, qs, "ast", "hybrid")
        symbol = ev.run_arm(conn, qs, "ast", "symbol")
    assert all(r.first is not None and r.first <= 3 for r in hybrid)   # tiny repo: lexical match is enough
    assert symbol[1].first == 1                                        # exact symbol name -> rank 1


def test_check_arms_requires_embeddings_and_same_commit(two_arms):
    from app.db import get_conn
    with get_conn() as conn:
        stats = ev.check_arms(conn, [REPO], baseline=True)
        assert set(stats) == {REPO, REPO + FIXED_SUFFIX}
        assert stats[REPO]["py_chunks"] > 0 and stats[REPO + FIXED_SUFFIX]["py_avg_lines"] > 0
        with conn.transaction():
            conn.execute("UPDATE chunks SET embedding = NULL WHERE id = ("
                         "SELECT min(c.id) FROM chunks c JOIN repos r ON r.id = c.repo_id WHERE r.name = %s)",
                         (REPO + FIXED_SUFFIX,))
            with pytest.raises(ev.EvalSetupError, match="without embeddings"):
                ev.check_arms(conn, [REPO], baseline=True)
            conn.execute("UPDATE repos SET commit_sha = 'a' WHERE name = %s", (REPO,))
            conn.execute("UPDATE repos SET commit_sha = 'b' WHERE name = %s", (REPO + FIXED_SUFFIX,))
            conn.execute("UPDATE chunks SET embedding = (SELECT embedding FROM chunks WHERE embedding IS NOT NULL LIMIT 1) "
                         "WHERE embedding IS NULL")
            with pytest.raises(ev.EvalSetupError, match="different commits"):
                ev.check_arms(conn, [REPO], baseline=True)
            raise Rollback   # undo the edits above; other tests share this fixture data


# ---------- regression: HNSW + repo filter must not under-fill ----------

def test_vector_search_fills_even_when_other_repos_crowd_the_index(indexed, monkeypatch):
    from pgvector.psycopg import register_vector  # noqa: F401  (registered by get_conn)

    from app.db import get_conn
    from app.retrieval import vector_search

    rng = np.random.default_rng(0)

    def unit(m):
        return (m / np.linalg.norm(m, axis=1, keepdims=True)).astype(np.float32)

    center = unit(rng.normal(size=(1, 384)))[0]
    crowd = unit(center + 0.15 * rng.normal(size=(500, 384)))   # repo A: 500 vectors hugging the query
    far = unit(rng.normal(size=(60, 384)))                      # repo B: unrelated vectors

    class Fake:
        def embed_query(self, _):
            return center

    monkeypatch.setattr("app.embeddings._embedder", Fake())
    sql = ("INSERT INTO chunks (repo_id, path, start_line, end_line, content, embedding) "
           "VALUES (%s, 'x.py', 1, 1, 'x', %s)")
    with get_conn() as conn:
        try:
            ids = [conn.execute("INSERT INTO repos (name) VALUES (%s) RETURNING id", (n,)).fetchone()[0]
                   for n in ("pytest-crowd-A", "pytest-crowd-B")]
            for rid, vecs in zip(ids, (crowd, far)):
                with conn.cursor() as cur:
                    cur.executemany(sql, [(rid, v) for v in vecs])
            conn.commit()
            with conn.transaction():
                # This table is tiny, so the planner would pick an exact seq scan by itself and
                # hide the bug. Real repos have thousands of chunks and use the HNSW index, so force it.
                conn.execute("SET LOCAL enable_seqscan = off")
                conn.execute("SET LOCAL hnsw.ef_search = 200")
                raw = conn.execute("SELECT id FROM chunks WHERE repo_id = %s ORDER BY embedding <=> %s LIMIT 30",
                                   (ids[1], center)).fetchall()
                assert len(raw) < 30     # premise: the plain index scan really does under-fill
                assert len(vector_search(conn, ids[1], "anything", 30)) == 30   # the fallback fills it
                assert len(vector_search(conn, ids[0], "anything", 30)) == 30
        finally:
            conn.rollback()
            conn.execute("DELETE FROM repos WHERE name IN ('pytest-crowd-A', 'pytest-crowd-B')")
            conn.commit()


def test_oversized_gold_warns_but_does_not_fail():
    qs = [ev.Question("a", "r", "q", "lookup", (ev.Gold("a.py", 1, 60),)),
          ev.Question("b", "r", "q", "multi", (ev.Gold("a.py", 1, 5), ev.Gold("b.py", 10, 90)))]
    assert ev.oversized_gold(qs) == ["b: b.py:10-90 is 81 lines"]
    assert ev.oversized_gold(qs, limit=4) == [
        "a: a.py:1-60 is 60 lines", "b: a.py:1-5 is 5 lines", "b: b.py:10-90 is 81 lines"]
