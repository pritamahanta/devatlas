import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AskResult } from "../types";
import Answer from "./Answer";

const result: AskResult = {
  question: "q",
  answer:
    "`create_user` hashes the password [users.py:4-6] and checks `x[1:3]`.\n\n```py\nprint(1)\n```\n\nSee [ghost.py:1-2].",
  citations: [{ path: "users.py", start_line: 4, end_line: 6, symbol: "create_user" }],
  invalid_citations: ["zzz.py:9"],
  cited: true,
  sources: [
    { path: "users.py", start_line: 4, end_line: 6, kind: "function", symbol: "create_user", parent: null, sources: {} },
  ],
  model: "fake",
};

describe("Answer", () => {
  const html = renderToStaticMarkup(<Answer result={result} onOpen={() => {}} />);

  it("renders validated citations as buttons and leaves other text alone", () => {
    expect(html).toContain('<button class="cite"><code>users.py:4-6</code></button>');
    expect(html).toContain("x[1:3]");
    expect(html).toContain("[ghost.py:1-2]"); // not validated -> plain text, not a button
    expect((html.match(/class="cite"/g) ?? []).length).toBe(1);
  });

  it("renders markdown code, the removed-citation note and the sources list", () => {
    expect(html).toContain("<pre>");
    expect(html).toContain("1 citation(s) removed");
    expect(html).toContain("Retrieved 1 chunks");
    expect(html).toContain("users.py:4-6");
  });
});
