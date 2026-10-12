# DevAtlas

Repository knowledge assistant: ask questions about a codebase and get answers
with exact file and line-range citations.

## Quick start

```bash
docker compose up -d
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run it

```bash
# 1. database
docker compose up -d
docker compose exec -T db psql -U devatlas -d devatlas < db/migrations/002_file_content.sql  # existing DBs only

# 2. backend (in backend/, venv active)
cp .env.example .env            # add your LLM key
python ingest_repo.py <https-git-url | local-dir> --name myrepo --embed
uvicorn app.main:app --reload   # API on :8000, docs at /docs

# 3. frontend
cd ../frontend && npm install && npm run dev   # UI on http://localhost:5173
```

## Evaluate it

Retrieval-only benchmark (hit@k / MRR, AST vs fixed-size chunking, vector vs keyword vs hybrid).
See [eval/README.md](eval/README.md) for the workflow and labelling rules.

```bash
python ingest_repo.py ~/eval-repos/flask --name flask --embed
python ingest_repo.py ~/eval-repos/flask --name flask --chunker fixed --embed
python validate_golden.py ../eval/golden.example.jsonl --show
python eval_retrieval.py ../eval/golden.example.jsonl --misses
```
