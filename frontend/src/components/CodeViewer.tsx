import { useEffect, useRef, useState } from "react";
import { getFile } from "../api";
import type { FileData, Range } from "../types";

const cache = new Map<string, FileData>();

interface Props {
  repo: string;
  range: Range | null;
}

export default function CodeViewer({ repo, range }: Props) {
  const [data, setData] = useState<FileData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const firstLine = useRef<HTMLDivElement | null>(null);
  const path = range?.path;

  useEffect(() => {
    if (!path) return;
    const key = `${repo}\u0000${path}`;
    const hit = cache.get(key);
    if (hit) {
      setData(hit);
      setError(null);
      return;
    }
    let cancelled = false;
    setData(null);
    setError(null);
    getFile(repo, path)
      .then((f) => {
        cache.set(key, f);
        if (!cancelled) setData(f);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [repo, path]);

  useEffect(() => {
    firstLine.current?.scrollIntoView({ block: "center" });
  }, [data, range]);

  if (!range) {
    return <div className="viewer empty">Click a citation to see the code here.</div>;
  }

  const lines = data ? data.content.replace(/\r/g, "").split("\n") : [];
  if (lines.length && lines[lines.length - 1] === "") lines.pop();

  return (
    <div className="viewer">
      <div className="viewer-header">
        <span className="mono">{range.path}</span>
        <span className="muted">
          {" "}
          lines {range.start === range.end ? range.start : `${range.start}-${range.end}`}
        </span>
      </div>
      {error && <div className="error">Could not load file: {error}</div>}
      {!data && !error && <div className="muted pad">Loading…</div>}
      {data && (
        <div className="code">
          {lines.map((text, i) => {
            const n = i + 1;
            const hl = n >= range.start && n <= range.end;
            return (
              <div
                key={n}
                className={hl ? "line hl" : "line"}
                ref={n === range.start ? firstLine : undefined}
              >
                <span className="ln">{n}</span>
                <span className="src">{text || " "}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
