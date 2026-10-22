#!/bin/sh
# Runs only when a NEW remote PostgreSQL volume is initialized.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv app_password RAG_DB_APP_PASSWORD
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE rag_app LOGIN;
SELECT format('ALTER ROLE rag_app WITH PASSWORD %L', :'app_password') \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE ragdb TO rag_app;
GRANT USAGE ON SCHEMA public TO rag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO rag_app;
SQL
