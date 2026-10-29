-- schema.sql
-- Chat history schema for the LLM chat-history PoC (PostgreSQL).
-- Table constraints here act as the second validation layer,
-- behind the Pydantic models in the application code.

CREATE TABLE IF NOT EXISTS users (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username   TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id),
    title      TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    model      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq             INT  NOT NULL CHECK (seq >= 0),
    role            TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content         TEXT NOT NULL CHECK (char_length(content) > 0),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL,
    -- The 'simple' text search config is used because PostgreSQL ships
    -- no Persian stemmer; it still tokenizes Persian text correctly.
    content_tsv     TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    -- This unique constraint also serves as the index for reading
    -- one conversation in message order.
    UNIQUE (conversation_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_created
    ON conversations (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_tsv
    ON messages USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS idx_messages_metadata
    ON messages USING GIN (metadata jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_messages_created_brin
    ON messages USING BRIN (created_at);