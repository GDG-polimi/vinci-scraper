-- Initial schema: documents, versions, attachments, fetch_log.
-- Timestamps are ISO-8601 UTC strings (e.g. 2026-11-18T09:30:00Z).

-- One row per crawled page in one language. The IT and EN versions of the same
-- page are two documents that share a doc_group (paired via hreflang, SCR-39).
-- Until a page is paired, doc_group is just its own canonical URL.
CREATE TABLE documents (
    id                   INTEGER PRIMARY KEY,
    url                  TEXT    NOT NULL UNIQUE,  -- canonical URL (SCR-11)
    host                 TEXT    NOT NULL,
    lang                 TEXT    NOT NULL CHECK (lang IN ('it', 'en')),
    doc_group            TEXT    NOT NULL,
    status               TEXT    NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'archived')),
    -- Consecutive fetch errors / absences from a listing; archived after 3 (SCR-29).
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    -- Validators from the last successful fetch, for conditional GET (SCR-31).
    etag                 TEXT,
    last_modified        TEXT,
    first_seen           TEXT    NOT NULL,
    last_seen            TEXT    NOT NULL,
    UNIQUE (doc_group, lang)
);

CREATE INDEX idx_documents_host_status ON documents (host, status);

-- Content history of a document. A new row is added only when the normalized
-- text hash changes; exactly one row per document has is_current = 1 (SCR-28).
CREATE TABLE versions (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    content_hash  TEXT    NOT NULL,  -- SHA-256 of the normalized text
    title         TEXT,
    text          TEXT    NOT NULL,
    snapshot_path TEXT,              -- compressed raw HTML snapshot (SCR-20)
    fetched_at    TEXT    NOT NULL,
    is_current    INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    UNIQUE (document_id, content_hash)
);

CREATE UNIQUE INDEX idx_versions_one_current
    ON versions (document_id) WHERE is_current = 1;

-- Files linked from a page (mostly PDFs under /fileadmin/), with extracted text.
-- The same file linked from two pages yields two rows (SCR-12).
CREATE TABLE attachments (
    id                 INTEGER PRIMARY KEY,
    parent_document_id INTEGER NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    url                TEXT    NOT NULL,
    content_type       TEXT,
    content_hash       TEXT,     -- SHA-256 of the extracted text
    text               TEXT,
    snapshot_path      TEXT,
    etag               TEXT,
    last_modified      TEXT,
    first_seen         TEXT    NOT NULL,
    last_seen          TEXT    NOT NULL,
    UNIQUE (parent_document_id, url)
);

CREATE INDEX idx_attachments_url ON attachments (url);

-- One row per HTTP request, successful or not (SCR-07). Not linked to documents
-- by key on purpose: requests for robots.txt, sitemaps or failed URLs belong here too.
CREATE TABLE fetch_log (
    id            INTEGER PRIMARY KEY,
    run_id        TEXT    NOT NULL,
    url           TEXT    NOT NULL,
    status        INTEGER,           -- NULL when no response (timeout, DNS, ...)
    error         TEXT,
    elapsed_ms    INTEGER,
    bytes         INTEGER,
    etag          TEXT,
    last_modified TEXT,
    content_hash  TEXT,
    fetched_at    TEXT    NOT NULL
);

CREATE INDEX idx_fetch_log_run ON fetch_log (run_id);
CREATE INDEX idx_fetch_log_url ON fetch_log (url);
