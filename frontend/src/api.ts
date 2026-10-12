import type { AskResult, FileData, RepoInfo } from "./types";

const BASE = "/api";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + url, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep status text */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const getRepos = () => request<RepoInfo[]>("/repos");

export const getFile = (repo: string, path: string) =>
  request<FileData>(`/file?repo=${encodeURIComponent(repo)}&path=${encodeURIComponent(path)}`);

export const ask = (repo: string, question: string, k = 8) =>
  request<AskResult>("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo, question, k }),
  });
