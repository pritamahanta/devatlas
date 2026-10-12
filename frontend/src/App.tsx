import { FormEvent, useEffect, useRef, useState } from "react";
import { ask, getRepos } from "./api";
import Answer from "./components/Answer";
import CodeViewer from "./components/CodeViewer";
import type { AskResult, Range, RepoInfo } from "./types";

interface Message {
  id: number;
  question: string;
  status: "loading" | "done" | "error";
  result?: AskResult;
  error?: string;
}

export default function App() {
  const [repos, setRepos] = useState<RepoInfo[]>([]);
  const [repo, setRepo] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [range, setRange] = useState<Range | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const nextId = useRef(1);
  const bottom = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    getRepos()
      .then((rs) => {
        setRepos(rs);
        const ready = rs.find((r) => r.embedded_chunks > 0) ?? rs[0];
        if (ready) setRepo(ready.name);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const busy = messages.some((m) => m.status === "loading");

  function changeRepo(name: string) {
    setRepo(name);
    setMessages([]);
    setRange(null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || !repo || busy) return;
    const id = nextId.current++;
    setInput("");
    setMessages((ms) => [...ms, { id, question, status: "loading" }]);
    try {
      const result = await ask(repo, question);
      setMessages((ms) => ms.map((m) => (m.id === id ? { ...m, status: "done", result } : m)));
      if (result.citations.length > 0) {
        const c = result.citations[0];
        setRange({ path: c.path, start: c.start_line, end: c.end_line });
      }
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      setMessages((ms) => ms.map((m) => (m.id === id ? { ...m, status: "error", error } : m)));
    }
  }

  return (
    <div className="app">
      <header>
        <h1>DevAtlas</h1>
        <span className="muted">Ask a codebase. Every answer links to the exact lines.</span>
        <select value={repo} onChange={(e) => changeRepo(e.target.value)} aria-label="Repository">
          {repos.length === 0 && <option value="">No repositories</option>}
          {repos.map((r) => (
            <option key={r.id} value={r.name}>
              {r.name} ({r.chunks} chunks)
            </option>
          ))}
        </select>
      </header>

      <main>
        <section className="chat">
          <div className="messages">
            {loadError && <div className="error">Could not reach the API: {loadError}</div>}
            {!loadError && messages.length === 0 && (
              <div className="empty">
                {repo
                  ? "Ask something like “where is authentication handled?” or “what does create_user do?”"
                  : "Index a repository first (see README), then reload."}
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className="turn">
                <div className="question">{m.question}</div>
                {m.status === "loading" && <div className="muted">Searching and reading the code…</div>}
                {m.status === "error" && <div className="error">{m.error}</div>}
                {m.status === "done" && m.result && <Answer result={m.result} onOpen={setRange} />}
              </div>
            ))}
            <div ref={bottom} />
          </div>
          <form onSubmit={submit}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={repo ? `Ask about ${repo}…` : "No repository selected"}
              disabled={!repo}
              aria-label="Question"
            />
            <button type="submit" disabled={!input.trim() || !repo || busy}>
              Ask
            </button>
          </form>
        </section>

        <section className="code-pane">
          <CodeViewer repo={repo} range={range} />
        </section>
      </main>
    </div>
  );
}
