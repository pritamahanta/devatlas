#!/usr/bin/env bash
# Pre-index the demo repos in scripts/demo_repos.txt into the running stack.
# Safe to re-run: ingest replaces a repo of the same name.
#
#   scripts/seed_demo.sh                                              # local stack
#   scripts/seed_demo.sh -f docker-compose.yml -f docker-compose.prod.yml   # production
set -euo pipefail
cd "$(dirname "$0")/.."

compose=(docker compose "$@" --profile app)

while read -r name url ref; do
  [[ -z "${name}" || "${name}" == \#* ]] && continue
  echo "==> ${name} @ ${ref}"
  # < /dev/null: stop `exec` from swallowing the rest of demo_repos.txt.
  "${compose[@]}" exec -T backend sh -c "
    set -e
    rm -rf /tmp/seed/${name}
    git clone --quiet --depth 1 --branch ${ref} ${url} /tmp/seed/${name}
    python ingest_repo.py /tmp/seed/${name} --name ${name} --embed
    rm -rf /tmp/seed/${name}
  " < /dev/null
done < scripts/demo_repos.txt

echo "Done. Indexed repos:"
"${compose[@]}" exec -T backend python -c "
import json, urllib.request
for r in json.load(urllib.request.urlopen('http://localhost:8000/repos')):
    print(f\"  {r['name']}: {r['files']} files, {r['chunks']} chunks, {r['embedded_chunks']} embedded\")
" < /dev/null
