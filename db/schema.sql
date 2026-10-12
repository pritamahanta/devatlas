CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE repos (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT,
    commit_sha  TEXT,
    indexed_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE files (
    id          SERIAL PRIMARY KEY,
    repo_id     INT REFERENCES repos(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    language    TEXT,
    line_count  INT
);

CREATE TABLE chunks (
    id          SERIAL PRIMARY KEY,
    repo_id     INT REFERENCES repos(id) ON DELETE CASCADE,
    file_id     INT REFERENCES files(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    start_line  INT NOT NULL,
    end_line    INT NOT NULL,
    symbol      TEXT,          -- e.g. create_user
    kind        TEXT,          -- function | method | class | doc | config
    parent      TEXT,          -- enclosing class, if any
    content     TEXT NOT NULL,
    embedding   vector(384),
    tsv         tsvector GENERATED ALWAYS AS (
                  to_tsvector('simple',
                    regexp_replace(coalesce(symbol,'') || ' ' || content, '[._/]', ' ', 'g'))
                ) STORED
);

CREATE INDEX chunks_tsv_idx ON chunks USING GIN (tsv);
CREATE INDEX chunks_emb_idx ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE symbols (
    id        SERIAL PRIMARY KEY,
    repo_id   INT REFERENCES repos(id) ON DELETE CASCADE,
    chunk_id  INT REFERENCES chunks(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    kind      TEXT,
    path      TEXT,
    line      INT
);
CREATE INDEX symbols_name_idx ON symbols (repo_id, name);

CREATE TABLE refs (
    id               SERIAL PRIMARY KEY,
    repo_id          INT REFERENCES repos(id) ON DELETE CASCADE,
    caller_chunk_id  INT REFERENCES chunks(id) ON DELETE CASCADE,
    callee_name      TEXT NOT NULL
);
CREATE INDEX refs_callee_idx ON refs (repo_id, callee_name);
