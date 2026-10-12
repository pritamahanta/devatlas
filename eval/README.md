# Evaluation (Step 8)

Measures **retrieval** only (no LLM calls, no cost): does the right code show up in the top-k?

- **Chunking**: tree-sitter (function/method/class) vs naive fixed-size line windows.
- **Retrieval**: vector-only vs keyword-only vs symbol-only vs vector+keyword vs hybrid (all + symbol), fused with RRF.

## Workflow

```bash
# 1. Pick 3-4 mid-sized Python repos you can skim. Pin each to a tag so line numbers never drift.
git clone --branch <tag> https://github.com/<owner>/<repo> ~/eval-repos/<repo>

# 2. Index each repo TWICE from the SAME checkout (backend/, venv active, real embedding model!).
python ingest_repo.py ~/eval-repos/<repo> --name <repo> --embed
python ingest_repo.py ~/eval-repos/<repo> --name <repo> --chunker fixed --embed   # stored as <repo>@fixed

# 3. Write eval/golden.jsonl (format: see golden.example.jsonl), then check your labels:
python validate_golden.py ../eval/golden.jsonl --show

# 4. Run it once, with settings frozen, and keep the output.
python eval_retrieval.py ../eval/golden.jsonl --misses --json ../eval/results/run1.json
```

Finding gold ranges: `python lookup_symbol.py <repo> <name>` prints where a function is defined;
`python show_chunks.py <file.py>` shows chunk boundaries; open the file and read it.

## Labelling rules (these are what make the numbers defensible)

1. **Write the questions and gold ranges before you look at any retrieval output.** Do not edit a
   label to make a result look better. Fixing a genuinely wrong label is fine (re-run everything after).
2. **Gold = the code that answers the question**, not the whole class or file. Keep ranges short
   (`validate_golden.py` warns above 60 lines): a huge range is easy to hit with any chunking.
3. **Questions you could really ask** about an unfamiliar repo. Mix them: ~30% `lookup` (where is X),
   ~40% `behavior` (how does X work), ~30% `multi` (needs more than one place). Roughly equal per repo.
4. **Freeze settings before the final run** (`app/config.py`: `rrf_k`, `candidates_per_retriever`,
   `query_prefix`, embedding model). If you tune them, tune against some questions and report on
   questions you did not tune on. The reported table must come from a single run.
5. Aim for 30-50 questions. With n=40, one question is 2.5 points, so read the CI column
   (`*` = the 95% interval excludes 0) rather than the raw difference.

## What a hit means

A retrieved chunk is a hit if it is in the gold file and overlaps a gold range by at least one line.
`hit@k` = any gold range hit in the top k; `recall@5` = fraction of the question's gold ranges hit;
`mrr` = 1 / rank of the first hit. Overlap (not chunk identity) is what lets two chunkings be compared.
Bigger chunks overlap more easily, so this definition mildly favours the fixed-size baseline; the
report prints average chunk sizes for both arms.

## Known limits (say these yourself before an interviewer does)

- The "keyword" retriever is Postgres full-text search (`ts_rank_cd`), **not BM25**.
- The fixed-size baseline has no symbol table, so the symbol channel is only evaluated on AST chunking;
  the chunking comparison uses vector, keyword and vector+keyword.
- Baseline window is 40 lines / 10 overlap. A different window can change the gap; if you want to
  claim robustness, re-run with e.g. `--window 25` and `--window 60`.
- The questions are written by you for repos you chose; this is a small hand-labelled benchmark, not a
  general claim about code search.
