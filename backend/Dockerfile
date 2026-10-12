FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models

# git: ingest clones repositories with GitPython.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first (the default wheel pulls several GB of CUDA libraries).
COPY requirements.txt requirements-embed.txt ./
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt -r requirements-embed.txt

# Bake the embedding model into the image so startup needs no download.
# Keep this in sync with EMBED_MODEL in app/config.py.
ARG EMBED_MODEL=BAAI/bge-small-en-v1.5
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBED_MODEL}')"

COPY . .

# repos_cache/ is where ingest clones repositories.
RUN useradd --create-home app \
    && mkdir -p /app/repos_cache \
    && chown -R app:app /app/repos_cache \
    && chmod -R a+rX /models
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
