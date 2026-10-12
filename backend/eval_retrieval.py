"""Step 8: python eval_retrieval.py <golden.jsonl> [--no-baseline] [--misses] [--json out.json]

Retrieval-only evaluation (no LLM, no API cost). Prints markdown tables:
  A. retrieval modes on AST chunking      (vector / keyword / symbol / vector+keyword / hybrid)
  B. chunking: AST vs fixed-size windows  (same retrieval modes, same embedder)
  C. hit@5 by question category
with paired-bootstrap confidence intervals on the differences. Requires every repo
in the golden set to be indexed twice from the SAME checkout:
  python ingest_repo.py ~/eval-repos/flask --name flask --embed
  python ingest_repo.py ~/eval-repos/flask --name flask --chunker fixed --embed
"""
import argparse
import json
import sys
from datetime import datetime, timezone

from app import evaluation as ev
from app.config import settings
from app.db import get_conn

AST_MODES = ["vector", "keyword", "symbol", "vector+keyword", "hybrid"]
CHUNK_MODES = ["vector", "keyword", "vector+keyword"]   # no symbol table in the baseline
COLS = ["hit@1", "hit@3", "hit@5", "hit@10", "recall@5", "mrr"]


def pct(x: float) -> str:
    return f"{100 * x:.1f}"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def metric_row(label: str, results) -> list[str]:
    s = ev.summarize(results)
    return [label, str(s["n"])] + [pct(s[c]) if c != "mrr" else f"{s[c]:.3f}" for c in COLS]


