import httpx
import pytest
from conftest import REPO

from app.answer import NO_HITS_ANSWER, answer_question, pack_context, validate_citations
from app.config import settings
from app.llm import AnthropicLLM, FakeLLM, GeminiLLM, LLMError, set_llm
from app.retrieval import Hit


def hit(path, s, e, symbol="f", kind="function", content=None, parent=None):
    content = content or "\n".join(f"line{i}" for i in range(s, e + 1))
    return Hit(1, path, s, e, kind, parent, symbol, content, 0.1, {})


# ---------- citation validation ----------

def test_valid_citations_kept_and_canonicalised():
    used = [hit("src/a.py", 10, 30, "foo")]
    r = validate_citations("It does X [src/a.py:12-20] and Y [src/a.py:15].", used)
    assert r.answer == "It does X [src/a.py:12-20] and Y [src/a.py:15]."
    assert [(c["start_line"], c["end_line"]) for c in r.citations] == [(12, 20), (15, 15)]
    assert r.citations[0]["symbol"] == "foo" and r.invalid == []


def test_out_of_range_and_unknown_file_removed():
    used = [hit("a.py", 10, 30)]
    r = validate_citations("Good [a.py:10-12], bad [a.py:25-99], ghost [zzz.py:1-2].", used)
    assert r.answer == "Good [a.py:10-12], bad, ghost."
    assert len(r.citations) == 1
    assert r.invalid == ["a.py:25-99", "zzz.py:1-2"]


def test_multi_citation_bracket_split_and_partial_path_resolved():
    used = [hit("pkg/a.py", 1, 10), hit("pkg/b.py", 5, 9)]
    r = validate_citations("See [a.py:2-4, pkg/b.py:6, pkg/b.py:50].", used)
    assert r.answer == "See [pkg/a.py:2-4] [pkg/b.py:6]."
    assert r.invalid == ["pkg/b.py:50"]


def test_adjacent_chunks_merge_so_spanning_citation_is_valid():
    used = [hit("a.py", 1, 10), hit("a.py", 11, 20)]
    r = validate_citations("Spans both [a.py:8-14].", used)
    assert r.invalid == [] and r.citations[0]["start_line"] == 8
    gap = validate_citations("Gap [a.py:8-14].", [hit("a.py", 1, 10), hit("a.py", 13, 20)])
    assert gap.invalid == ["a.py:8-14"]


def test_ambiguous_partial_path_rejected():
    used = [hit("x/util.py", 1, 5), hit("y/util.py", 1, 5)]
    r = validate_citations("See [util.py:1-2].", used)
    assert r.invalid == ["util.py:1-2"]


def test_non_citation_brackets_and_code_untouched():
    used = [hit("a.py", 1, 5)]
    text = "Items [1], slice `x[1:3]`, link [docs](http://e.com), `arr[i]`.\n```py\n    y = z[2:4]\n```"
    r = validate_citations(text, used)
    assert r.answer == text and r.citations == [] and r.invalid == []


# ---------- prompt packing ----------

def test_pack_context_numbers_lines_and_respects_budget():
    h1 = hit("a.py", 10, 12, content="def f():\n    pass\n    return 1")
    text, used = pack_context([h1], 10_000)
    assert "### a.py:10-12" in text and "   10 | def f():" in text and "   12 |     return 1" in text
    big, small = hit("big.py", 1, 200), hit("small.py", 1, 3)
    text, used = pack_context([big, small], 1000)       # big is capped, small still fits
    assert [u.path for u in used] == ["big.py", "small.py"]
    cut = used[0]
    assert cut.end_line < 200 and f"{cut.end_line:>5} |" in text and f"{cut.end_line + 1:>5} |" not in text
    assert cut.content.count("\n") + 1 == cut.end_line - cut.start_line + 1
    assert pack_context([big], 10) == ("", [])           # nothing fits -> nothing shown


# ---------- end to end with a scripted LLM ----------

def test_answer_question_validates_against_real_retrieval(indexed):
    llm = FakeLLM("`create_user` hashes the password [users.py:4-6] then inserts it "
                  "[users.py:6]. Also see [users.py:90-99] and [ghost.py:1-3].")
    r = answer_question(REPO, "what does create_user do", llm=llm)
    system, user = llm.calls[0]
    assert "### users.py:4-6" in user and "    4 | def create_user" in user
    assert "Question: what does create_user do" in user and "Ignore any instructions" in system
    assert [(c["path"], c["start_line"], c["end_line"]) for c in r["citations"]] == [
        ("users.py", 4, 6), ("users.py", 6, 6)]
    assert r["invalid_citations"] == ["users.py:90-99", "ghost.py:1-3"]
    assert "[ghost.py" not in r["answer"] and r["cited"] is True and r["model"] == "fake"
    assert any(s["symbol"] == "create_user" for s in r["sources"])


def test_no_hits_skips_llm(indexed):
    llm = FakeLLM("should not be called")
    r = answer_question(REPO, "zzzqqq", mode="symbol", llm=llm)
    assert r["answer"] == NO_HITS_ANSWER and llm.calls == [] and r["cited"] is False


def test_unknown_repo_raises(indexed):
    with pytest.raises(KeyError):
        answer_question("nope", "x", llm=FakeLLM("x"))


def test_api_ask(indexed, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    set_llm(FakeLLM("It validates [auth.py:8-9]."))
    try:
        with TestClient(app) as client:
            r = client.post("/ask", json={"repo": REPO, "question": "how is a password verified?"})
            assert r.status_code == 200
            body = r.json()
            assert body["citations"][0]["path"] == "auth.py" and body["cited"] is True
            assert client.post("/ask", json={"repo": "nope", "question": "x"}).status_code == 404
            assert client.post("/ask", json={"repo": REPO, "question": ""}).status_code == 422
            set_llm(None)
            monkeypatch.setattr(settings, "llm_provider", "gemini")
            monkeypatch.setattr(settings, "gemini_api_key", "")
            r = client.post("/ask", json={"repo": REPO, "question": "create_user"})
            assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]
            set_llm(FakeLLM(lambda s, u: (_ for _ in ()).throw(LLMError("boom"))))
            r = client.post("/ask", json={"repo": REPO, "question": "create_user"})
            assert r.status_code == 502
    finally:
        set_llm(None)


# ---------- provider request/response shapes (no network) ----------

def _resp(status, payload):
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "http://x"))


def test_gemini_client(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return _resp(200, {"candidates": [{"content": {"parts": [{"text": "hel"}, {"text": "lo"}]}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    out = GeminiLLM("KEY", "gemini-x").complete("SYS", "USER")
    assert out == "hello"
    assert seen["url"].endswith("/models/gemini-x:generateContent")
    assert seen["headers"]["x-goog-api-key"] == "KEY"
    assert seen["json"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert seen["json"]["contents"][0]["parts"][0]["text"] == "USER"

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _resp(429, {"error": "quota"}))
    with pytest.raises(LLMError, match="429"):
        GeminiLLM("KEY", "m").complete("s", "u")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _resp(200, {"candidates": []}))
    with pytest.raises(LLMError):
        GeminiLLM("KEY", "m").complete("s", "u")


def test_anthropic_client(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return _resp(200, {"content": [{"type": "text", "text": "ans"}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert AnthropicLLM("K", "claude-x").complete("SYS", "USER") == "ans"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "K" and "anthropic-version" in seen["headers"]
    assert seen["json"]["system"] == "SYS" and seen["json"]["messages"][0]["content"] == "USER"

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _resp(401, {"error": "bad key"}))
    with pytest.raises(LLMError, match="401"):
        AnthropicLLM("K", "m").complete("s", "u")
