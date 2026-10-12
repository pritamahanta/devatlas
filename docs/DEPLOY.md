# Deploying DevAtlas (single VM, Docker Compose)

One Linux VM runs everything: Postgres + pgvector, the FastAPI backend, the React UI behind
nginx, and Caddy for automatic HTTPS. Demo repos are pre-indexed so visitors can ask questions
immediately.

## You need

- A Linux VM with Docker and Docker Compose **v2.24 or newer** (`docker compose version`).
- A domain (or subdomain) whose A record points at the VM, with ports 80 and 443 open.
- An LLM API key (Gemini or Anthropic) for `/ask`.

## Steps

```bash
git clone https://github.com/pritamahanta/devatlas && cd devatlas

# 1. Settings (both files are git-ignored)
cat > .env <<'EOF'
DOMAIN=demo.example.com
DB_PASSWORD=choose-a-long-random-password
EOF
cp backend/.env.example backend/.env      # then fill in ONE provider key

# 2. Build and start the stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app up -d --build

# 3. Pre-index the demo repos (edit scripts/demo_repos.txt to change them)
scripts/seed_demo.sh -f docker-compose.yml -f docker-compose.prod.yml

# 4. Check
curl https://demo.example.com/api/health
curl https://demo.example.com/api/repos
```

`DB_PASSWORD` is only applied when the database volume is first created. To change it later,
change it inside Postgres as well, or recreate the volume and re-run the seed step.

## Updating

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app up -d --build
```

Indexed data lives in the `pgdata` volume and survives rebuilds. If you change chunking or
embedding code, re-run `scripts/seed_demo.sh`.

## What protects the public demo

- Postgres and the backend are not published to the internet; only Caddy (80/443) is.
- nginx limits `/api/ask` to 10 requests/minute per client IP (burst of 5), because that endpoint
  spends your LLM quota. Check `limit_req_zone` in `frontend/nginx.conf` if you want a different rate.
- There is no ingest endpoint on the API; repos are added only through `scripts/seed_demo.sh`.
- Still set a spending/quota limit on the LLM key in the provider console. The per-IP limit does
  not stop many different IPs.

## Things to measure yourself

- Memory: the backend loads the embedding model at startup. Check `docker stats` on your VM
  before choosing a VM size.
- Indexing time per demo repo (the seed script prints progress). Embedding runs on CPU.
