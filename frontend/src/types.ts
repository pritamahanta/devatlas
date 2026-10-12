export interface RepoInfo {
  id: number;
  name: string;
  url: string | null;
  files: number;
  chunks: number;
  embedded_chunks: number;
}

export interface Citation {
  path: string;
  start_line: number;
  end_line: number;
  symbol: string | null;
}

export interface SourceInfo {
  path: string;
  start_line: number;
  end_line: number;
  kind: string;
  symbol: string | null;
  parent: string | null;
  sources: Record<string, number>;
}

export interface AskResult {
  question: string;
  answer: string;
  citations: Citation[];
  invalid_citations: string[];
  cited: boolean;
  sources: SourceInfo[];
  model: string | null;
}

export interface FileData {
  path: string;
  language: string | null;
  line_count: number;
  content: string;
}

/** A line range in a file, 1-indexed and inclusive. */
export interface Range {
  path: string;
  start: number;
  end: number;
}
