# DevAtlas

Repository knowledge assistant: ask questions about an unfamiliar codebase and get answers
where every claim links to the exact file and line range.

![CI](https://github.com/pritamahanta/devatlas/actions/workflows/ci.yml/badge.svg)

## What it does

- **Code-aware chunking.** Python files are parsed with tree-sitter: one chunk per function or
  method, a header chunk per class, and chunks for leftover module-level code. Functions over 150
  lines are split into windows. Markdown and config files are chunked separately.
- **Hybrid retrieval.** Three retrievers run on every question: vector search (pgvector, local
  `BAAI/bge-small-en-v1.5` embeddings), keyword search (Postgres full-text, identifier-aware), and an
  exact symbol-name lookup. Results are merged with Reciprocal Rank Fusion (RRF).
- **Validated citations.** The model sees excerpts with line numbers and must cite
  `[path:start-end]`. The server then checks every citation against the lines the model was actually
  shown; citations that point elsewhere are removed from the answer and returned in `invalid`.
- **Code viewer UI.** Citations in the answer are clickable and open the file at the cited lines.
- **Evaluation harness.** A retrieval benchmark (hit@k, recall@5, MRR) compares AST vs fixed-size
  chunking and vector vs keyword vs hybrid retrieval. See [Evaluation](#evaluation).

Everything lives in one PostgreSQL database with the pgvector extension (chunks, vectors, full-text
index, symbols, call references). There is no separate vector database.

## Architecture

```
React UI ──► nginx ──► FastAPI ──┬─ ingest:   clone → filter → tree-sitter chunk → embed → Postgres
 (chat + code viewer)            │
                                 ├─ retrieve: vector + full-text + symbol → RRF
                                 │
                                 ├─ answer:   pack excerpts → LLM (Gemini or Anthropic) → validate citations
                                 │
                                 └─ PostgreSQL + pgvector: repos, files, chunks, symbols, refs
```

API endpoints: `GET /health`, `GET /repos`, `GET /search`, `POST /ask`, `GET /file`
(interactive docs at `/docs`). `/ask` returns one JSON response (no streaming).

## Quick start (Docker)

```bash
cp backend/.env.example backend/.env     # add ONE LLM API key (Gemini or Anthropic)
docker compose --profile app up -d --build
scripts/seed_demo.sh                     # pre-index the demo repos (takes a while on CPU)
# open http://localhost:8080
```

A plain `docker compose up -d` starts only the database, which is what you want for development.

## Development setup

```bash
# 1. database
docker compose up -d
docker compose exec -T db psql -U devatlas -d devatlas < db/migrations/002_file_content.sql  # existing DBs only

# 2. backend (in backend/, venv active)
python -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only torch first
pip install -r requirements.txt -r requirements-embed.txt
cp .env.example .env            # add your LLM key
python ingest_repo.py <https-git-url | local-dir> --name myrepo --embed
uvicorn app.main:app --reload   # API on :8000, docs at /docs

# 3. frontend
cd ../frontend && npm install && npm run dev   # UI on http://localhost:5173
```

Tests: `cd backend && pytest` (DB-backed tests are skipped if Postgres is not reachable) and
`cd frontend && npm test`. GitHub Actions runs both on every push.

## Evaluation

Retrieval-only benchmark: no LLM calls, no cost. See [eval/README.md](eval/README.md) for the full
workflow, the labelling rules and the known limits.

```bash
python ingest_repo.py ~/eval-repos/flask --name flask --embed
python ingest_repo.py ~/eval-repos/flask --name flask --chunker fixed --embed
python validate_golden.py ../eval/golden.jsonl --show
python eval_retrieval.py ../eval/golden.jsonl --misses --json ../eval/results/run1.json
```

### Results

_Not measured yet._ Fill this section from a single frozen run of `eval_retrieval.py`
(commit the JSON in `eval/results/`), and only with numbers that run produced.

| Setup | hit@1 | hit@5 | recall@5 | MRR |
|---|---|---|---|---|
| Fixed-size chunks, vector | | | | |
| AST chunks, vector | | | | |
| AST chunks, keyword (Postgres FTS) | | | | |
| AST chunks, vector + keyword | | | | |
| AST chunks, hybrid (+ symbol lookup) | | | | |

Benchmark: N questions over M repos (pinned tags), labelled by hand before looking at any results.

## Deployment

One VM with Docker Compose, automatic HTTPS and pre-indexed demo repos:
see [docs/DEPLOY.md](docs/DEPLOY.md).

## Known limits

- Python source only. Besides `.py`, only Markdown/rst/txt docs and common config files (toml, yaml,
  json, ini, cfg, Dockerfile, Makefile) are indexed; code in other languages is skipped.
- The keyword retriever is Postgres full-text ranking (`ts_rank_cd`), not BM25.
- Retrieval returns chunks as indexed; it does not yet pull in a hit's callers or callees. Call
  references are stored in the `refs` table (call sites matched by name, not resolved types), which
  is the basis for a possible flow-tracing feature.
- Citations are checked to point at lines the model was shown. That proves the location exists, not
  that the claim about it is correct.
