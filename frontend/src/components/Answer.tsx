import type { ReactNode } from "react";
import Markdown, { defaultUrlTransform } from "react-markdown";
import { linkifyCitations, parseCiteHref } from "../citations";
import type { AskResult, Range } from "../types";

interface Props {
  result: AskResult;
  onOpen: (r: Range) => void;
}

export default function Answer({ result, onOpen }: Props) {
  return (
    <div className="answer">
      <Markdown
        urlTransform={(url) => (url.startsWith("cite:") ? url : defaultUrlTransform(url))}
        components={{
          a: ({ href, children }: { href?: string; children?: ReactNode }) => {
            const range = href ? parseCiteHref(href) : null;
            if (range) {
              return (
                <button className="cite" onClick={() => onOpen(range)}>
                  {children}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            );
          },
        }}
      >
        {linkifyCitations(result.answer, result.citations)}
      </Markdown>

      {result.invalid_citations.length > 0 && (
        <p className="note">
          {result.invalid_citations.length} citation(s) removed: they pointed at lines that were not in
          the retrieved code.
        </p>
      )}

      {result.sources.length > 0 && (
        <details className="sources">
          <summary>Retrieved {result.sources.length} chunks</summary>
          {result.sources.map((s, i) => (
            <button
              key={i}
              className="source"
              onClick={() => onOpen({ path: s.path, start: s.start_line, end: s.end_line })}
            >
              <span className="mono">
                {s.path}:{s.start_line}-{s.end_line}
              </span>
              <span className="muted">
                {" "}
                {s.parent ? `${s.parent}.` : ""}
                {s.symbol ?? s.kind}
              </span>
            </button>
          ))}
        </details>
      )}
    </div>
  );
}
