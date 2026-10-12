from pathlib import Path

import pytest

from app.embeddings import HashingEmbedder, set_embedder
from app.retrieval import keyword_terms, rrf
from app.textutil import split_identifier


def test_split_identifier():
    assert split_identifier("get_user_byId") == ["get", "user", "by", "id"]
    assert split_identifier("HTTPServer2") == ["http", "server", "2"]


def test_keyword_terms():
    t = keyword_terms("Where is getUserById defined? and create_user")
    assert "getuserbyid" in t and "user" in t and "id" in t
    assert "create" in t and "createuser" not in t  # snake_case is split, not joined
    assert "where" not in t and "is" not in t       # stopwords dropped
    assert all(x.isalnum() for x in t)              # safe for to_tsquery


def test_keyword_terms_stemming_variants():
    t = keyword_terms("how are passwords hashed")
    assert {"passwords", "password", "hashed", "hash"} <= set(t)


def test_rrf_prefers_agreement():
    fused = rrf([[1, 2, 3], [3, 2, 9]], k=60)
    ids = [d for d, _ in fused]
    assert ids[:2] == [2, 3] or ids[:2] == [3, 2]   # in both lists -> on top
    assert set(ids) == {1, 2, 3, 9}
    one = rrf([[5, 6, 7]])
    assert [d for d, _ in one] == [5, 6, 7]         # single list keeps its order


def test_hashing_embedder_unit_norm():
    import numpy as np
    e = HashingEmbedder(384)
    v = e.embed_documents(["def hash_password(pw): return pw", "x"])
    assert v.shape == (2, 384)
    assert abs(float(np.linalg.norm(v[0])) - 1.0) < 1e-5


def _db_available() -> bool:
    try:
        from app.db import get_conn
        get_conn().close()
        return True
    except Exception:
        return False


REPO = "pytest-search-repo"


@pytest.fixture(scope="module")
def indexed(tmp_path_factory):
    if not _db_available():
        pytest.skip("Postgres not reachable")
    from app.db import get_conn
    from app.embed import embed_repo
    from app.ingest import ingest

    root: Path = tmp_path_factory.mktemp("repo")
    (root / "auth.py").write_text(
        "import hashlib\n\n\n"
        "def hash_password(password):\n"
        "    return hashlib.sha256(password.encode()).hexdigest()\n\n\n"
        "def verify_password(password, hashed):\n"
        "    return hash_password(password) == hashed\n"
    )
    (root / "users.py").write_text(
        "from auth import hash_password\n\n\n"
        "def create_user(name, password):\n"
        "    hashed = hash_password(password)\n"
        "    return db.insert('users', name, hashed)\n\n\n"
        "def getUserById(user_id):\n"
        "    return db.get('users', user_id)\n"
    )
    (root / "routes.py").write_text(
        "from users import create_user\n\n\n"
        "@app.post('/users')\n"
        "def post_user(body):\n"
        "    return create_user(body.name, body.password)\n"
    )
    (root / "payments.py").write_text(
        "def charge_card(card_number, amount):\n"
        "    return gateway.charge(card_number, amount)\n"
    )
    (root / "README.md").write_text("# Demo\n\nA tiny service with users and payments.\n")

    set_embedder(HashingEmbedder(384))
    ingest(str(root), name=REPO)
    n = embed_repo(REPO, progress=lambda *_: None)
    yield n
    set_embedder(None)
    with get_conn() as conn:
        conn.execute("DELETE FROM repos WHERE name = %s", (REPO,))


def _run(query, mode="hybrid", k=5):
    from app.db import get_conn
    from app.retrieval import get_repo_id, search
    with get_conn() as conn:
        return search(conn, get_repo_id(conn, REPO), query, k, mode)


def test_all_chunks_embedded(indexed):
    from app.db import get_conn
    with get_conn() as conn:
        total, emb = conn.execute(
            "SELECT count(*), count(embedding) FROM chunks c JOIN repos r ON r.id=c.repo_id "
            "WHERE r.name=%s", (REPO,)).fetchone()
    assert total > 0 and total == emb == indexed


def test_keyword_finds_snake_case_parts(indexed):
    hits = _run("how are passwords hashed with sha256", "keyword")
    assert "hash_password" in [h.symbol for h in hits[:2]]
    assert "charge_card" not in [h.symbol for h in hits]


def test_symbol_exact_match_first(indexed):
    hits = _run("what does create_user do", "symbol")
    assert [h.symbol for h in hits] == ["create_user"]
    hits = _run("explain getUserById", "symbol")
    assert hits[0].symbol == "getUserById"


def test_camel_case_keyword(indexed):
    hits = _run("getUserById", "keyword")
    assert hits and hits[0].symbol == "getUserById"


def test_vector_returns_ranked_chunks(indexed):
    hits = _run("hash password sha256", "vector")
    assert hits[0].symbol in ("hash_password", "verify_password")


def test_hybrid_fuses_sources(indexed):
    hits = _run("where is create_user and how does it hash the password", "hybrid")
    top = hits[0]
    assert top.symbol == "create_user"
    assert len(top.sources) >= 2  # agreed on by several retrievers
    assert any(h.symbol == "hash_password" for h in hits)


def test_api_search(indexed):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        r = client.get("/search", params={"repo": REPO, "q": "create_user", "k": 3})
        assert r.status_code == 200
        body = r.json()
        assert body["hits"][0]["symbol"] == "create_user"
        assert {"path", "start_line", "end_line", "snippet", "sources"} <= body["hits"][0].keys()
        assert client.get("/search", params={"repo": "nope", "q": "x"}).status_code == 404
        repos = client.get("/repos").json()
        mine = next(x for x in repos if x["name"] == REPO)
        assert mine["chunks"] == mine["embedded_chunks"] > 0
