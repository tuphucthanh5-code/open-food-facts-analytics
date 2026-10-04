CREATE TABLE IF NOT EXISTS raw_products (
    id               BIGSERIAL PRIMARY KEY,
    code             TEXT,
    retrieved_at     TIMESTAMPTZ,
    source_endpoint  TEXT,
    request_url      TEXT,
    http_status      INTEGER,
    page             INTEGER,
    source_file      TEXT NOT NULL,
    payload          JSONB NOT NULL,
    UNIQUE (code, source_file)
);

CREATE INDEX IF NOT EXISTS idx_raw_products_code ON raw_products (code);
