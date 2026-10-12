from conftest import REPO
from fastapi.testclient import TestClient

from app.main import app


def test_file_endpoint_returns_full_text_matching_chunk_lines(indexed):
    with TestClient(app) as client:
        r = client.get("/file", params={"repo": REPO, "path": "users.py"})
        assert r.status_code == 200
        body = r.json()
        lines = body["content"].split("\n")
        assert lines[3].startswith("def create_user")       # line 4 (1-indexed)
        assert body["language"] == "python" and body["line_count"] == len(lines)

        hit = client.get("/search", params={"repo": REPO, "q": "create_user", "mode": "symbol"}).json()["hits"][0]
        chunk_lines = lines[hit["start_line"] - 1:hit["end_line"]]
        assert "\n".join(chunk_lines).startswith("def create_user")


def test_file_endpoint_404s(indexed):
    with TestClient(app) as client:
        assert client.get("/file", params={"repo": REPO, "path": "nope.py"}).status_code == 404
        assert client.get("/file", params={"repo": "nope", "path": "users.py"}).status_code == 404
        # no filesystem access: traversal-looking paths are just unknown keys
        assert client.get("/file", params={"repo": REPO, "path": "../../etc/passwd"}).status_code == 404