def diff_row(label: str, base, other, n_boot: int) -> list[str]:
    """other - base on hit@5, paired over questions, in percentage points."""
    f = lambda r: ev.hit_at(r, 5)
    a, b = ev.per_question(base, f), ev.per_question(other, f)
    ids = [r.qid for r in base]
    d, lo, hi = ev.paired_bootstrap([a[i] for i in ids], [b[i] for i in ids], n_boot)
    sig = "" if lo <= 0 <= hi else " *"
    return [label, f"{100 * d:+.1f}", f"{100 * lo:+.1f} to {100 * hi:+.1f}{sig}"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("golden")
    ap.add_argument("--no-baseline", action="store_true", help="skip the fixed-size comparison")
    ap.add_argument("--misses", action="store_true", help="show questions hybrid missed in the top 10")
    ap.add_argument("--json", metavar="PATH", help="also write all results as JSON")
    ap.add_argument("--bootstrap", type=int, default=2000, help="bootstrap resamples")
    ap.add_argument("--allow-hash", action="store_true",
                    help="allow the offline hash embedder (pipeline smoke test ONLY; numbers are meaningless)")
    args = ap.parse_args()

    if settings.embed_backend == "hash" and not args.allow_hash:
        sys.exit("EMBED_BACKEND=hash is an offline test embedder, not a semantic model: these "
                 "numbers would be meaningless. Use the real model (see requirements-embed.txt).")
    try:
        questions = ev.load_golden(args.golden)
    except ValueError as e:
        sys.exit(str(e))
    repos = sorted({q.repo for q in questions})
    baseline = not args.no_baseline

    with get_conn() as conn:
        problems = ev.validate_against_index(conn, questions)
        if problems:
            sys.exit("golden set does not match the index:\n  " + "\n  ".join(problems)
                     + "\n(run validate_golden.py for details)")
        try:
            stats = ev.check_arms(conn, repos, baseline)
        except ev.EvalSetupError as e:
            sys.exit(f"setup problem: {e}")

        runs: dict[tuple[str, str], list[ev.QResult]] = {}
        for mode in AST_MODES:
            runs[("ast", mode)] = ev.run_arm(conn, questions, "ast", mode)
        if baseline:
            for mode in CHUNK_MODES:
                runs[("fixed", mode)] = ev.run_arm(conn, questions, "fixed", mode)
        misses = []
        if args.misses:
            for q, r in zip(questions, runs[("ast", "hybrid")]):
                if r.first is None:
                    misses.append((q, ev.top_hits(conn, q, "ast", "hybrid", 3)))

    n = len(questions)
    print(f"# DevAtlas retrieval evaluation  ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)\n")
    print(f"- questions: {n} over {len(repos)} repos; one question = {100 / n:.1f} points")
    print(f"- embedder: {settings.embed_model} ({settings.embed_backend}); "
          f"candidates/retriever={settings.candidates_per_retriever}, rrf_k={settings.rrf_k}")
    print("- hit = a retrieved chunk overlaps a gold range by >=1 line (see app/evaluation.py)\n")
    rows = []
    for name, st in stats.items():
        rows.append([name, (st["commit"] or "-")[:8], str(st["chunks"]), str(st["py_chunks"]),
                     f"{st['py_avg_lines']:.1f}", f"{st['py_median_lines']:.0f}"])
    print(md_table(["indexed repo", "commit", "chunks", ".py chunks", "avg lines", "median lines"], rows))

    print("\n## A. Retrieval modes (AST chunking)\n")
    print(md_table(["mode", "n"] + COLS, [metric_row(m, runs[("ast", m)]) for m in AST_MODES]))
    print("\nhit@5 difference vs baseline mode, 95% paired-bootstrap CI (percentage points; * = excludes 0)\n")
    pairs = [("hybrid vs vector", "vector", "hybrid"), ("hybrid vs keyword", "keyword", "hybrid"),
             ("vector+keyword vs vector", "vector", "vector+keyword"),
             ("hybrid vs vector+keyword (symbol lookup adds)", "vector+keyword", "hybrid")]
    print(md_table(["comparison", "diff", "95% CI"],
                   [diff_row(lbl, runs[("ast", a)], runs[("ast", b)], args.bootstrap) for lbl, a, b in pairs]))

    if baseline:
        print("\n## B. Chunking: AST vs fixed-size windows\n")
        rows = []
        for m in CHUNK_MODES:
            rows.append(metric_row(f"{m} / fixed", runs[("fixed", m)]))
            rows.append(metric_row(f"{m} / ast", runs[("ast", m)]))
        print(md_table(["mode / chunking", "n"] + COLS, rows))
        print("\nhit@5 difference, AST minus fixed, 95% paired-bootstrap CI (percentage points; * = excludes 0)\n")
        print(md_table(["retrieval mode", "diff", "95% CI"],
                       [diff_row(m, runs[("fixed", m)], runs[("ast", m)], args.bootstrap) for m in CHUNK_MODES]))

    print("\n## C. hit@5 by question category (AST chunking)\n")
    cats = list(ev.by_category(runs[("ast", "hybrid")]))
    sizes = {c: ev.by_category(runs[("ast", "hybrid")])[c]["n"] for c in cats}
    rows = []
    for m in AST_MODES:
        bc = ev.by_category(runs[("ast", m)])
        rows.append([m] + [pct(bc[c]["hit@5"]) for c in cats])
    print(md_table(["mode"] + [f"{c} (n={sizes[c]})" for c in cats], rows))

    if misses:
        print(f"\n## Questions hybrid missed in the top {ev.K_MAX} ({len(misses)})\n")
        for q, hits in misses:
            print(f"- **{q.id}** ({q.category}): {q.text}")
            print("  - gold: " + ", ".join(f"{g.path}:{g.start}-{g.end}" for g in q.gold))
            for h in hits:
                print(f"  - got:  {h.path}:{h.start_line}-{h.end_line} ({h.kind} {h.symbol or ''})")

    if args.json:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "golden": args.golden, "questions": n,
            "config": {"embed_model": settings.embed_model, "embed_backend": settings.embed_backend,
                       "candidates_per_retriever": settings.candidates_per_retriever,
                       "rrf_k": settings.rrf_k, "hnsw_ef_search": settings.hnsw_ef_search},
            "indexed": stats,
            "runs": {f"{arm}/{mode}": {
                "summary": ev.summarize(res), "by_category": ev.by_category(res),
                "per_question": {r.qid: r.ranks for r in res}} for (arm, mode), res in runs.items()},
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
