import type { Citation, Range } from "./types";

// The backend returns validated citations as [path:a] or [path:a-b].
const CITE = /\[([^\[\]\n]+?):(\d+)(?:-(\d+))?\](?!\()/g;

/** Turn validated [path:a-b] citations in the answer into markdown links (cite:...).
 *  Only brackets that match a validated citation are touched, so code like x[1:3]
 *  and ordinary [text] are left alone. */
export function linkifyCitations(answer: string, citations: Citation[]): string {
  const known = new Set(citations.map((c) => `${c.path}:${c.start_line}-${c.end_line}`));
  return answer.replace(CITE, (match, path: string, a: string, b?: string) => {
    const start = Number(a);
    const end = b ? Number(b) : start;
    if (!known.has(`${path}:${start}-${end}`)) return match;
    const label = start === end ? `${path}:${start}` : `${path}:${start}-${end}`;
    return `[\`${label}\`](cite:${encodeURIComponent(path)}:${start}-${end})`;
  });
}

export function parseCiteHref(href: string): Range | null {
  const m = /^cite:(.+):(\d+)-(\d+)$/.exec(href);
  if (!m) return null;
  return { path: decodeURIComponent(m[1]), start: Number(m[2]), end: Number(m[3]) };
}
