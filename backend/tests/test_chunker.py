from app.chunker import chunk_python

SAMPLE = '''import os
from fastapi import FastAPI

app = FastAPI()


def helper(x):
    return x + 1


@app.get("/users/{uid}")
def get_user(uid: int):
    """Fetch a user."""
    user = load(uid)
    return helper(user)


class UserService:
    """Handles users."""

    TABLE = "users"

    def create(self, name):
        row = self.repo.insert(name)
        return row

    @staticmethod
    def validate(name):
        return bool(name)

    class Inner:
        def ping(self):
            return pong()
'''


def by_symbol(chunks):
    return {(c.parent, c.symbol): c for c in chunks}


def test_kinds_and_symbols():
    chunks = chunk_python(SAMPLE, "svc.py")
    m = by_symbol(chunks)
    assert m[(None, "helper")].kind == "function"
    assert m[(None, "get_user")].kind == "function"
    assert m[(None, "UserService")].kind == "class"
    assert m[("UserService", "create")].kind == "method"
    assert m[("UserService", "validate")].kind == "method"
    assert m[("UserService", "Inner")].kind == "class"
    assert m[("UserService.Inner", "ping")].kind == "method"


def test_line_ranges_match_source():
    lines = SAMPLE.split("\n")
    for c in chunk_python(SAMPLE, "svc.py"):
        assert c.content == "\n".join(lines[c.start_line - 1:c.end_line])


def test_decorator_included_in_range():
    m = by_symbol(chunk_python(SAMPLE, "svc.py"))
    c = m[(None, "get_user")]
    assert c.content.startswith('@app.get("/users/{uid}")')
    m_static = m[("UserService", "validate")]
    assert m_static.content.lstrip().startswith("@staticmethod")


def test_class_header_excludes_methods():
    c = by_symbol(chunk_python(SAMPLE, "svc.py"))[(None, "UserService")]
    assert "Handles users" in c.content
    assert 'TABLE = "users"' in c.content
    assert "def create" not in c.content


def test_calls_extracted():
    m = by_symbol(chunk_python(SAMPLE, "svc.py"))
    assert set(m[(None, "get_user")].calls) == {"load", "helper"}
    assert m[("UserService", "create")].calls == ["insert"]


def test_module_chunk_for_leftover_code():
    mods = [c for c in chunk_python(SAMPLE, "svc.py") if c.kind == "module"]
    assert any("app = FastAPI()" in c.content for c in mods)


def test_oversized_function_is_split():
    body = "\n".join(f"    x{i} = {i}" for i in range(400))
    src = f"def big():\n{body}\n"
    parts = [c for c in chunk_python(src, "big.py") if c.symbol == "big"]
    assert len(parts) >= 3
    assert parts[0].start_line == 1
    assert all(p.end_line - p.start_line + 1 <= 150 for p in parts)


def test_embed_text_has_header():
    c = by_symbol(chunk_python(SAMPLE, "svc.py"))[("UserService", "create")]
    t = c.embed_text()
    assert "# file: svc.py" in t and "UserService.create" in t
