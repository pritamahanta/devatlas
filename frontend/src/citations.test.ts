import { describe, expect, it } from "vitest";
import { linkifyCitations, parseCiteHref } from "./citations";

const cites = [
  { path: "src/users.py", start_line: 4, end_line: 6, symbol: "create_user" },
  { path: "auth.py", start_line: 8, end_line: 8, symbol: null },
];

describe("linkifyCitations", () => {
  it("links validated citations, single-line and ranges", () => {
    const out = linkifyCitations("Hashes [src/users.py:4-6] then checks [auth.py:8].", cites);
    expect(out).toBe(
      "Hashes [`src/users.py:4-6`](cite:src%2Fusers.py:4-6) then checks [`auth.py:8`](cite:auth.py:8-8).",
    );
  });

  it("leaves unvalidated brackets, slices and links alone", () => {
    const text = "See [other.py:1-2], `x[1:3]`, [1], [docs](http://e.com).";
    expect(linkifyCitations(text, cites)).toBe(text);
  });
});

describe("parseCiteHref", () => {
  it("round-trips a link", () => {
    expect(parseCiteHref("cite:src%2Fusers.py:4-6")).toEqual({ path: "src/users.py", start: 4, end: 6 });
    expect(parseCiteHref("https://example.com")).toBeNull();
  });
});
