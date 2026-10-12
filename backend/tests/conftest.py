"""Shared fixtures: a tiny indexed + embedded repo in the real Postgres."""
import pytest

REPO = "pytest-search-repo"


def _db_available() -> bool:
    try:
        from app.db import get_conn
        get_conn().close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def indexed(tmp_path_factory):
    if not _db_available():
        pytest.skip("Postgres not reachable")
    from app.db import get_conn
    from app.embed import embed_repo
    from app.embeddings import HashingEmbedder, set_embedder
    from app.ingest import ingest

    root = tmp_path_factory.mktemp("repo")
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
